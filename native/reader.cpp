#include <osg/Geometry>
#include <osg/Geode>
#include <osg/Transform>
#include <osg/PagedLOD>
#include <osg/ProxyNode>
#include <osg/Texture2D>
#include <osg/Material>
#include <osg/TriangleIndexFunctor>
#include <osgDB/ReadFile>
#include <osgDB/WriteFile>
#include <fstream>
#include <filesystem>
#include <iostream>
#include <set>
#include <sstream>
#include <map>
#include <string_view>
#include <charconv>
#include "json.hpp"
using json=nlohmann::json;namespace fs=std::filesystem;
struct Triangles {std::vector<unsigned> ids;void operator()(unsigned a,unsigned b,unsigned c){ids.insert(ids.end(),{a,b,c});}};
std::string_view word(std::string_view& text){auto start=text.find_first_not_of(" \t\r");if(start==text.npos){text={};return {};};text.remove_prefix(start);auto end=text.find_first_of(" \t\r");auto result=text.substr(0,end);if(end==text.npos)text={};else text.remove_prefix(end);return result;}
double number(std::string_view& text){auto token=word(text);double value;auto result=std::from_chars(token.data(),token.data()+token.size(),value);if(result.ec!=std::errc()||result.ptr!=token.data()+token.size())throw std::runtime_error("Invalid OBJ number");return value;}
struct Extract {
 json manifest={{"parts",json::array()},{"textures",json::array()}};fs::path output;std::set<fs::path> active;std::vector<double> clipBox;
 explicit Extract(fs::path p):output(p){fs::create_directories(p);}
 void obj(fs::path path){
  std::ifstream f(path);if(!f)throw std::runtime_error("Cannot open OBJ");
  std::vector<osg::Vec3d> xyz;std::vector<osg::Vec2> uv;
  struct Batch{std::vector<osg::Vec3d> positions;std::vector<osg::Vec2> uv;};
  using Key=std::pair<std::string,bool>;std::map<Key,Batch> batches;size_t buffered=0;
  std::map<std::string,json> materials;std::string current,line;
  auto flush=[&](const Key& key,Batch& batch){
   auto& out=batch.positions;auto& outuv=batch.uv;if(out.empty())return;
   std::string name="part_"+std::to_string(manifest["parts"].size())+".bin";std::ofstream b(output/name,std::ios::binary);
   b.write((char*)out.data(),out.size()*24);if(key.second)b.write((char*)outuv.data(),outuv.size()*8);if(!b)throw std::runtime_error("Cannot write OBJ cache");
   json mat=materials.count(key.first)?materials[key.first]:json::object();
   manifest["parts"].push_back({{"buffer",name},{"vertices",out.size()},{"has_uv",key.second},{"texture",mat.value("texture",json(nullptr))},{"color",mat.value("color",json::array({1,1,1,1}))}});
   buffered-=out.size();out.clear();out.shrink_to_fit();outuv.clear();outuv.shrink_to_fit();
  };
  auto index=[](std::string_view s,size_t size){int64_t n;auto parsed=std::from_chars(s.data(),s.data()+s.size(),n);if(parsed.ec!=std::errc()||parsed.ptr!=s.data()+s.size())throw std::runtime_error("Invalid OBJ index");int64_t value=n>0?n-1:int64_t(size)+n;if(n==0||value<0||value>=int64_t(size))throw std::runtime_error("OBJ index invalid");return size_t(value);};
  while(std::getline(f,line)){
   if(line.empty()||line[0]=='#')continue;std::string_view rest(line);auto key=word(rest);
   if(key=="v"){double x=number(rest),y=number(rest),z=number(rest);xyz.emplace_back(x,y,z);}
   else if(key=="vt"){float u=number(rest),v=number(rest);uv.emplace_back(u,v);}
   else if(key=="usemtl"){current=std::string(word(rest));}
   else if(key=="mtllib"){
    auto start=rest.find_first_not_of(" \t");std::string file(rest.substr(start));if(!file.empty()&&file.back()=='\r')file.pop_back();std::ifstream m(path.parent_path()/fs::u8path(file));if(!m)throw std::runtime_error("Missing OBJ MTL: "+file);std::string ml,name;
    while(std::getline(m,ml)){std::istringstream ms(ml);std::string k;ms>>k;if(k=="newmtl"){ms>>name;materials[name]={{"color",{1,1,1,1}}};}else if(k=="Kd"){double a,b,c;ms>>a>>b>>c;materials[name]["color"]={a,b,c,1};}else if(k=="d"){double a;ms>>a;materials[name]["color"][3]=a;}else if(k=="map_Kd"){std::string tex;std::getline(ms>>std::ws,tex);if(!tex.empty()&&tex.front()=='-')throw std::runtime_error("OBJ map_Kd options unsupported");auto tp=path.parent_path()/fs::u8path(tex);if(!fs::is_regular_file(tp))throw std::runtime_error("Missing OBJ texture: "+tex);materials[name]["texture"]=manifest["textures"].size();manifest["textures"].push_back(tp.u8string());}}
   }
   else if(key=="f"){
    std::vector<std::string_view> corners;while(true){auto c=word(rest);if(c.empty()||c[0]=='#')break;corners.push_back(c);}if(corners.size()!=3)throw std::runtime_error("OBJ requires triangulated faces");
    bool faceUV=corners[0].find('/')!=std::string::npos&&corners[0].find("//")==std::string::npos;
    Key batchKey{current,faceUV};auto& batch=batches[batchKey];
    for(auto& corner:corners){auto slash=corner.find('/');batch.positions.push_back(xyz[index(corner.substr(0,slash),xyz.size())]);if(faceUV){auto end=corner.find('/',slash+1);batch.uv.push_back(uv[index(corner.substr(slash+1,end==std::string::npos?end:end-slash-1),uv.size())]);}}
    buffered+=3;
    if(batch.positions.size()>=300000)flush(batchKey,batch);
    // Material changes in the generated OBJ are frequent; batching avoids millions of tiny files.
    if(buffered>=3000000){auto largest=std::max_element(batches.begin(),batches.end(),[](auto&a,auto&b){return a.second.positions.size()<b.second.positions.size();});flush(largest->first,largest->second);}
   }
  }for(auto& item:batches)flush(item.first,item.second);
 }
 void file(fs::path p,osg::Matrixd matrix,osg::StateSet* inherited){
  p=fs::weakly_canonical(p);if(!active.insert(p).second)throw std::runtime_error("Cyclic OSGB reference");
  auto options=new osgDB::Options("noRotation");auto node=osgDB::readRefNodeFile(p.u8string(),options);
  if(!node)throw std::runtime_error("Cannot load "+p.u8string());walk(node,p.parent_path(),matrix,inherited);active.erase(p);
 }
 void walk(osg::Node* node,fs::path folder,osg::Matrixd matrix,osg::StateSet* inherited){
  osg::ref_ptr<osg::StateSet> state=new osg::StateSet;if(inherited)state->merge(*inherited);if(node->getStateSet())state->merge(*node->getStateSet());
  if(auto t=dynamic_cast<osg::Transform*>(node))t->computeLocalToWorldMatrix(matrix,nullptr);
  if(auto paged=dynamic_cast<osg::PagedLOD*>(node)){
   unsigned count=std::max(paged->getNumChildren(),paged->getNumFileNames());if(!count)return;
   unsigned best=0;for(unsigned i=1;i<count;i++)if(paged->getRangeMode()==osg::LOD::PIXEL_SIZE_ON_SCREEN ? paged->getMinRange(i)>paged->getMinRange(best):paged->getMinRange(i)<paged->getMinRange(best))best=i;
   if(best<paged->getNumFileNames()&&!paged->getFileName(best).empty())file(folder/fs::u8path(paged->getFileName(best)),matrix,state);
   else if(best<paged->getNumChildren())walk(paged->getChild(best),folder,matrix,state);
   return;
  }
  if(auto proxy=dynamic_cast<osg::ProxyNode*>(node)){
   for(unsigned i=0;i<proxy->getNumFileNames();i++)if(!proxy->getFileName(i).empty())file(folder/fs::u8path(proxy->getFileName(i)),matrix,state);
   if(proxy->getNumFileNames())return;
  }
  if(auto geode=node->asGeode())for(unsigned i=0;i<geode->getNumDrawables();i++){
   auto g=geode->getDrawable(i)->asGeometry();if(!g)continue;
   auto ss=new osg::StateSet;osg::ref_ptr<osg::StateSet> hold=ss;ss->merge(*state);if(g->getStateSet())ss->merge(*g->getStateSet());
   auto vertices=dynamic_cast<osg::Vec3Array*>(g->getVertexArray());auto vd=dynamic_cast<osg::Vec3dArray*>(g->getVertexArray());if(!vertices&&!vd)throw std::runtime_error("Unsupported vertex array");
   if(clipBox.size()==6){
    osg::BoundingBoxd bound;size_t count=vertices?vertices->size():vd->size();
    for(size_t k=0;k<count;k++)bound.expandBy((vertices?osg::Vec3d((*vertices)[k]):(*vd)[k])*matrix);
    bool outside=false;for(int axis=0;axis<3;axis++)if(bound._max[axis]<clipBox[axis]||bound._min[axis]>clipBox[axis+3])outside=true;
    if(outside)continue;
   }
   auto uv=dynamic_cast<osg::Vec2Array*>(g->getTexCoordArray(0));osg::TriangleIndexFunctor<Triangles> triangles;g->accept(triangles);
   json texture=nullptr;auto tex=dynamic_cast<osg::Texture2D*>(ss->getTextureAttribute(0,osg::StateAttribute::TEXTURE));
   if(tex&&tex->getImage()){
    int id=manifest["textures"].size();std::string name="texture_"+std::to_string(id)+".png";
    osg::ref_ptr<osgDB::Options> pngOptions=new osgDB::Options("PNG_COMPRESSION 1");
    if(!osgDB::writeImageFile(*tex->getImage(),(output/name).u8string(),pngOptions))throw std::runtime_error("Cannot extract texture");manifest["textures"].push_back(name);texture=id;
   }
   json color={1,1,1,1};if(auto mat=dynamic_cast<osg::Material*>(ss->getAttribute(osg::StateAttribute::MATERIAL))){auto c=mat->getDiffuse(osg::Material::FRONT);color={c[0],c[1],c[2],c[3]};}
   for(size_t start=0;start<triangles.ids.size();start+=300000){
    size_t end=std::min(start+300000,triangles.ids.size());std::string name="part_"+std::to_string(manifest["parts"].size())+".bin";std::ofstream f(output/name,std::ios::binary);
    for(size_t k=start;k<end;k++){auto id=triangles.ids[k];if(id>=(vertices?vertices->size():vd->size()))throw std::runtime_error("Invalid vertex index");osg::Vec3d p=(vertices?osg::Vec3d((*vertices)[id]):(*vd)[id])*matrix;f.write((char*)p.ptr(),24);}
    if(uv)for(size_t k=start;k<end;k++){auto id=triangles.ids[k];if(id>=uv->size())throw std::runtime_error("Invalid UV index");f.write((char*)(*uv)[id].ptr(),8);}
    if(!f)throw std::runtime_error("Cannot write extracted mesh");manifest["parts"].push_back({{"buffer",name},{"vertices",end-start},{"has_uv",uv!=nullptr},{"texture",texture},{"color",color}});
   }
  }
  if(auto group=node->asGroup())for(unsigned i=0;i<group->getNumChildren();i++)walk(group->getChild(i),folder,matrix,state);
 }
};
int main(int argc,char**argv){try{if(argc!=2)throw std::runtime_error("Expected job.json");std::ifstream f(fs::u8path(argv[1]));json job;f>>job;Extract e(fs::u8path(job.at("output").get<std::string>()));if(job.contains("clipBox"))e.clipBox=job["clipBox"].get<std::vector<double>>();auto source=fs::u8path(job.at("source").get<std::string>());auto ext=source.extension().string();std::transform(ext.begin(),ext.end(),ext.begin(),::tolower);if(ext==".obj")e.obj(source);else e.file(source,osg::Matrixd::identity(),nullptr);if(e.manifest["parts"].empty())throw std::runtime_error("No triangles found inside clipping box");std::ofstream out(e.output/"model.mesh");out<<e.manifest.dump(2);return 0;}catch(std::exception&e){std::cerr<<e.what();return 1;}}
