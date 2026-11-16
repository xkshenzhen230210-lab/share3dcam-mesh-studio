#pragma once
#include <osg/Array>
#include <osg/PrimitiveSet>
#include <array>
#include <vector>
#include <cstdint>
#include <cstring>
#include <future>
#include <thread>
#ifdef _WIN32
#include <windows.h>
#endif

// Stable full-precision depth ordering. No depth buckets, quantization or
// discarded splats: equal depths retain original record order, including +/-0.
struct GaussianDepthOrder {
 std::vector<uint64_t> keys,scratch;
 unsigned lastWorkers=1;
 static unsigned availableWorkers(){
  unsigned available=std::thread::hardware_concurrency();
#ifdef _WIN32
  DWORD_PTR mask=0,system=0;if(GetProcessAffinityMask(GetCurrentProcess(),&mask,&system)){available=0;for(;mask;mask>>=1)available+=unsigned(mask&1);}
#endif
  return std::max(1u,std::min(8u,available));
 }
 template<class F> static void parallel(unsigned workers,F task){
  std::vector<std::future<void>> jobs;jobs.reserve(workers-1);
  for(unsigned t=1;t<workers;t++)jobs.push_back(std::async(std::launch::async,task,t));
  task(0);for(auto& job:jobs)job.get();
 }
 void parallelSort(const osg::Vec3Array& positions,const osg::Vec3d& direction,osg::DrawElementsUInt& order,unsigned workers){
  const size_t count=positions.size();
  struct alignas(64) Buckets{std::array<size_t,256> values{};};
  std::vector<Buckets> hist(workers),offsets(workers);
  auto start=[&](unsigned t){return count*t/workers;};
  parallel(workers,[&](unsigned t){for(size_t i=start(t);i<start(t+1);i++){
   float depth=positions[i]*direction;uint32_t bits;if(depth==0)depth=0;std::memcpy(&bits,&depth,sizeof(bits));
   uint32_t key=~((bits&0x80000000u)?~bits:(bits^0x80000000u));keys[i]=(uint64_t(key)<<32)|uint32_t(i);hist[t].values[key&255]++;
  }});
  auto* input=&keys;auto* output=&scratch;
  for(unsigned pass=0;pass<4;pass++){
   unsigned shift=32+pass*8;
   if(pass)parallel(workers,[&](unsigned t){auto& h=hist[t].values;h.fill(0);for(size_t i=start(t);i<start(t+1);i++)h[((*input)[i]>>shift)&255]++;});
   size_t position=0;
   // Bucket-major, then contiguous input partition: preserve stability across
   // threads as well as within each thread, including equal-depth source ties.
   for(unsigned bucket=0;bucket<256;bucket++)for(unsigned t=0;t<workers;t++){offsets[t].values[bucket]=position;position+=hist[t].values[bucket];}
   parallel(workers,[&](unsigned t){auto& offset=offsets[t].values;for(size_t i=start(t);i<start(t+1);i++){auto key=(*input)[i];(*output)[offset[(key>>shift)&255]++]=key;}});
   std::swap(input,output);
  }
  parallel(workers,[&](unsigned t){for(size_t i=start(t);i<start(t+1);i++)order[i]=uint32_t((*input)[i]);});
 }
 size_t workspaceBytes()const{return (keys.capacity()+scratch.capacity())*sizeof(uint64_t);}
 void sort(const osg::Vec3Array& positions,const osg::Vec3d& direction,osg::DrawElementsUInt& order,unsigned workerHint=0){
  size_t count=positions.size();keys.resize(count);scratch.resize(count);order.resize(count);
  lastWorkers=workerHint?std::max(1u,std::min(8u,workerHint)):(count>=1000000?availableWorkers():1u);
  if(lastWorkers>1){parallelSort(positions,direction,order,lastWorkers);return;}
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
