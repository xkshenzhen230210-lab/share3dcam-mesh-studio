#define NOMINMAX
#include <windows.h>
#include <io.h>
#include <fcntl.h>
#include <osgViewer/Viewer>
#include <osgViewer/api/Win32/GraphicsWindowWin32>
#include <osg/ClipNode>
#include <osg/Geometry>
#include <osg/Geode>
#include <osg/LOD>
#include <osg/PagedLOD>
#include <osg/ProxyNode>
#include <osg/Texture2D>
#include <osg/Material>
#include <osg/Notify>
#include <osg/GLExtensions>
#include <osgUtil/SmoothingVisitor>
#include <osgDB/ReadFile>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <set>
#include <cmath>
#include <thread>
#include <functional>
#include "json.hpp"
#include "point_scene.h"
#include "render_memory.h"

using json=nlohmann::json;
namespace fs=std::filesystem;

// stdout is the raw-video transport. All OSG diagnostics must stay on stderr.
struct Diagnostics:osg::NotifyHandler {
 void notify(osg::NotifySeverity,const char* message) override {std::cerr<<message;}
};

void progress(const fs::path& path,const json& value){
 auto temporary=path;temporary+=".tmp";
 {std::ofstream output(temporary);output<<value.dump();if(!output)throw std::runtime_error("Cannot write render progress");}
 for(int retry=0;retry<8;retry++){
  if(MoveFileExW(temporary.c_str(),path.c_str(),MOVEFILE_REPLACE_EXISTING))return;
  std::this_thread::sleep_for(std::chrono::milliseconds(25*(retry+1)));
 }
 throw std::runtime_error("Cannot publish render progress");
}

// Resolve every finest-detail branch before the first frame. No paging or LOD
// transitions can then change scene detail while a frame is being exported.
struct FullDetail {
 std::set<fs::path> active;
 TextureMemory* memory=nullptr;
 std::function<void()> pageLoaded;
 osg::ref_ptr<osgDB::Options> options=new osgDB::Options("noRotation");
 osg::ref_ptr<osg::Node> file(fs::path path){
  path=fs::weakly_canonical(path);
  if(active.size()>=256||!active.insert(path).second)throw std::runtime_error("Cyclic or excessively deep OSGB reference: "+path.u8string());
  auto node=osgDB::readRefNodeFile(path.u8string(),options);
  if(!node)throw std::runtime_error("Cannot load model page: "+path.u8string());
  if(memory)memory->loaded(node);
  if(pageLoaded)pageLoaded();
  auto result=walk(node,path.parent_path());active.erase(path);return result;
 }
 fs::path external(const fs::path& folder,const std::string& database,const std::string& name){
  auto child=fs::u8path(name);if(child.is_absolute())return child;
  if(!database.empty()){
   auto base=fs::u8path(database);auto path=(base.is_absolute()?base:folder/base)/child;
   if(fs::is_regular_file(path))return path;
  }
  return folder/child;
 }
 osg::ref_ptr<osg::Group> replacement(osg::Node* original){
  auto group=new osg::Group;group->setName(original->getName());group->setNodeMask(original->getNodeMask());
  group->setStateSet(original->getStateSet());group->setCullingActive(original->getCullingActive());return group;
 }
 std::vector<unsigned> finest(osg::LOD* lod,unsigned count){
  if(lod->getNumRanges()<count)throw std::runtime_error("Incomplete OSGB LOD ranges");
  double sample=0;
  if(lod->getRangeMode()==osg::LOD::PIXEL_SIZE_ON_SCREEN){
   for(unsigned i=0;i<count;i++)sample=std::max(sample,double(lod->getMinRange(i)));
  }else if(count){
   sample=lod->getMinRange(0);for(unsigned i=1;i<count;i++)sample=std::min(sample,double(lod->getMinRange(i)));
  }
  std::vector<unsigned> selected;
  for(unsigned i=0;i<count;i++)if(lod->getMinRange(i)<=sample&&lod->getMaxRange(i)>sample)selected.push_back(i);
  if(count&&!selected.size())throw std::runtime_error("No valid finest-detail OSGB LOD range");return selected;
 }
 osg::ref_ptr<osg::Node> walk(osg::Node* node,const fs::path& folder){
  if(auto paged=dynamic_cast<osg::PagedLOD*>(node)){
   auto group=replacement(node);unsigned count=std::max(paged->getNumChildren(),paged->getNumFileNames());
   for(auto i:finest(paged,count)){
    if(i<paged->getNumFileNames()&&!paged->getFileName(i).empty())group->addChild(file(external(folder,paged->getDatabasePath(),paged->getFileName(i))));
    else if(i<paged->getNumChildren())group->addChild(walk(paged->getChild(i),folder));
    else throw std::runtime_error("Missing finest-detail OSGB child");
   }return group;
  }
  if(auto proxy=dynamic_cast<osg::ProxyNode*>(node)){
   auto group=replacement(node);unsigned count=std::max(proxy->getNumChildren(),proxy->getNumFileNames());
   for(unsigned i=0;i<count;i++){
    if(i<proxy->getNumFileNames()&&!proxy->getFileName(i).empty())group->addChild(file(external(folder,proxy->getDatabasePath(),proxy->getFileName(i))));
    else if(i<proxy->getNumChildren())group->addChild(walk(proxy->getChild(i),folder));
   }return group;
  }
  if(auto lod=dynamic_cast<osg::LOD*>(node)){
   auto group=replacement(node);for(auto i:finest(lod,lod->getNumChildren()))group->addChild(walk(lod->getChild(i),folder));return group;
  }
  if(auto group=node->asGroup())for(unsigned i=0;i<group->getNumChildren();i++)group->setChild(i,walk(group->getChild(i),folder));
  return node;
 }
};

struct DisplayMaterials:osg::NodeVisitor {
 DisplayMaterials():NodeVisitor(TRAVERSE_ALL_CHILDREN){}
 bool texture(osg::StateSet* state){
  if(!state)return false;auto attribute=state->getTextureAttribute(0,osg::StateAttribute::TEXTURE);
  if(auto texture=dynamic_cast<osg::Texture2D*>(attribute))if(!texture->getImage()||!texture->getImage()->data())throw std::runtime_error("Model texture is missing or could not be decoded");
  return attribute!=nullptr;
 }
 void apply(osg::Geode& node)override {
  for(unsigned i=0;i<node.getNumDrawables();i++)if(auto geometry=node.getDrawable(i)->asGeometry()){
   bool point=false;if(geometry->getUserValue("share_point",point)&&point)continue;
   auto state=geometry->getOrCreateStateSet();bool textured=texture(state);
   for(auto ancestor:getNodePath())if(texture(ancestor->getStateSet()))textured=true;
   state->setMode(GL_LIGHTING,(textured?osg::StateAttribute::OFF:osg::StateAttribute::ON)|osg::StateAttribute::OVERRIDE);
   if(!textured){if(!geometry->getNormalArray())osgUtil::SmoothingVisitor::smooth(*geometry);auto mat=new osg::Material;mat->setColorMode(osg::Material::AMBIENT_AND_DIFFUSE);mat->setAmbient(osg::Material::FRONT_AND_BACK,osg::Vec4(.3,.3,.3,1));state->setAttributeAndModes(mat,osg::StateAttribute::ON);}
   geometry->setUseDisplayList(false);geometry->setUseVertexBufferObjects(true);
  }traverse(node);
 }
};

osg::Vec3d vector(const json& camera,const char* key){
 auto values=camera.at(key).get<std::vector<double>>();
 if(values.size()!=3||!std::all_of(values.begin(),values.end(),[](double v){return std::isfinite(v);}))throw std::runtime_error("Invalid camera vector");
 return {values[0],values[1],values[2]};
}

void cameraPose(osg::Camera* camera,const json& pose,double aspect){
 auto eye=vector(pose,"eye"),center=vector(pose,"center"),up=vector(pose,"up");double fovy=pose.value("fovy",35.);
 if((center-eye).length2()<=1e-20||((center-eye)^up).length2()<=1e-20||!std::isfinite(fovy)||fovy<=1||fovy>=179)throw std::runtime_error("Degenerate camera pose");
 camera->setViewMatrixAsLookAt(eye,center,up);camera->setProjectionMatrixAsPerspective(fovy,aspect,.01,100000.);
}

int main(int argc,char** argv){
 fs::path progressPath;
 json graphics=json::object(),memoryReport=json::object();std::string phase="starting",errorKind="runtime";size_t completed=0;
 try{
  _setmode(_fileno(stdout),_O_BINARY);osg::setNotifyHandler(new Diagnostics);osg::setNotifyLevel(osg::WARN);
  if(argc!=2)throw std::runtime_error("Expected render job.json");
  std::ifstream input(fs::u8path(argv[1]));json job;input>>job;
  progressPath=fs::u8path(job.at("progress").get<std::string>());
  int width=job.at("width"),height=job.at("height");double fps=job.at("fps");auto& frames=job.at("frames");
  if(width<16||height<16||width>3840||height>2160||width%2||height%2||!std::isfinite(fps)||fps<1||fps>120||!frames.is_array()||frames.empty())throw std::runtime_error("Invalid render dimensions, frame rate or camera frames");
  // Validate all poses before committing any output bytes to the encoder.
  osg::ref_ptr<osg::Camera> poseValidator=new osg::Camera;for(auto& pose:frames)cameraPose(poseValidator,pose,double(width)/height);
  auto publish=[&](const std::string& next){phase=next;memoryReport["system"]=renderMemorySnapshot();progress(progressPath,{{"state",phase},{"frame",completed},{"total",frames.size()},{"graphics",graphics},{"memory",memoryReport}});};
  publish("loading");
  TextureMemory memory(progressPath.parent_path(),job.value("optimize_memory",true));
  FullDetail loader;loader.memory=&memory;PointScene points;osg::ref_ptr<osg::Node> model;
  size_t pages=0;loader.pageLoaded=[&](){pages++;progress(progressPath,{{"state","loading"},{"frame",0},{"pages",pages},{"total",frames.size()}});};
  if(points.load(fs::u8path(job.at("source").get<std::string>())))model=points.node;
  else model=loader.file(fs::u8path(job.at("source").get<std::string>()));publish("materials");DisplayMaterials materials;model->accept(materials);
  memoryReport=memory.report(model);
  osg::ref_ptr<osg::ClipNode> scene=new osg::ClipNode;scene->addChild(model);
  if(job.contains("clip_box")&&!job.at("clip_box").is_null()){
   auto b=job.at("clip_box").get<std::vector<double>>();
   if(b.size()!=6||!std::all_of(b.begin(),b.end(),[](double x){return std::isfinite(x);})||b[0]>=b[3]||b[1]>=b[4]||b[2]>=b[5])throw std::runtime_error("Invalid clipping box");
   points.setClip(true,b);
   if(!points.active)for(unsigned i=0;i<6;i++){osg::Vec4d p(0,0,0,0);p[i%3]=i<3?1:-1;p[3]=i<3?-b[i]:b[i];scene->addClipPlane(new osg::ClipPlane(i,p));}
  }
  // A small invisible pbuffer owns the GL context; the FBO owns export dimensions.
  std::string contextMode=job.value("context_mode",std::string("pbuffer"));
  if(contextMode!="pbuffer"&&contextMode!="window")throw std::runtime_error("Invalid graphics context mode");
  publish("context");
  osg::ref_ptr<osg::GraphicsContext::Traits> traits=new osg::GraphicsContext::Traits;
  traits->x=0;traits->y=0;traits->width=32;traits->height=32;traits->windowDecoration=false;
  traits->pbuffer=true;traits->doubleBuffer=false;traits->vsync=false;traits->depth=24;traits->alpha=8;
  osg::ref_ptr<osg::GraphicsContext> context;
  if(contextMode=="pbuffer")context=osg::GraphicsContext::createGraphicsContext(traits);
  HWND hidden=nullptr;
  if(!context){
   WNDCLASSW windowClass{};windowClass.style=CS_OWNDC;windowClass.lpfnWndProc=DefWindowProcW;windowClass.hInstance=GetModuleHandle(nullptr);windowClass.lpszClassName=L"ShareMeshRender";RegisterClassW(&windowClass);
   hidden=CreateWindowW(windowClass.lpszClassName,L"SHARE3DCAM Render",WS_POPUP,0,0,32,32,nullptr,nullptr,windowClass.hInstance,nullptr);
   if(!hidden)throw std::runtime_error("Cannot create hidden graphics window");
   contextMode="window";
   traits->pbuffer=false;traits->inheritedWindowData=new osgViewer::GraphicsWindowWin32::WindowData(hidden);context=osg::GraphicsContext::createGraphicsContext(traits);
  }
  if(!context)throw std::runtime_error("Cannot create offscreen OpenGL context");
  publish("initializing");
  osgViewer::Viewer viewer;viewer.setThreadingModel(osgViewer::Viewer::SingleThreaded);viewer.setReleaseContextAtEndOfFrameHint(false);
  auto camera=viewer.getCamera();camera->setGraphicsContext(context);camera->setViewport(0,0,width,height);camera->setClearColor(osg::Vec4(.055,.08,.12,1));
  camera->setRenderTargetImplementation(osg::Camera::FRAME_BUFFER_OBJECT);camera->setDrawBuffer(GL_COLOR_ATTACHMENT0_EXT);camera->setReadBuffer(GL_COLOR_ATTACHMENT0_EXT);
  osg::ref_ptr<osg::Image> image=new osg::Image;image->allocateImage(width,height,1,GL_RGB,GL_UNSIGNED_BYTE,1);
  if(points.gaussian)image->setInternalTextureFormat(GL_RGB32F_ARB);
  camera->attach(osg::Camera::COLOR_BUFFER,image);camera->attach(osg::Camera::DEPTH_BUFFER,GL_DEPTH_COMPONENT24);
  viewer.setSceneData(scene);viewer.realize();if(hidden)ShowWindow(hidden,SW_HIDE);
  if(!viewer.isRealized())throw std::runtime_error("Cannot realize offscreen OpenGL context");
  if(!context->makeCurrent())throw std::runtime_error("Cannot activate offscreen OpenGL context");
  auto glString=[](GLenum name){auto value=glGetString(name);return value?std::string(reinterpret_cast<const char*>(value)):std::string("unavailable");};
  auto extensions=osg::GLExtensions::Get(context->getState()->getContextID(),true);
  graphics={{"vendor",glString(GL_VENDOR)},{"renderer",glString(GL_RENDERER)},{"version",glString(GL_VERSION)},{"context_mode",contextMode}};
  std::cerr<<"Graphics: "<<graphics.dump()<<std::endl;publish("capabilities");
  if(!extensions||!extensions->isFrameBufferObjectSupported)throw std::runtime_error("OpenGL framebuffer objects unavailable; use the GPU manufacturer's driver and a local graphics session");
  GLint maxTexture=0,maxRenderbuffer=0;glGetIntegerv(GL_MAX_TEXTURE_SIZE,&maxTexture);glGetIntegerv(GL_MAX_RENDERBUFFER_SIZE_EXT,&maxRenderbuffer);
  graphics["max_texture_size"]=maxTexture;graphics["max_renderbuffer_size"]=maxRenderbuffer;
  if(std::max(width,height)>std::min(maxTexture,maxRenderbuffer))throw std::runtime_error("Requested video size exceeds this GPU's framebuffer limit");
  bool gpuMemoryInfo=osg::isGLExtensionSupported(context->getState()->getContextID(),"GL_NVX_gpu_memory_info");
  auto gpuMemory=[&](){if(gpuMemoryInfo){GLint dedicated=0,available=0;glGetIntegerv(0x9047,&dedicated);glGetIntegerv(0x9049,&available);
   if(dedicated>0)graphics["gpu_dedicated_bytes"]=int64_t(dedicated)*1024;
   if(available>=0)graphics["gpu_available_estimate_bytes"]=int64_t(available)*1024;
  }};gpuMemory();
  if(points.active)points.checkProgram(*context->getState());
  const size_t bytes=size_t(width)*height*3;
  for(size_t i=0;i<frames.size();i++){
   publish(i==0?"first_frame":"rendering");
   cameraPose(camera,frames[i],double(width)/height);points.update(camera);viewer.frame(double(i)/fps);
   if(i==0||i%30==0||i+1==frames.size()){TextureInventory resident;model->accept(resident);memoryReport["image_bytes_after_upload"]=resident.bytes;}
   auto glError=glGetError();
   if(glError==GL_OUT_OF_MEMORY){errorKind="gpu_memory";throw std::runtime_error("显存分配失败 / GPU memory allocation failed (OpenGL 1285); system RAM and GPU memory are separate limits");}
   if(glError!=GL_NO_ERROR)throw std::runtime_error("OpenGL rendering failed (error "+std::to_string(glError)+"); framebuffer unavailable");
   if(i==0||i%30==0||i+1==frames.size())gpuMemory();
   if(image->getTotalSizeInBytes()!=bytes)throw std::runtime_error("Unexpected framebuffer byte count");
   publish("encoding");
   if(fwrite(image->data(),1,bytes,stdout)!=bytes)throw std::runtime_error("Video encoder pipe closed");
   completed=i+1;publish("rendering");
  }
  publish("encoding");
  if(fflush(stdout)!=0)throw std::runtime_error("Cannot flush rendered frames");
  publish("closing");
  viewer.setDone(true);context->close();if(hidden)DestroyWindow(hidden);
  publish("succeeded");return 0;
 }catch(const std::exception& error){
  bool allocation=dynamic_cast<const std::bad_alloc*>(&error)!=nullptr;if(allocation)errorKind="system_memory";
  std::string message=allocation?"系统内存分配失败 / System memory allocation failed while "+phase:error.what();
  std::cerr<<message<<std::endl;
  memoryReport["system"]=renderMemorySnapshot();
  if(!progressPath.empty())try{progress(progressPath,{{"state","failed"},{"phase",phase},{"frame",completed},{"error",message},{"error_kind",errorKind},{"graphics",graphics},{"memory",memoryReport}});}catch(...){}
  return 1;
 }
}
