#pragma once
#include <osg/Array>
#include <osg/PrimitiveSet>
#include <array>
#include <vector>
#include <cstdint>
#include <cstring>

// Stable full-precision depth ordering. No depth buckets, quantization or
// discarded splats: equal depths retain original record order, including +/-0.
struct GaussianDepthOrder {
 std::vector<uint64_t> keys,scratch;
 void sort(const osg::Vec3Array& positions,const osg::Vec3d& direction,osg::DrawElementsUInt& order){
  size_t count=positions.size();keys.resize(count);scratch.resize(count);order.resize(count);
  std::array<std::array<size_t,256>,4> counts{};
  for(size_t i=0;i<count;i++){
   float depth=positions[i]*direction;uint32_t bits;
   if(depth==0)depth=0;std::memcpy(&bits,&depth,sizeof(bits));
   uint32_t ascending=(bits&0x80000000u)?~bits:(bits^0x80000000u),key=~ascending;
   keys[i]=(uint64_t(key)<<32)|uint32_t(i);
   for(unsigned pass=0;pass<4;pass++)counts[pass][(key>>(pass*8))&255]++;
  }
  auto* input=&keys;auto* output=&scratch;
  for(unsigned pass=0;pass<4;pass++){
   auto offsets=counts[pass];size_t start=0;
   for(auto& value:offsets){size_t size=value;value=start;start+=size;}
   unsigned shift=32+pass*8;
   for(auto entry:*input)(*output)[offsets[(entry>>shift)&255]++]=entry;
   std::swap(input,output);
  }
  for(size_t i=0;i<count;i++)order[i]=uint32_t((*input)[i]);
 }
};
