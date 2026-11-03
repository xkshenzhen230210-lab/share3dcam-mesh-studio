#define NOMINMAX
#include <windows.h>
#include <osgViewer/Viewer>
#include <osgViewer/api/Win32/GraphicsWindowWin32>
#include <osgGA/TrackballManipulator>
#include <osg/ClipNode>
#include <osg/Geometry>
#include <osg/Geode>
#include <osg/PolygonMode>
#include <osg/LineWidth>
#include <osg/Texture2D>
#include <osg/Material>
#include <osgUtil/SmoothingVisitor>
#include <osg/ComputeBoundsVisitor>
#include <osg/PagedLOD>
#include <osgDB/ReadFile>
#include <fstream>
#include <filesystem>
#include <thread>
#include <iostream>
#include "json.hpp"
using json=nlohmann::json;namespace fs=std::filesystem;
struct CoarseBounds:osg::ComputeBoundsVisitor {
 fs::path folder;unsigned depth=0;
 explicit CoarseBounds(fs::path path):folder(path){}
 void apply(osg::PagedLOD& node)override {
  // Placeholder children have no bounds; real coarse geometry is sufficient for fitting.
  osg::ComputeBoundsVisitor local;
  for(unsigned i=0;i<node.getNumChildren();i++)node.getChild(i)->accept(local);
  if(local.getBoundingBox().valid()){traverse(node);return;}
  if(depth>=8)return;
  for(unsigned i=0;i<node.getNumFileNames();i++)if(!node.getFileName(i).empty()){
   auto path=folder/fs::u8path(node.getFileName(i));auto child=osgDB::readRefNodeFile(path.u8string());
   if(child){auto previous=folder;folder=path.parent_path();depth++;child->accept(*this);depth--;folder=previous;break;}
  }
 }
};
struct DisplayMaterials:osg::NodeVisitor {
 DisplayMaterials():NodeVisitor(TRAVERSE_ALL_CHILDREN){}
 void apply(osg::Geode& node)override {
  for(unsigned i=0;i<node.getNumDrawables();i++)if(auto g=node.getDrawable(i)->asGeometry()){
   if(g->getUserValue("share_display",done)&&done)continue;
   auto state=g->getOrCreateStateSet();bool textured=state->getTextureAttribute(0,osg::StateAttribute::TEXTURE)!=nullptr;
   for(auto n:getNodePath())if(n->getStateSet()&&n->getStateSet()->getTextureAttribute(0,osg::StateAttribute::TEXTURE))textured=true;
   state->setMode(GL_LIGHTING,(textured?osg::StateAttribute::OFF:osg::StateAttribute::ON)|osg::StateAttribute::OVERRIDE);
   if(!textured){if(!g->getNormalArray())osgUtil::SmoothingVisitor::smooth(*g);auto mat=new osg::Material;mat->setColorMode(osg::Material::AMBIENT_AND_DIFFUSE);mat->setAmbient(osg::Material::FRONT_AND_BACK,osg::Vec4(.3,.3,.3,1));state->setAttributeAndModes(mat,osg::StateAttribute::ON);}
   g->setUserValue("share_display",true);
  }traverse(node);
 }
 bool done=false;
};
void state(json value){std::ofstream f("state.tmp");f<<value.dump();f.close();MoveFileExW(L"state.tmp",L"state.json",MOVEFILE_REPLACE_EXISTING);}
int main(int argc,char**argv){try{
 if(argc!=2)throw std::runtime_error("Expected job.json");std::ifstream jf(fs::u8path(argv[1]));json job;jf>>job;
 osg::ref_ptr<osgDB::Options> readOptions=new osgDB::Options("noRotation");
 auto model=osgDB::readRefNodeFile(job.at("source").get<std::string>(),readOptions);if(!model)throw std::runtime_error("Cannot load model");
 HWND parent=(HWND)job.at("parent").get<uint64_t>();if(!IsWindow(parent))throw std::runtime_error("Viewer parent closed");
 WNDCLASSW wc{};wc.style=CS_OWNDC;wc.lpfnWndProc=DefWindowProcW;wc.hInstance=GetModuleHandle(nullptr);wc.lpszClassName=L"ShareMeshView";RegisterClassW(&wc);
 RECT r;GetClientRect(parent,&r);int w=std::max(10L,r.right),h=std::max(10L,r.bottom);
 HWND child=CreateWindowW(wc.lpszClassName,L"SHARE3DCAM 3D",WS_CHILD|WS_VISIBLE|WS_CLIPSIBLINGS|WS_CLIPCHILDREN,0,0,w,h,parent,nullptr,wc.hInstance,nullptr);
 auto traits=new osg::GraphicsContext::Traits;traits->x=0;traits->y=0;traits->width=w;traits->height=h;traits->windowDecoration=false;traits->doubleBuffer=true;traits->inheritedWindowData=new osgViewer::GraphicsWindowWin32::WindowData(child);
 auto gc=osg::GraphicsContext::createGraphicsContext(traits);if(!gc)throw std::runtime_error("OpenGL context failed");
 osgViewer::Viewer viewer;viewer.setThreadingModel(osgViewer::Viewer::SingleThreaded);viewer.getCamera()->setGraphicsContext(gc);viewer.getCamera()->setViewport(0,0,w,h);viewer.getCamera()->setProjectionMatrixAsPerspective(35.,double(w)/h,.01,100000.);viewer.getCamera()->setClearColor(osg::Vec4(.055,.08,.12,1));
 auto scene=new osg::Group;auto clip=new osg::ClipNode;clip->addChild(model);scene->addChild(clip);
 auto box=new osg::Geode;auto geom=new osg::Geometry;auto vertices=new osg::Vec3Array(24);geom->setVertexArray(vertices);geom->addPrimitiveSet(new osg::DrawArrays(GL_LINES,0,24));auto colors=new osg::Vec4Array;colors->push_back(osg::Vec4(1,.52,.18,1));geom->setColorArray(colors,osg::Array::BIND_OVERALL);box->addDrawable(geom);box->getOrCreateStateSet()->setMode(GL_LIGHTING,osg::StateAttribute::OFF);box->getOrCreateStateSet()->setAttribute(new osg::LineWidth(2));scene->addChild(box);box->setNodeMask(0);
 auto manip=new osgGA::TrackballManipulator;viewer.setCameraManipulator(manip);viewer.setSceneData(scene);viewer.realize();viewer.home();
 CoarseBounds bounds(fs::u8path(job.at("source").get<std::string>()).parent_path());model->accept(bounds);auto bb=bounds.getBoundingBox();auto sphere=model->getBound();
 if(bb.valid())sphere=osg::BoundingSphere(bb);
 json lohi;if(bb.valid())lohi={bb.xMin(),bb.yMin(),bb.zMin(),bb.xMax(),bb.yMax(),bb.zMax()};else lohi={sphere.center().x()-sphere.radius(),sphere.center().y()-sphere.radius(),sphere.center().z()-sphere.radius(),sphere.center().x()+sphere.radius(),sphere.center().y()+sphere.radius(),sphere.center().z()+sphere.radius()};
 auto home=sphere.center();double distance=std::max(1.f,sphere.radius());manip->setHomePosition(home+osg::Vec3d(distance*1.2,-distance*1.8,distance*1.3),home,osg::Vec3d(0,0,1));viewer.home();
 state({{"ready",true},{"bounds",job.value("bounds",lohi)}});long long last=-1;int frames=0;
 while(!viewer.done()&&IsWindow(parent)){
  GetClientRect(parent,&r);if(r.right!=w||r.bottom!=h){w=std::max(10L,r.right);h=std::max(10L,r.bottom);SetWindowPos(child,nullptr,0,0,w,h,SWP_NOZORDER);gc->resized(0,0,w,h);viewer.getCamera()->setViewport(0,0,w,h);viewer.getCamera()->setProjectionMatrixAsPerspective(35.,double(w)/h,.01,100000.);}
  if(frames++%3==0){try{std::ifstream f("command.json");json command;if(f){f>>command;long long seq=command.value("seq",0LL);if(seq!=last){last=seq;if(command.value("quit",false))break;
    bool enabled=command.value("enabled",false);auto b=command.value("box",std::vector<double>{-1,-1,-1,1,1,1});
    while(clip->getNumClipPlanes())clip->removeClipPlane(clip->getClipPlane(0));
    if(enabled)for(unsigned i=0;i<6;i++){osg::Vec4d p(0,0,0,0);p[i%3]=i<3?1:-1;p[3]=i<3?-b[i]:b[i];clip->addClipPlane(new osg::ClipPlane(i,p));}
    box->setNodeMask(command.value("showBox",false)?~0u:0u);unsigned at=0;for(int axis=0;axis<3;axis++)for(int j=0;j<4;j++){osg::Vec3 a,c;for(int k=0;k<3;k++)a[k]=c[k]=b[k];int a1=(axis+1)%3,a2=(axis+2)%3;a[a1]=c[a1]=b[a1+((j&1)?3:0)];a[a2]=c[a2]=b[a2+((j&2)?3:0)];c[axis]=b[axis+3];(*vertices)[at++]=a;(*vertices)[at++]=c;}vertices->dirty();geom->dirtyBound();geom->dirtyDisplayList();
    scene->getOrCreateStateSet()->setAttributeAndModes(new osg::PolygonMode(osg::PolygonMode::FRONT_AND_BACK,command.value("wire",false)?osg::PolygonMode::LINE:osg::PolygonMode::FILL));
    std::string view=command.value("view",std::string());if(view=="fit")viewer.home();else if(!view.empty()){auto c=sphere.center();double d=std::max(1.f,sphere.radius())*3.5;osg::Vec3d eye=c,up(0,0,1);if(view=="top"){eye.z()+=d;up.set(0,1,0);}else if(view=="front")eye.y()-=d;else eye.x()+=d;manip->setTransformation(eye,c,up);}
   }}}catch(...){}}
  if(frames%30==0){DisplayMaterials materials;model->accept(materials);}
  viewer.frame();std::this_thread::sleep_for(std::chrono::milliseconds(10));
 }
 viewer.setDone(true);return 0;
}catch(std::exception&e){state({{"error",e.what()}});std::cerr<<e.what();return 1;}}
