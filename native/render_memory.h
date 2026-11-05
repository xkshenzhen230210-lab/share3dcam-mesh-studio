#pragma once
#include <windows.h>
#include <psapi.h>
#include <osg/Geode>
#include <osg/Texture2D>
#include <osg/observer_ptr>
#include <filesystem>
#include <map>
#include <memory>
#include <set>
#include <vector>
#include <cstring>
#include <typeinfo>
#include "json.hpp"

inline nlohmann::json renderMemorySnapshot(){
 nlohmann::json result;MEMORYSTATUSEX system{};system.dwLength=sizeof(system);
 if(GlobalMemoryStatusEx(&system)){result["system_total_bytes"]=system.ullTotalPhys;result["system_available_bytes"]=system.ullAvailPhys;result["system_commit_available_bytes"]=system.ullAvailPageFile;}
 PROCESS_MEMORY_COUNTERS_EX process{};process.cb=sizeof(process);
 if(GetProcessMemoryInfo(GetCurrentProcess(),reinterpret_cast<PROCESS_MEMORY_COUNTERS*>(&process),sizeof(process))){
  result["process_private_bytes"]=process.PrivateUsage;result["process_commit_peak_bytes"]=process.PeakPagefileUsage;result["process_working_set_bytes"]=process.WorkingSetSize;
 }
 return result;
}

// Raw decoded pixels are immutable during offline rendering. Backing them with
// temporary files avoids committing every source texture to the process heap.
// Windows can evict these clean mapped pages without losing any source pixels.
struct PixelMapping {
 HANDLE file=INVALID_HANDLE_VALUE,mapping=nullptr;unsigned char* data=nullptr;
 PixelMapping(const PixelMapping&)=delete;PixelMapping& operator=(const PixelMapping&)=delete;
 ~PixelMapping(){if(data)UnmapViewOfFile(data);if(mapping)CloseHandle(mapping);if(file!=INVALID_HANDLE_VALUE)CloseHandle(file);}
 PixelMapping(const std::filesystem::path& path,const unsigned char* source,size_t bytes){
  file=CreateFileW(path.c_str(),GENERIC_READ|GENERIC_WRITE,FILE_SHARE_READ|FILE_SHARE_DELETE,nullptr,CREATE_NEW,
   FILE_ATTRIBUTE_TEMPORARY|FILE_FLAG_DELETE_ON_CLOSE,nullptr);
  if(file==INVALID_HANDLE_VALUE)throw std::runtime_error("Cannot create original-texture disk cache (Windows "+std::to_string(GetLastError())+")");
  try{
   for(size_t offset=0;offset<bytes;){DWORD written=0,part=DWORD(std::min<size_t>(bytes-offset,16*1024*1024));
    if(!WriteFile(file,source+offset,part,&written,nullptr)||written!=part)throw std::runtime_error("Cannot write original-texture disk cache; check free disk space");offset+=written;
   }
   mapping=CreateFileMappingW(file,nullptr,PAGE_READONLY,0,0,nullptr);
   if(!mapping)throw std::runtime_error("Cannot map original-texture disk cache (Windows "+std::to_string(GetLastError())+")");
   data=static_cast<unsigned char*>(MapViewOfFile(mapping,FILE_MAP_READ,0,0,bytes));
   if(!data)throw std::runtime_error("Cannot access original-texture disk cache (Windows "+std::to_string(GetLastError())+")");
  }catch(...){if(mapping)CloseHandle(mapping);CloseHandle(file);mapping=nullptr;file=INVALID_HANDLE_VALUE;throw;}
 }
};
struct DiskImage:osg::Image {
 std::unique_ptr<PixelMapping> pixels;
 DiskImage(const osg::Image& source,const std::filesystem::path& path):pixels(new PixelMapping(path,source.data(),source.getTotalSizeInBytesIncludingMipmaps())){
  setImage(source.s(),source.t(),source.r(),source.getInternalTextureFormat(),source.getPixelFormat(),source.getDataType(),
   pixels->data,NO_DELETE,source.getPacking(),source.getRowLength());
  setMipmapLevels(source.getMipmapLevels());setOrigin(source.getOrigin());setPixelAspectRatio(source.getPixelAspectRatio());
  setFileName(source.getFileName());setName(source.getName());setWriteHint(source.getWriteHint());setDataVariance(STATIC);
 }
};

struct TextureInventory:osg::NodeVisitor {
 std::set<const osg::Image*> images;std::set<const osg::Texture2D*> textures;uint64_t bytes=0;
 TextureInventory():NodeVisitor(TRAVERSE_ALL_CHILDREN){}
 void state(osg::StateSet* ss){if(!ss)return;
  for(unsigned unit=0;unit<ss->getTextureAttributeList().size();unit++)
   if(auto texture=dynamic_cast<osg::Texture2D*>(ss->getTextureAttribute(unit,osg::StateAttribute::TEXTURE))){
    textures.insert(texture);auto image=texture->getImage();if(image&&image->data()&&images.insert(image).second)bytes+=image->getTotalSizeInBytesIncludingMipmaps();
   }
 }
 void apply(osg::Node& node)override{state(node.getStateSet());traverse(node);}
 void apply(osg::Geode& node)override{state(node.getStateSet());for(unsigned i=0;i<node.getNumDrawables();i++)state(node.getDrawable(i)->getStateSet());traverse(node);}
};

struct TextureMemory:osg::NodeVisitor {
 bool enabled=true;std::filesystem::path folder;uint64_t beforeBytes=0,beforeImages=0,beforeTextures=0,mappedBytes=0,serial=0;
 std::map<uint64_t,std::vector<osg::observer_ptr<osg::Image>>> imagePool;
 std::map<osg::Image*,std::vector<osg::observer_ptr<osg::Texture2D>>> texturePool;
 std::set<osg::StateSet*> visited;
 explicit TextureMemory(std::filesystem::path path,bool optimize=true):NodeVisitor(TRAVERSE_ALL_CHILDREN),enabled(optimize),folder(path/"texture_cache"){}
 void loaded(osg::Node* node){TextureInventory inventory;node->accept(inventory);
  beforeBytes+=inventory.bytes;beforeImages+=inventory.images.size();beforeTextures+=inventory.textures.size();
  if(enabled){visited.clear();node->accept(*this);}
 }
 static bool equal(const osg::Image& a,const osg::Image& b){
  return a.s()==b.s()&&a.t()==b.t()&&a.r()==b.r()&&a.getPixelFormat()==b.getPixelFormat()&&a.getDataType()==b.getDataType()&&
   a.getInternalTextureFormat()==b.getInternalTextureFormat()&&a.getPacking()==b.getPacking()&&a.getRowLength()==b.getRowLength()&&
   a.getOrigin()==b.getOrigin()&&a.getPixelAspectRatio()==b.getPixelAspectRatio()&&a.getMipmapLevels()==b.getMipmapLevels()&&
   a.getTotalSizeInBytesIncludingMipmaps()==b.getTotalSizeInBytesIncludingMipmaps()&&
   std::memcmp(a.data(),b.data(),a.getTotalSizeInBytesIncludingMipmaps())==0;
 }
 static uint64_t bucket(const osg::Image& image){
  uint64_t size=image.getTotalSizeInBytesIncludingMipmaps(),hash=1469598103934665603ULL;
  // This only narrows candidates; full metadata and every byte are compared.
  for(uint64_t i=0;i<64&&size;i++){hash^=image.data()[(i*(size-1))/63];hash*=1099511628211ULL;}
  return hash^size;
 }
 osg::ref_ptr<osg::Image> image(osg::Image* original){
  auto& candidates=imagePool[bucket(*original)];
  for(auto& weak:candidates)if(auto saved=weak.get())if(saved==original||equal(*original,*saved))return saved;
  osg::ref_ptr<osg::Image> canonical=original;
  if(original->getTotalSizeInBytesIncludingMipmaps()>=256*1024){
   std::filesystem::create_directories(folder);
   canonical=new DiskImage(*original,folder/("pixels_"+std::to_string(serial++)+".bin"));mappedBytes+=original->getTotalSizeInBytesIncludingMipmaps();
  }
  candidates.push_back(canonical);return canonical;
 }
 void state(osg::StateSet* ss){if(!ss||!visited.insert(ss).second)return;
  for(unsigned unit=0;unit<ss->getTextureAttributeList().size();unit++){
   auto texture=dynamic_cast<osg::Texture2D*>(ss->getTextureAttribute(unit,osg::StateAttribute::TEXTURE));if(!texture)continue;
   auto original=texture->getImage();
   if(!original||typeid(*original)!=typeid(osg::Image)||!original->data()||!original->isDataContiguous()||original->requiresUpdateCall()||original->getPixelBufferObject()||
    original->getDataVariance()==osg::Object::DYNAMIC||texture->getDataVariance()==osg::Object::DYNAMIC||texture->getSubloadCallback()||texture->getReadPBuffer())continue;
   auto canonical=image(original);texture->setImage(canonical);
   texture->setUnRefImageDataAfterApply(true);
   auto& candidates=texturePool[canonical.get()];osg::Texture2D* shared=nullptr;
   for(auto& weak:candidates)if(auto saved=weak.get())if(saved==texture||saved->compare(*texture)==0){shared=saved;break;}
   if(shared&&shared!=texture){auto pair=ss->getTextureAttributePair(unit,osg::StateAttribute::TEXTURE);ss->setTextureAttribute(unit,shared,pair?pair->second:osg::StateAttribute::OFF);}
   else if(!shared)candidates.push_back(texture);
  }
 }
 void apply(osg::Node& node)override{state(node.getStateSet());traverse(node);}
 void apply(osg::Geode& node)override{state(node.getStateSet());for(unsigned i=0;i<node.getNumDrawables();i++)state(node.getDrawable(i)->getStateSet());traverse(node);}
 nlohmann::json report(osg::Node* node){TextureInventory after;node->accept(after);return {
  {"image_bytes_before",beforeBytes},{"image_bytes_after",after.bytes},{"images_before",beforeImages},{"images_after",after.images.size()},
  {"textures_before",beforeTextures},{"textures_after",after.textures.size()},{"mapped_image_bytes",mappedBytes},{"optimization",enabled}};}
};
