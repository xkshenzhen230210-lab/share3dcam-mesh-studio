#pragma once
#include <osg/GLExtensions>
#include <osg/State>
#include <osg/PrimitiveSet>
#include <osg/Array>
#include <stdexcept>
#include <string>
#include <vector>
#include <algorithm>
#include <numeric>
#include <cstring>
#include <limits>
#include <cmath>

// Complete stable 32-bit float-depth radix sort. GPU indices stay on the GPU.
// The optional NVIDIA subgroup path is capability checked; CPU sorting remains
// available on the original OpenGL 3.2 renderer. No depth buckets or thinning.
struct GpuDepthOrder {
 osg::ref_ptr<osg::GLExtensions> gl;
 HGLRC context=nullptr;
 bool attempted=false,active=false;
 bool mathChecked=false;const osg::Vec3Array* cpuPositions=nullptr;
 std::string reason;
 GLuint position=0,pairs[2]{},histogram=0,indices=0,status=0;
 GLuint generate=0,countProgram=0,scanProgram=0,addProgram=0,scatter=0,finish=0;
 std::vector<GLuint> buffers,programs;
 struct Level{GLuint prefix,sum;unsigned size;};std::vector<Level> levels;
 unsigned count=0,groups=0;size_t bytes=0;
 double minCoordinate=std::numeric_limits<double>::infinity();
 ~GpuDepthOrder(){release();}
 void release(){
  if(gl&&context==wglGetCurrentContext()){
   if(!buffers.empty())gl->glDeleteBuffers(GLsizei(buffers.size()),buffers.data());
   for(auto p:programs)gl->glDeleteProgram(p);
  }
  buffers.clear();programs.clear();levels.clear();active=false;indices=0;bytes=0;
 }
 GLuint buffer(size_t size,const void* data=nullptr){
  GLuint b=0;gl->glGenBuffers(1,&b);buffers.push_back(b);gl->glBindBuffer(GL_SHADER_STORAGE_BUFFER,b);
  gl->glBufferData(GL_SHADER_STORAGE_BUFFER,osg::GLsizeiptr(size),data,data?GL_STATIC_DRAW:GL_DYNAMIC_COPY);bytes+=size;
  if(glGetError()!=GL_NO_ERROR)throw std::runtime_error("GPU sort buffer allocation failed");return b;
 }
 GLuint program(const std::string& body,bool subgroup=false){
  std::string source="#version 430 compatibility\n";
  if(subgroup)source+="#extension GL_NV_shader_thread_group : require\n";
  source+="layout(local_size_x=256) in;uniform uint count;uniform uint groups;uniform uint shift;\n"
          "uint blockID(){return gl_WorkGroupID.y*gl_NumWorkGroups.x+gl_WorkGroupID.x;}\n"
          "uint itemID(){return blockID()*256u+gl_LocalInvocationIndex;}\n"+body;
  GLuint shader=gl->glCreateShader(GL_COMPUTE_SHADER);const char* text=source.c_str();gl->glShaderSource(shader,1,&text,nullptr);gl->glCompileShader(shader);
  GLint ok=0;gl->glGetShaderiv(shader,GL_COMPILE_STATUS,&ok);
  if(!ok){char log[4096]{};gl->glGetShaderInfoLog(shader,sizeof(log),nullptr,log);gl->glDeleteShader(shader);throw std::runtime_error(std::string("GPU sort shader: ")+log);}
  GLuint p=gl->glCreateProgram();programs.push_back(p);gl->glAttachShader(p,shader);gl->glLinkProgram(p);gl->glDeleteShader(shader);
  gl->glGetProgramiv(p,GL_LINK_STATUS,&ok);if(!ok){char log[4096]{};gl->glGetProgramInfoLog(p,sizeof(log),nullptr,log);throw std::runtime_error(std::string("GPU sort program: ")+log);}return p;
 }
 void bind(unsigned slot,GLuint b){gl->glBindBufferBase(GL_SHADER_STORAGE_BUFFER,slot,b);}
 void use(GLuint p,unsigned n,unsigned g=0,unsigned s=0){
  gl->glUseProgram(p);gl->glUniform1ui(gl->glGetUniformLocation(p,"count"),n);gl->glUniform1ui(gl->glGetUniformLocation(p,"groups"),g);gl->glUniform1ui(gl->glGetUniformLocation(p,"shift"),s);
 }
 void dispatch(unsigned blocks){
  unsigned x=std::min(4096u,std::max(1u,blocks));gl->glDispatchCompute(x,(blocks+x-1)/x,1);gl->glMemoryBarrier(GL_SHADER_STORAGE_BARRIER_BIT);
 }
 bool initialize(osg::State& state,const osg::Vec3Array& positions){
  if(attempted)return active;attempted=true;context=wglGetCurrentContext();gl=osg::GLExtensions::Get(state.getContextID(),true);
  if(!context||!gl||!gl->glDispatchCompute||!gl->glBindBufferBase||!gl->glUniform3f||
     !osg::isGLExtensionSupported(state.getContextID(),"GL_NV_shader_thread_group")){
   reason="Compute/subgroup support unavailable";return false;
  }
  GLint warp=0,maxBlock=0;glGetIntegerv(0x9339,&warp);glGetIntegerv(GL_MAX_SHADER_STORAGE_BLOCK_SIZE,&maxBlock);
  if(warp!=32||maxBlock<=0||positions.size()*sizeof(osg::Vec3)>size_t(maxBlock)||positions.size()*8>size_t(maxBlock)){
   reason="GPU sort buffer/subgroup limits";return false;
  }
  for(const auto& p:positions)for(unsigned k=0;k<3;k++)if(p[k]!=0)minCoordinate=std::min(minCoordinate,std::abs(double(p[k])));
  if(minCoordinate<std::numeric_limits<float>::min()){reason="Subnormal coordinates require CPU sorting";return false;}
  GLint previous=0;glGetIntegerv(GL_CURRENT_PROGRAM,&previous);
  try{
   static_assert(sizeof(osg::Vec3)==12,"Expected packed xyz");cpuPositions=&positions;count=unsigned(positions.size());groups=(count+255)/256;
   position=buffer(size_t(count)*12,&positions.front());pairs[0]=buffer(size_t(count)*8);pairs[1]=buffer(size_t(count)*8);
   histogram=buffer(size_t(groups)*16*4);indices=buffer(size_t(count)*4);status=buffer(4);
   for(unsigned n=groups*16;;n=(n+255)/256){unsigned blocks=(n+255)/256;levels.push_back({buffer(size_t(n)*4),buffer(size_t(blocks)*4),n});if(blocks<=1)break;}
   generate=program(R"GLSL(
struct Position{float x;float y;float z;};
layout(std430,binding=0)readonly buffer Positions{Position positions[];};
layout(std430,binding=1)writeonly buffer Pairs{uvec2 pairs[];};uniform vec3 direction;
void main(){uint i=itemID();if(i>=count)return;
 // Match osg::Vec3f::operator*: its RHS converts to Vec3f and every multiply
 // and left-associated add rounds in float32. Do not contract into an FMA.
 precise float a=positions[i].x*direction.x;
 precise float b=positions[i].y*direction.y;
 precise float c=positions[i].z*direction.z;
 precise float ab=a+b;precise float d=ab+c;
 if(d==0.0)d=0.0;uint bits=floatBitsToUint(d);
 uint key=~((bits&0x80000000u)!=0u?~bits:(bits^0x80000000u));pairs[i]=uvec2(key,i);
})GLSL");
   countProgram=program(R"GLSL(
layout(std430,binding=0)readonly buffer Pairs{uvec2 pairs[];};
layout(std430,binding=1)writeonly buffer Histogram{uint histogram[];};
layout(std430,binding=2)buffer Status{uint status;};shared uint warpCounts[128];
void main(){uint block=blockID();if(block>=groups)return;uint lane=gl_LocalInvocationIndex,warp=lane/32u,i=itemID();
 bool valid=i<count;uint digit=valid?(pairs[i].x>>shift)&15u:0u;
 if(gl_ThreadInWarpNV!=lane%32u)atomicOr(status,1u);
 for(uint b=0u;b<16u;b++){uint mask=ballotThreadNV(valid&&digit==b);if(lane%32u==0u)warpCounts[warp*16u+b]=uint(bitCount(mask));}
 barrier();if(lane<16u){uint total=0u;for(uint w=0u;w<8u;w++)total+=warpCounts[w*16u+lane];histogram[lane*groups+block]=total;}
})GLSL",true);
   scanProgram=program(R"GLSL(
layout(std430,binding=0)readonly buffer Input{uint values[];};
layout(std430,binding=1)writeonly buffer Prefix{uint prefix[];};
layout(std430,binding=2)writeonly buffer Sums{uint sums[];};shared uint scan[256];
void main(){uint block=blockID();if(block>=(count+255u)/256u)return;uint i=itemID(),lane=gl_LocalInvocationIndex;
 uint value=i<count?values[i]:0u;scan[lane]=value;barrier();
 for(uint offset=1u;offset<256u;offset*=2u){uint previous=lane>=offset?scan[lane-offset]:0u;barrier();scan[lane]+=previous;barrier();}
 if(i<count)prefix[i]=scan[lane]-value;if(lane==255u)sums[block]=scan[lane];
})GLSL");
   addProgram=program(R"GLSL(
layout(std430,binding=0)buffer Prefix{uint prefix[];};layout(std430,binding=1)readonly buffer Parent{uint parent[];};
void main(){uint i=itemID();if(i<count)prefix[i]+=parent[i/256u];}
)GLSL");
   scatter=program(R"GLSL(
layout(std430,binding=0)readonly buffer Input{uvec2 inputPairs[];};
layout(std430,binding=1)readonly buffer Prefix{uint prefix[];};
layout(std430,binding=2)writeonly buffer Output{uvec2 outputPairs[];};shared uint warpCounts[128];
layout(std430,binding=3)readonly buffer Status{uint status;};
void main(){uint block=blockID();if(block>=groups||status!=0u)return;uint lane=gl_LocalInvocationIndex,warp=lane/32u,i=itemID();
 bool valid=i<count;uvec2 value=valid?inputPairs[i]:uvec2(0);uint digit=(value.x>>shift)&15u,myMask=0u;
 for(uint b=0u;b<16u;b++){uint mask=ballotThreadNV(valid&&digit==b);if(lane%32u==0u)warpCounts[warp*16u+b]=uint(bitCount(mask));if(b==digit)myMask=mask;}
 barrier();if(!valid)return;uint rank=uint(bitCount(myMask&gl_ThreadLtMaskNV));
 for(uint w=0u;w<warp;w++)rank+=warpCounts[w*16u+digit];outputPairs[prefix[digit*groups+block]+rank]=value;
})GLSL",true);
   finish=program(R"GLSL(
layout(std430,binding=0)readonly buffer Input{uvec2 pairs[];};layout(std430,binding=1)writeonly buffer Output{uint indices[];};
void main(){uint i=itemID();if(i<count)indices[i]=pairs[i].y;}
)GLSL");
   active=true;
  }catch(const std::exception& error){reason=error.what();release();for(unsigned i=0;i<8&&glGetError()!=GL_NO_ERROR;i++){}}
  gl->glUseProgram(GLuint(previous));for(unsigned slot=0;slot<4;slot++)bind(slot,0);gl->glBindBuffer(GL_SHADER_STORAGE_BUFFER,0);return active;
 }
 void sort(const osg::Vec3d& direction){
  double minDirection=std::numeric_limits<double>::infinity();
  for(unsigned k=0;k<3;k++){float d=float(direction[k]);if(d!=0)minDirection=std::min(minDirection,std::abs(double(d)));}
  // GPU arithmetic may flush subnormals. Only use it where every nonzero
  // operand, product and possible cancellation stays in the normal range.
  const double minimum=std::numeric_limits<float>::min();
  if(minDirection<minimum||minCoordinate*minDirection<minimum*33554432.0)throw std::runtime_error("Float range requires exact CPU sorting");
  GLint previous=0;glGetIntegerv(GL_CURRENT_PROGRAM,&previous);
  unsigned zero=0;gl->glBindBuffer(GL_SHADER_STORAGE_BUFFER,status);gl->glBufferSubData(GL_SHADER_STORAGE_BUFFER,0,4,&zero);
  use(generate,count);bind(0,position);bind(1,pairs[0]);gl->glUniform3f(gl->glGetUniformLocation(generate,"direction"),float(direction.x()),float(direction.y()),float(direction.z()));dispatch(groups);
  if(!mathChecked){
   // A small initial readback checks the driver's arithmetic and xyz layout;
   // production frame ordering itself never downloads the full index array.
   std::vector<unsigned> sample(size_t(std::min(count,4096u))*2);
   gl->glMemoryBarrier(GL_BUFFER_UPDATE_BARRIER_BIT);gl->glBindBuffer(GL_SHADER_STORAGE_BUFFER,pairs[0]);gl->glGetBufferSubData(GL_SHADER_STORAGE_BUFFER,0,osg::GLsizeiptr(sample.size()*4),sample.data());
   for(unsigned i=0;i<sample.size()/2;i++){
    float depth=(*cpuPositions)[i]*direction;if(depth==0)depth=0;unsigned bits=0;std::memcpy(&bits,&depth,4);
    unsigned key=~((bits&0x80000000u)?~bits:(bits^0x80000000u));
    if(sample[i*2]!=key||sample[i*2+1]!=i){gl->glUseProgram(GLuint(previous));throw std::runtime_error("GPU arithmetic compatibility check failed");}
   }mathChecked=true;
  }
  unsigned input=0;
  for(unsigned pass=0;pass<8;pass++){
   use(countProgram,count,groups,pass*4);bind(0,pairs[input]);bind(1,histogram);bind(2,status);dispatch(groups);
   GLuint values=histogram;
   for(const auto& level:levels){use(scanProgram,level.size);bind(0,values);bind(1,level.prefix);bind(2,level.sum);dispatch((level.size+255)/256);values=level.sum;}
   for(size_t l=levels.size()-1;l>0;l--){auto& level=levels[l-1];use(addProgram,level.size);bind(0,level.prefix);bind(1,levels[l].prefix);dispatch((level.size+255)/256);}
   use(scatter,count,groups,pass*4);bind(0,pairs[input]);bind(1,levels[0].prefix);bind(2,pairs[1-input]);bind(3,status);dispatch(groups);input=1-input;
  }
  use(finish,count);bind(0,pairs[input]);bind(1,indices);dispatch(groups);
  gl->glMemoryBarrier(GL_ELEMENT_ARRAY_BARRIER_BIT|GL_BUFFER_UPDATE_BARRIER_BIT|GL_SHADER_STORAGE_BARRIER_BIT);
  unsigned mappingError=0;gl->glBindBuffer(GL_SHADER_STORAGE_BUFFER,status);gl->glGetBufferSubData(GL_SHADER_STORAGE_BUFFER,0,4,&mappingError);
  auto error=glGetError();gl->glUseProgram(GLuint(previous));for(unsigned slot=0;slot<4;slot++)bind(slot,0);gl->glBindBuffer(GL_SHADER_STORAGE_BUFFER,0);
  if(mappingError||error!=GL_NO_ERROR)throw std::runtime_error("GPU sorting failed validation or allocation");
 }
 std::vector<unsigned> readback(){
  std::vector<unsigned> result(count);gl->glBindBuffer(GL_SHADER_STORAGE_BUFFER,indices);gl->glGetBufferSubData(GL_SHADER_STORAGE_BUFFER,0,osg::GLsizeiptr(count)*4,result.data());gl->glBindBuffer(GL_SHADER_STORAGE_BUFFER,0);return result;
 }
};

struct GpuIndexElements:osg::DrawElementsUInt{
 GLuint gpuBuffer=0;
 GpuIndexElements():osg::DrawElementsUInt(GL_POINTS){}
 void draw(osg::State& state,bool useVbo)const override{
  if(!gpuBuffer){osg::DrawElementsUInt::draw(state,useVbo);return;}
  auto gl=osg::GLExtensions::Get(state.getContextID(),true);state.unbindElementBufferObject();
  gl->glBindBuffer(GL_ELEMENT_ARRAY_BUFFER_ARB,gpuBuffer);glDrawElements(GL_POINTS,GLsizei(size()),GL_UNSIGNED_INT,nullptr);gl->glBindBuffer(GL_ELEMENT_ARRAY_BUFFER_ARB,0);
 }
};
