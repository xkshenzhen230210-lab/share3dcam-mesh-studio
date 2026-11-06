#define NOMINMAX
#include <windows.h>
#include <windowsx.h>
#include <imm.h>
#include <osgViewer/Viewer>
#include <osgViewer/api/Win32/GraphicsWindowWin32>
#include <osgGA/TrackballManipulator>
#include <osg/ClipNode>
#include <osg/Geometry>
#include <osg/Geode>
#include <osg/PolygonMode>
#include <osg/Point>
#include <osg/LineWidth>
#include <osg/Texture2D>
#include <osg/Material>
#include <osgUtil/SmoothingVisitor>
#include <osgUtil/IntersectionVisitor>
#include <osgUtil/LineSegmentIntersector>
#include <osg/ComputeBoundsVisitor>
#include <osg/PagedLOD>
#include <osgDB/ReadFile>
#include <osgDB/WriteFile>
#include <fstream>
#include <filesystem>
#include <thread>
#include <iostream>
#include <cmath>
#include <functional>
#include <optional>
#include <array>
#include "json.hpp"
#include "navigation.h"
#include "camera_controls.h"
#include "point_scene.h"
#include <memory>
using json=nlohmann::json;namespace fs=std::filesystem;
static WNDPROC osgWindowProcedure=nullptr;static WPARAM lastNativeKey=0,lastNativeChar=0;static int lastEventKey=0;static unsigned navigationSteps=0;
static std::function<bool(unsigned)> navigationPress;
static std::function<bool(MouseMotion,POINT,bool)> mouseStart;
static std::function<void(MouseMotion,double,double)> mouseDrag;
static std::function<void()> mouseEnd;
static std::function<void()> measureClick;
static std::function<void(POINT,double)> mouseWheel;
static UINT dragButton=0;static POINT dragPoint{};static MouseMotion dragMotion=MouseMotion::Orbit;
static bool measureMode=false,dragMoved=false;
void stopMouseDrag(HWND window){
 if(dragButton&&mouseEnd)mouseEnd();
 dragButton=0;
 if(GetCapture()==window)ReleaseCapture();
}
void updateMouseDrag(LPARAM detail){
 POINT next{GET_X_LPARAM(detail),GET_Y_LPARAM(detail)};
 if(measureMode&&dragMotion==MouseMotion::Orbit&&!dragMoved&&
    std::abs(next.x-dragPoint.x)<=3&&std::abs(next.y-dragPoint.y)<=3)return;
 auto previous=dragPoint;dragPoint=next;
 if(mouseDrag&&(next.x!=previous.x||next.y!=previous.y)){
  dragMoved=true;
  mouseDrag(dragMotion,next.x-previous.x,next.y-previous.y);
 }
}
LRESULT CALLBACK navigationWindowProcedure(HWND window,UINT message,WPARAM key,LPARAM detail){
 if(message==WM_LBUTTONDOWN||message==WM_RBUTTONDOWN||message==WM_MBUTTONDOWN||message==WM_LBUTTONDBLCLK||message==WM_RBUTTONDBLCLK||message==WM_MBUTTONDBLCLK){
  if(dragButton)return 0;
  SetFocus(window);dragPoint={GET_X_LPARAM(detail),GET_Y_LPARAM(detail)};
  bool left=message==WM_LBUTTONDOWN||message==WM_LBUTTONDBLCLK;
  bool right=message==WM_RBUTTONDOWN||message==WM_RBUTTONDBLCLK;
  bool shift=(key&MK_SHIFT)!=0;
  dragMotion=left&&!shift?MouseMotion::Orbit:(right&&shift?MouseMotion::Look:MouseMotion::Pan);
  dragButton=left?MK_LBUTTON:(right?MK_RBUTTON:MK_MBUTTON);
  dragMoved=false;
  SetCapture(window);
  if(!mouseStart||!mouseStart(dragMotion,dragPoint,message==WM_LBUTTONDBLCLK&&!shift))stopMouseDrag(window);
  return 0;
 }
 if(message==WM_MOUSEMOVE&&dragButton){
  if(!(key&dragButton)){stopMouseDrag(window);return 0;}
  updateMouseDrag(detail);return 0;
 }
 if(message==WM_LBUTTONUP||message==WM_RBUTTONUP||message==WM_MBUTTONUP){
  UINT released=message==WM_LBUTTONUP?MK_LBUTTON:(message==WM_RBUTTONUP?MK_RBUTTON:MK_MBUTTON);
  // Windows may coalesce the final move while a large model is picking or paging.
  if(dragButton==released){
   updateMouseDrag(detail);
   if(measureMode&&!dragMoved&&dragMotion==MouseMotion::Orbit&&measureClick)measureClick();
   stopMouseDrag(window);
  }
  return 0;
 }
 if(message==WM_CAPTURECHANGED||message==WM_KILLFOCUS||message==WM_CANCELMODE)stopMouseDrag(window);
 if(message==WM_MOUSEWHEEL){
  POINT cursor{GET_X_LPARAM(detail),GET_Y_LPARAM(detail)};
  if(!dragButton&&mouseWheel&&ScreenToClient(window,&cursor))mouseWheel(cursor,double(GET_WHEEL_DELTA_WPARAM(key))/WHEEL_DELTA);
  return 0;
 }
 if(message==WM_KEYDOWN||message==WM_SYSKEYDOWN){lastNativeKey=key;if(navigationPress&&navigationPress(static_cast<unsigned>(key)))return 0;}
 // Windows accessibility and software keyboards use VK_PACKET + WM_CHAR.
 // OSG's Win32 adapter only translates virtual-key events, so forward this
 // Unicode path explicitly without duplicating physical keyboard events.
 if(message==WM_CHAR)lastNativeChar=key;
 if(message==WM_CHAR&&navigationPress&&(lastNativeKey==0||lastNativeKey==VK_PACKET||lastNativeKey==VK_PROCESSKEY)){
  unsigned value=static_cast<unsigned>(key);if(value>='A'&&value<='Z')value+=32;
  if(value=='w'||value=='a'||value=='s'||value=='d'||value=='q'||value=='e'){
   navigationPress(value);return 0;
  }
 }
 return CallWindowProcW(osgWindowProcedure,window,message,key,detail);
}
struct CameraManipulator:osgGA::TrackballManipulator {
 void applyPose(const osg::Vec3d& eye,const osg::Vec3d& center,const osg::Vec3d& up){_thrown=false;flushMouseEventStack();finishAnimation();setTransformation(eye,center,up);}
};

constexpr double pickNear=.01,pickFar=100000.;

// Read the native viewport before swapping buffers, even if another window overlaps it.
struct ViewSnapshot : osg::Camera::DrawCallback {
 mutable bool requested=false;
 mutable osg::ref_ptr<osg::Image> image;
 void operator()(osg::RenderInfo& info)const override{
  if(!requested)return;
  requested=false;
  auto viewport=info.getCurrentCamera()->getViewport();
  image=new osg::Image;
  image->readPixels(int(viewport->x()),int(viewport->y()),int(viewport->width()),int(viewport->height()),GL_RGB,GL_UNSIGNED_BYTE,1);
 }
};

void fitClipBox(MouseCamera& camera,const osg::BoundingBoxd& box,double aspect,const HorizontalFrame& frame=HorizontalFrame()){
 auto forward=camera.center-camera.eye;
 if(!box.valid()||forward.normalize()<1e-10||aspect<=0)return;
 auto right=forward^camera.up;
 if(right.normalize()<1e-10)return;
 auto up=right^forward;
 const double tanY=std::tan(osg::DegreesToRadians(camera.fovy)*.5);
 auto center=frame.world(box.center());
 double depth=pickNear*3.;
 for(unsigned corner=0;corner<8;corner++){
  auto offset=frame.world(box.corner(corner))-center;
  double span=std::max(std::abs(offset*right)/(tanY*aspect),std::abs(offset*up)/tanY);
  depth=std::max(depth,span*1.12-offset*forward+pickNear);
 }
 camera.eye=center-forward*depth;
 camera.center=center;
 camera.up=up;
}

std::optional<osg::Vec3d> pickSurface(osg::Node& model,const PointScene& points,
                                     const MouseCamera& camera,double x,double y,double height,
                                     const osg::BoundingBoxd& clipBounds,const HorizontalFrame& frame=HorizontalFrame()){
 auto forward=camera.center-camera.eye;
 if(forward.normalize()<1e-10)return {};
 auto right=forward^camera.up;
 if(right.normalize()<1e-10)return {};
 auto up=right^forward;
 double unitsPerPixel=2.*std::tan(osg::DegreesToRadians(camera.fovy)*.5)/height;
 double sx=x*unitsPerPixel,sy=-y*unitsPerPixel;
 if(points.active){
  // The viewer already caps its point cache. Search it without copying or sorting it.
  const double tolerance=(points.gaussian?8.:4.)*unitsPerPixel;
  auto localEye=camera.eye-points.origin;
  double nearest=pickFar;
  std::optional<osg::Vec3d> hit;
  for(size_t i=0;i<points.positions->size();i++){
   if(points.gaussian&&(*points.colors)[i].a()<1.f/255.f)continue;
   osg::Vec3d local=(*points.positions)[i];
   auto offset=local-localEye;
   double depth=offset*forward;
   if(depth<pickNear||depth>=nearest)continue;
   double dx=offset*right-sx*depth,dy=offset*up-sy*depth;
   double radius=depth*tolerance;
   if(dx*dx+dy*dy>radius*radius)continue;
   auto world=local+points.origin;
   if(clipBounds.valid()&&!clipBounds.contains(frame.local(world)))continue;
   nearest=depth;
   hit=world;
  }
  return hit;
 }
 auto ray=forward+right*sx+up*sy;
 auto boxEye=frame.local(camera.eye),boxRay=frame.localVector(ray);
 double start=pickNear,end=pickFar;
 // Clip the ray before intersecting so hidden triangles cannot become the pivot.
 if(clipBounds.valid())for(int axis=0;axis<3;axis++){
  if(std::abs(boxRay[axis])<1e-12){
   if(boxEye[axis]<clipBounds._min[axis]||boxEye[axis]>clipBounds._max[axis])return {};
   continue;
  }
  double a=(clipBounds._min[axis]-boxEye[axis])/boxRay[axis];
  double b=(clipBounds._max[axis]-boxEye[axis])/boxRay[axis];
  start=std::max(start,std::min(a,b));end=std::min(end,std::max(a,b));
  if(start>=end)return {};
 }
 osg::ref_ptr<osgUtil::LineSegmentIntersector> rayPick=new osgUtil::LineSegmentIntersector(camera.eye+ray*start,camera.eye+ray*end);
 rayPick->setIntersectionLimit(osgUtil::Intersector::LIMIT_NEAREST);
 osgUtil::IntersectionVisitor visitor(rayPick);
 model.accept(visitor);
 if(!rayPick->containsIntersections())return {};
 return rayPick->getFirstIntersection().getWorldIntersectPoint();
}
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
   bool point=false;if(g->getUserValue("share_point",point)&&point)continue;
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
void writeState(const json& value,const wchar_t* destination=L"state.json"){
 std::ofstream f("state.tmp");f<<value.dump();f.close();
 MoveFileExW(L"state.tmp",destination,MOVEFILE_REPLACE_EXISTING);
}
void state(const json& value){writeState(value);}
int main(int argc,char**argv){try{
 if(argc==3&&std::string(argv[1])=="--test-alignment"){
  std::ifstream input(fs::u8path(argv[2]));json points;input>>points;std::vector<osg::Vec2d> footprint;osg::BoundingBoxd source;
  for(auto& p:points){osg::Vec3d v(p[0],p[1],p[2]);source.expandBy(v);footprint.push_back({v.x(),v.y()});}
  footprint=footprintHull(std::move(footprint));auto frame=principalFrame(footprint,source);auto b=frameBounds(frame,footprint,source);
  std::cout<<json({{"frame",frame.json()},{"bounds",{b.xMin(),b.yMin(),b.zMin(),b.xMax(),b.yMax(),b.zMax()}}}).dump();return 0;
 }
 if(argc==2&&std::string(argv[1])=="--test-mouse-controls"){
  MouseCamera initial{{0,-5,0},{0,0,0},{0,0,1},35.};json result;
  auto save=[&](const char* name,const MouseCamera& p){auto vec=[](const osg::Vec3d& v){return json::array({v.x(),v.y(),v.z()});};result[name]={{"eye",vec(p.eye)},{"center",vec(p.center)},{"up",vec(p.up)}};};
  auto p=initial;lookMouseCamera(p,100,0,600);save("look",p);
  p=initial;orbitMouseCamera(p,initial.center,100,60,1000,600);save("orbit",p);
  p=initial;lookMouseCamera(p,0,-100000,600);save("pitch",p);
  p=initial;panMouseCamera(p,50,30,600);save("pan",p);
  p=initial;lookMouseCamera(p,50,20,600);lookMouseCamera(p,50,20,600);save("split",p);
  p=initial;lookMouseCamera(p,100,40,600);save("whole",p);
  p=initial;zoomMouseCamera(p,1);save("wheel",p);
  p=initial;lookMouseCamera(p,100,40,600,.5);save("sensitivity_half",p);
  p=initial;lookMouseCamera(p,100,40,600,2.);save("sensitivity_double",p);
  p=initial;lookMouseCamera(p,200,80,1200);save("height_double",p);
  p=initial;lookMouseCamera(p,100,40,1200);save("height_tall",p);
  p=initial;lookMouseCamera(p,0,100000,600);save("pitch_down",p);
  p=initial;zoomMouseCamera(p,1e9);save("wheel_near",p);
  p=initial;zoomMouseCamera(p,-1e9);zoomMouseCamera(p,-1e9);save("wheel_far",p);
  osg::Vec3d hit(1,2,.5);
  p=initial;orbitMouseCamera(p,hit,100,60,1000,600);save("surface_orbit",p);
  p=initial;zoomMouseCamera(p,1,&hit);save("surface_wheel_in",p);
  p=initial;zoomMouseCamera(p,-1,&hit);save("surface_wheel_out",p);
  p=initial;centerMouseCamera(p,hit);save("surface_center",p);
  p=initial;panMouseCamera(p,50,30,600,1.,7.);save("surface_pan",p);
  p={{0,0,5},{0,0,0},{0,1,0},35.};orbitMouseCamera(p,p.center,0,-60,1000,600);save("top_orbit",p);
  osg::ref_ptr<osg::Geode> pickModel=new osg::Geode;
  auto pickGeometry=new osg::Geometry;
  auto pickVertices=new osg::Vec3Array;
  for(float y:{0.f,2.f}){
   pickVertices->push_back(osg::Vec3(-2,y,-2));
   pickVertices->push_back(osg::Vec3(2,y,-2));
   pickVertices->push_back(osg::Vec3(0,y,2));
  }
  pickGeometry->setVertexArray(pickVertices);
  pickGeometry->addPrimitiveSet(new osg::DrawArrays(GL_TRIANGLES,0,6));
  pickModel->addDrawable(pickGeometry);
  PointScene pickPoints;
  osg::BoundingBoxd clipped(-2,1,-2,2,3,2);
  auto savePick=[&](const char* name,const std::optional<osg::Vec3d>& selected){
   result[name]=selected?json::array({selected->x(),selected->y(),selected->z()}):json(nullptr);
  };
  savePick("pick_mesh",pickSurface(*pickModel,pickPoints,initial,0,0,600,{}));
  savePick("pick_clipped_mesh",pickSurface(*pickModel,pickPoints,initial,0,0,600,clipped));
  savePick("pick_empty",pickSurface(*pickModel,pickPoints,initial,450,-250,600,{}));
  pickPoints.active=true;pickPoints.gaussian=true;
  pickPoints.positions->push_back(osg::Vec3(0,0,0));pickPoints.colors->push_back(osg::Vec4(1,1,1,0));
  pickPoints.positions->push_back(osg::Vec3(0,2,0));pickPoints.colors->push_back(osg::Vec4(1,1,1,1));
  savePick("pick_gaussian",pickSurface(*pickModel,pickPoints,initial,0,0,600,{}));
  osg::ref_ptr<CameraManipulator> legacy=new CameraManipulator;p=initial;p.up.set(std::sqrt(.5),0,std::sqrt(.5));
  legacy->applyPose(p.eye,p.center,p.up);legacy->getTransformation(p.eye,p.center,p.up);save("legacy_rolled",p);
  std::cout<<result.dump();return 0;
 }
 if(argc==2&&std::string(argv[1])=="--test-navigation"){
  auto value=[](osg::Vec3d p){return json::array({p.x(),p.y(),p.z()});};osg::Vec3d forward(0,1,0),up(0,0,1);
  std::cout<<json({{"forward",value(navigationDelta(forward,up,0,1,0,20,.1))},{"right",value(navigationDelta(forward,up,1,0,0,20,.1))},
   {"up",value(navigationDelta(forward,up,0,0,1,20,.1))},{"down",value(navigationDelta(forward,up,0,0,-1,20,.1))},
   {"diagonal",value(navigationDelta(forward,up,1,1,1,20,.1))}}).dump();return 0;
 }
 if(argc!=2)throw std::runtime_error("Expected job.json");std::ifstream jf(fs::u8path(argv[1]));json job;jf>>job;
 osg::ref_ptr<osgDB::Options> readOptions=new osgDB::Options("noRotation");
 PointScene points;osg::ref_ptr<osg::Node> model;
 std::unique_ptr<PointScene> analysis;
 std::string analysisSource,analysisError;
 bool analysisVisible=false;
 if(points.load(fs::u8path(job.at("source").get<std::string>()))){model=points.node;job["bounds"]=points.bounds;}
 else model=osgDB::readRefNodeFile(job.at("source").get<std::string>(),readOptions);if(!model)throw std::runtime_error("Cannot load model");
 HWND parent=(HWND)job.at("parent").get<uint64_t>();if(!IsWindow(parent))throw std::runtime_error("Viewer parent closed");
 WNDCLASSW wc{};wc.style=CS_OWNDC|CS_DBLCLKS;wc.lpfnWndProc=DefWindowProcW;wc.hInstance=GetModuleHandle(nullptr);wc.lpszClassName=L"ShareMeshView";RegisterClassW(&wc);
 RECT r;GetClientRect(parent,&r);int w=std::max(10L,r.right),h=std::max(10L,r.bottom);
 HWND child=CreateWindowW(wc.lpszClassName,L"SHARE3DCAM 3D",WS_CHILD|WS_VISIBLE|WS_CLIPSIBLINGS|WS_CLIPCHILDREN,0,0,w,h,parent,nullptr,wc.hInstance,nullptr);
 auto traits=new osg::GraphicsContext::Traits;traits->x=0;traits->y=0;traits->width=w;traits->height=h;traits->windowDecoration=false;traits->doubleBuffer=true;traits->inheritedWindowData=new osgViewer::GraphicsWindowWin32::WindowData(child);
 auto gc=osg::GraphicsContext::createGraphicsContext(traits);if(!gc)throw std::runtime_error("OpenGL context failed");
 osgViewer::Viewer viewer;viewer.setThreadingModel(osgViewer::Viewer::SingleThreaded);viewer.getCamera()->setGraphicsContext(gc);viewer.getCamera()->setViewport(0,0,w,h);viewer.getCamera()->setProjectionMatrixAsPerspective(35.,double(w)/h,.01,100000.);viewer.getCamera()->setClearColor(osg::Vec4(.055,.08,.12,1));
 auto scene=new osg::Group;auto clip=new osg::ClipNode;clip->addChild(model);scene->addChild(clip);
 auto box=new osg::Geode;auto geom=new osg::Geometry;auto vertices=new osg::Vec3dArray(24);geom->setVertexArray(vertices);geom->addPrimitiveSet(new osg::DrawArrays(GL_LINES,0,24));auto colors=new osg::Vec4Array;colors->push_back(osg::Vec4(1,.52,.18,1));geom->setColorArray(colors,osg::Array::BIND_OVERALL);box->addDrawable(geom);box->getOrCreateStateSet()->setMode(GL_LIGHTING,osg::StateAttribute::OFF);box->getOrCreateStateSet()->setAttribute(new osg::LineWidth(2));scene->addChild(box);box->setNodeMask(0);
 auto marker=new osg::MatrixTransform;
 auto markerNode=new osg::Geode;
 auto markerGeometry=new osg::Geometry;
 markerGeometry->setVertexArray(new osg::Vec3Array(1));
 markerGeometry->setColorArray(colors,osg::Array::BIND_OVERALL);
 markerGeometry->addPrimitiveSet(new osg::DrawArrays(GL_POINTS,0,1));
 markerNode->addDrawable(markerGeometry);
 auto markerStyle=markerNode->getOrCreateStateSet();
 markerStyle->setMode(GL_LIGHTING,osg::StateAttribute::OFF);
 markerStyle->setMode(GL_DEPTH_TEST,osg::StateAttribute::OFF);
 markerStyle->setAttribute(new osg::Point(8.f));
 markerStyle->setRenderBinDetails(20,"RenderBin");
 marker->addChild(markerNode);marker->setNodeMask(0);scene->addChild(marker);
 auto ruler=new osg::MatrixTransform;
 auto rulerNode=new osg::Geode;
 auto rulerGeometry=new osg::Geometry;
 auto rulerVertices=new osg::Vec3Array(2);
 auto rulerColors=new osg::Vec4Array;
 rulerColors->push_back(osg::Vec4(.2,.85,1.,1.));
 auto rulerDots=new osg::DrawArrays(GL_POINTS,0,0);
 auto rulerLine=new osg::DrawArrays(GL_LINES,0,0);
 rulerGeometry->setVertexArray(rulerVertices);
 rulerGeometry->setColorArray(rulerColors,osg::Array::BIND_OVERALL);
 rulerGeometry->setUseDisplayList(false);
 rulerGeometry->addPrimitiveSet(rulerDots);
 rulerGeometry->addPrimitiveSet(rulerLine);
 rulerNode->addDrawable(rulerGeometry);
 auto rulerStyle=rulerNode->getOrCreateStateSet();
 rulerStyle->setMode(GL_LIGHTING,osg::StateAttribute::OFF);
 rulerStyle->setMode(GL_DEPTH_TEST,osg::StateAttribute::OFF);
 rulerStyle->setAttribute(new osg::Point(9.f));
 rulerStyle->setAttribute(new osg::LineWidth(2.f));
 rulerStyle->setRenderBinDetails(21,"RenderBin");
 ruler->addChild(rulerNode);ruler->setNodeMask(0);scene->addChild(ruler);
 osg::ref_ptr<ViewSnapshot> snapshot=new ViewSnapshot;
 viewer.getCamera()->setFinalDrawCallback(snapshot);
 auto manip=new CameraManipulator;
 // Native input below owns all mouse gestures; never continue spinning on release.
 manip->setAllowThrow(false);
 viewer.setCameraManipulator(manip);viewer.setSceneData(scene);viewer.realize();
 ImmAssociateContext(child,nullptr);
 osgWindowProcedure=reinterpret_cast<WNDPROC>(SetWindowLongPtrW(child,GWLP_WNDPROC,reinterpret_cast<LONG_PTR>(navigationWindowProcedure)));
 if(points.active){gc->makeCurrent();points.checkProgram(*gc->getState());gc->releaseContext();}viewer.home();
 CoarseBounds bounds(fs::u8path(job.at("source").get<std::string>()).parent_path());model->accept(bounds);auto bb=bounds.getBoundingBox();auto sphere=model->getBound();
 if(points.active&&points.fitBounds.valid()){
  bb.init();bb.expandBy(osg::Vec3(points.fitBounds._min));bb.expandBy(osg::Vec3(points.fitBounds._max));
 }
 if(bb.valid())sphere=osg::BoundingSphere(bb);
 HorizontalFrame frame;osg::BoundingBoxd sourceBounds=bb;
 if(points.active)sourceBounds.set(points.bounds[0],points.bounds[1],points.bounds[2],points.bounds[3],points.bounds[4],points.bounds[5]);
 if(!sourceBounds.valid()){auto c=sphere.center();double r=std::max(1.f,sphere.radius());sourceBounds.set(c.x()-r,c.y()-r,c.z()-r,c.x()+r,c.y()+r,c.z()+r);}
 osg::BoundingBoxd selectedBounds=sourceBounds;
 if(job.value("auto_align",false)){
  std::vector<osg::Vec2d> footprint;bool sampledFootprint=false;
  if(points.active){
   footprint=points.footprint;
   if(footprint.empty()){
    for(auto& p:*points.positions)footprint.push_back({double(p.x())+points.origin.x(),double(p.y())+points.origin.y()});
    footprint=footprintHull(std::move(footprint));
    sampledFootprint=true;
   }
  }else{
   FootprintVisitor sample(fs::u8path(job.at("source").get<std::string>()).parent_path());model->accept(sample);footprint=std::move(sample.hull);
   if(sample.bounds.valid())sourceBounds=sample.bounds;
  }
  frame=principalFrame(footprintHull(footprint),sourceBounds);
  // Estimate direction from sampled geometry, then conservatively enclose the
  // original extent of older caches. AABB corners must not bias the direction.
  if(sampledFootprint)for(unsigned i=0;i<8;i++){auto p=sourceBounds.corner(i);footprint.push_back({p.x(),p.y()});}
  selectedBounds=frameBounds(frame,footprint,sourceBounds);
 }
 json lohi={selectedBounds.xMin(),selectedBounds.yMin(),selectedBounds.zMin(),selectedBounds.xMax(),selectedBounds.yMax(),selectedBounds.zMax()};
 auto home=sphere.center();double distance=std::max(1.f,sphere.radius());manip->setHomePosition(home+frame.direction(osg::Vec3d(distance*1.2,-distance*1.8,distance*1.3)),home,osg::Vec3d(0,0,1));viewer.home();
 long long last=-1;int frames=0;double fovy=35.,fixedAspect=0.,navigationSpeed=1.5,mouseSensitivity=1.;unsigned mouseSteps=0;
 osg::BoundingBoxd clipBounds;
 std::optional<osg::Vec3d> lastPickedPoint;
 std::optional<osg::Vec3d> measureHit;
 std::array<osg::Vec3d,2> measurePoints;
 unsigned measureCount=0;
 bool measureMiss=false;
 long long measureReset=0;
 std::string snapshotId;
 auto refreshRuler=[&](){
  ruler->setNodeMask(measureMode&&measureCount?~0u:0u);
  if(!measureCount)return;
  ruler->setMatrix(osg::Matrixd::translate(measurePoints[0]));
  (*rulerVertices)[0].set(0,0,0);
  (*rulerVertices)[1]=measureCount==2?osg::Vec3(measurePoints[1]-measurePoints[0]):osg::Vec3();
  rulerDots->setCount(measureCount);
  rulerLine->setCount(measureCount==2?2:0);
  rulerGeometry->dirtyBound();
 };
 osg::Vec3d dragPivot;
 double panDepth=0.;
 auto pose=[&](){MouseCamera p;manip->getTransformation(p.eye,p.center,p.up);p.fovy=fovy;return p;};
 auto insideViewport=[&](POINT cursor){
  auto vp=viewer.getCamera()->getViewport();
  double y=h-1-cursor.y;
  return cursor.x>=vp->x()&&cursor.x<vp->x()+vp->width()&&y>=vp->y()&&y<vp->y()+vp->height();
 };
 auto pick=[&](const MouseCamera& p,POINT cursor){
  auto vp=viewer.getCamera()->getViewport();
  double x=cursor.x+.5-vp->x()-vp->width()*.5;
  double y=cursor.y+.5-(h-vp->y()-vp->height()*.5);
  return analysisVisible?pickSurface(*analysis->node,*analysis,p,x,y,vp->height(),clipBounds,frame):
   pickSurface(*model,points,p,x,y,vp->height(),clipBounds,frame);
 };
 mouseStart=[&](MouseMotion motion,POINT cursor,bool centerOnPoint){
  if(!insideViewport(cursor))return false;
  if(motion==MouseMotion::Look)return true;
  auto p=pose();
  auto hit=pick(p,cursor);
  measureHit=motion==MouseMotion::Orbit?hit:std::nullopt;
  if(hit)lastPickedPoint=hit;
  auto forward=p.center-p.eye;
  forward.normalize();
  auto pivot=p.center;
  if(lastPickedPoint&&(!clipBounds.valid()||clipBounds.contains(frame.local(*lastPickedPoint)))&&
     (*lastPickedPoint-p.eye)*forward>pickNear)pivot=*lastPickedPoint;
  dragPivot=pivot;
  panDepth=(pivot-p.eye)*forward;
  if(centerOnPoint&&hit&&!measureMode){
   centerMouseCamera(p,*hit);
   manip->applyPose(p.eye,p.center,p.up);mouseSteps++;
  }
  if(motion==MouseMotion::Orbit&&hit){
   marker->setMatrix(osg::Matrixd::translate(*hit));
   marker->setNodeMask(~0u);
  }
  return true;
 };
 mouseDrag=[&](MouseMotion motion,double dx,double dy){
  auto p=pose();
  auto vp=viewer.getCamera()->getViewport();
  if(motion==MouseMotion::Orbit)orbitMouseCamera(p,dragPivot,dx,dy,vp->width(),vp->height(),mouseSensitivity);
  else if(motion==MouseMotion::Pan)panMouseCamera(p,dx,dy,vp->height(),mouseSensitivity,panDepth);
  else lookMouseCamera(p,dx,dy,vp->height(),mouseSensitivity);
  manip->applyPose(p.eye,p.center,p.up);mouseSteps++;
 };
 mouseEnd=[&](){marker->setNodeMask(0);};
 measureClick=[&](){
  measureMiss=!measureHit;
  if(!measureHit)return;
  if(measureCount&&(*measureHit-measurePoints[measureCount-1]).length2()<=1e-20)return;
  if(measureCount==2)measureCount=0;
  measurePoints[measureCount++]=*measureHit;
  refreshRuler();
 };
 mouseWheel=[&](POINT cursor,double steps){
  if(!insideViewport(cursor))return;
  auto p=pose();
  auto hit=pick(p,cursor);
  zoomMouseCamera(p,steps,hit?&*hit:nullptr);
  manip->applyPose(p.eye,p.center,p.up);mouseSteps++;
 };
 navigationPress=[&](unsigned key){
  if(key==VK_ESCAPE&&measureMode){
   measureCount=0;measureMiss=false;refreshRuler();
   return true;
  }
  if(key>='A'&&key<='Z')key+=32;
  double right=(key=='d')-(key=='a'),forward=(key=='w')-(key=='s'),vertical=(key=='q')-(key=='e');
  if(!right&&!forward&&!vertical)return false;
  osg::Vec3d eye,center,up;manip->getTransformation(eye,center,up);
  double multiplier=(GetKeyState(VK_SHIFT)&0x8000)?3.:1.;if(GetKeyState(VK_CONTROL)&0x8000)multiplier*=.2;
  auto delta=navigationDelta(center-eye,up,right,forward,vertical,navigationSpeed*multiplier,1./60.);
  manip->applyPose(eye+delta,center+delta,up);lastEventKey=key;navigationSteps++;return true;
 };
 auto projection=[&](){int vw=w,vh=h;if(fixedAspect>0){if(double(w)/h>fixedAspect)vw=std::max(1,int(h*fixedAspect));else vh=std::max(1,int(w/fixedAspect));}viewer.getCamera()->setViewport((w-vw)/2,(h-vh)/2,vw,vh);viewer.getCamera()->setProjectionMatrixAsPerspective(fovy,fixedAspect>0?fixedAspect:double(w)/h,.01,100000.);};
 auto publish=[&](){
  auto p=pose();
  auto vec=[](const osg::Vec3d& v){return json::array({v.x(),v.y(),v.z()});};
  json measurement={{"count",measureCount},{"miss",measureMiss}};
  if(measureCount==2){
   auto delta=measurePoints[1]-measurePoints[0];
   measurement["distance"]=delta.length();
   measurement["delta"]=vec(delta);
  }
  state({{"ready",true},{"bounds",lohi},{"clip_frame",frame.json()},{"applied_seq",last},{"analysis_visible",analysisVisible},{"analysis_source",analysisSource},{"analysis_error",analysisError},{"navigation_focused",GetFocus()==child},{"navigation_foreground",GetForegroundWindow()==GetAncestor(parent,GA_ROOT)},{"navigation_input",{lastNativeKey,lastNativeChar,lastEventKey,navigationSteps}},{"mouse_steps",mouseSteps},{"mouse_sensitivity",mouseSensitivity},{"measurement",measurement},{"camera",{{"eye",vec(p.eye)},{"center",vec(p.center)},{"up",vec(p.up)},{"fovy",fovy}}}});
 };
 auto lastState=std::chrono::steady_clock::now(),lastMove=lastState;publish();
 while(!viewer.done()&&IsWindow(parent)){
  GetClientRect(parent,&r);if(r.right!=w||r.bottom!=h){w=std::max(10L,r.right);h=std::max(10L,r.bottom);SetWindowPos(child,nullptr,0,0,w,h,SWP_NOZORDER);gc->resized(0,0,w,h);projection();}
  if(frames++%3==0){try{std::ifstream f("command.json");json command;if(f){f>>command;long long seq=command.value("seq",0LL);if(seq!=last){last=seq;if(command.value("quit",false))break;
    if(command.contains("aspect")){double next=command.at("aspect");if(std::isfinite(next)&&next>=0&&next<=10){fixedAspect=next;projection();}}
    bool enabled=command.value("enabled",false);auto b=command.value("box",std::vector<double>{-1,-1,-1,1,1,1});
    if(b.size()!=6||!std::all_of(b.begin(),b.end(),[](double v){return std::isfinite(v);})||
       b[0]>=b[3]||b[1]>=b[4]||b[2]>=b[5])throw std::runtime_error("Invalid clip bounds");
    auto previousClip=clipBounds;
    clipBounds.init();if(enabled)clipBounds.set(b[0],b[1],b[2],b[3],b[4],b[5]);
    bool nextMeasure=command.value("measure",false);
    auto reset=command.value("measure_reset",0LL);
    if(nextMeasure!=measureMode||reset!=measureReset||clipBounds!=previousClip){
     measureMode=nextMeasure;measureReset=reset;measureCount=0;measureMiss=false;measureHit.reset();
     refreshRuler();
    }
    while(clip->getNumClipPlanes())clip->removeClipPlane(clip->getClipPlane(0));
    if(enabled&&!points.active)for(unsigned i=0;i<6;i++)clip->addClipPlane(new osg::ClipPlane(i,frame.plane(i,b)));
    points.setClip(enabled,b,frame);
    auto nextAnalysis=command.value("analysis_source",std::string());
    if(nextAnalysis.empty())analysisError.clear();
    if(nextAnalysis!=analysisSource){
     try{
      std::unique_ptr<PointScene> next;
      if(!nextAnalysis.empty()){
       next=std::make_unique<PointScene>();
       if(!next->load(fs::u8path(nextAnalysis))||next->gaussian)throw std::runtime_error("Invalid analysis preview");
       gc->makeCurrent();next->checkProgram(*gc->getState());gc->releaseContext();
      }
      if(analysis)scene->removeChild(analysis->node);
      analysis=std::move(next);analysisSource=nextAnalysis;analysisError.clear();
      if(analysis)scene->addChild(analysis->node);
     }catch(const std::exception& error){analysisError=error.what();gc->releaseContext();}
    }
    bool nextVisible=analysis&&analysisSource==nextAnalysis&&command.value("analysis_visible",false);
    if(nextVisible!=analysisVisible){lastPickedPoint.reset();measureCount=0;measureHit.reset();refreshRuler();}
    analysisVisible=nextVisible;
    model->setNodeMask(analysisVisible?0u:~0u);
    if(analysis){analysis->node->setNodeMask(analysisVisible?~0u:0u);analysis->setClip(enabled,b,frame);}
    float pointSize=command.value("point_size",2.f);
    points.setPointSize(pointSize);if(analysis)analysis->setPointSize(pointSize);
    double speed=command.value("navigation_speed",navigationSpeed);if(std::isfinite(speed)&&speed>0&&speed<=100000)navigationSpeed=speed;
    double sensitivity=command.value("mouse_sensitivity",mouseSensitivity);if(std::isfinite(sensitivity)&&sensitivity>=.1&&sensitivity<=3.)mouseSensitivity=sensitivity;
    if(command.contains("move")){
     auto step=command.at("move").get<std::vector<double>>();if(step.size()==3&&std::all_of(step.begin(),step.end(),[](double v){return std::isfinite(v)&&std::abs(v)<=3.;})){
      double factor=std::max({std::abs(step[0]),std::abs(step[1]),std::abs(step[2])});if(factor<=0)factor=1;
      osg::Vec3d eye,center,up;manip->getTransformation(eye,center,up);auto delta=navigationDelta(center-eye,up,step[0]/factor,step[1]/factor,step[2]/factor,navigationSpeed*factor,1./30.);
      manip->applyPose(eye+delta,center+delta,up);
     }
    }
    box->setNodeMask(command.value("showBox",false)?~0u:0u);unsigned at=0;for(int axis=0;axis<3;axis++)for(int j=0;j<4;j++){osg::Vec3d a,c;for(int k=0;k<3;k++)a[k]=c[k]=b[k];int a1=(axis+1)%3,a2=(axis+2)%3;a[a1]=c[a1]=b[a1+((j&1)?3:0)];a[a2]=c[a2]=b[a2+((j&2)?3:0)];c[axis]=b[axis+3];(*vertices)[at++]=frame.world(a);(*vertices)[at++]=frame.world(c);}vertices->dirty();geom->dirtyBound();geom->dirtyDisplayList();
    scene->getOrCreateStateSet()->setAttributeAndModes(new osg::PolygonMode(osg::PolygonMode::FRONT_AND_BACK,command.value("wire",false)?osg::PolygonMode::LINE:osg::PolygonMode::FILL));
    std::string view=command.value("view",std::string());
    if(!view.empty())lastPickedPoint.reset();
    if(view=="fit"&&analysisVisible){
     auto p=pose();auto viewport=viewer.getCamera()->getViewport();
     fitClipBox(p,analysis->fitBounds,viewport->width()/viewport->height());
     manip->applyPose(p.eye,p.center,p.up);
    }else if(view=="fit")viewer.home();
    else if(view=="clip"&&clipBounds.valid()){
     auto p=pose();
     auto viewport=viewer.getCamera()->getViewport();
     fitClipBox(p,clipBounds,viewport->width()/viewport->height(),frame);
     manip->applyPose(p.eye,p.center,p.up);
    }else if(view=="top"||view=="front"||view=="right"){
     auto c=sphere.center();double d=std::max(1.f,sphere.radius())*3.5;osg::Vec3d eye=c,up(0,0,1);
     if(view=="top"){eye.z()+=d;up.set(0,1,0);}else if(view=="front")eye.y()-=d;else eye.x()+=d;
     manip->applyPose(c+frame.direction(eye-c),c,frame.direction(up));
    }
    if(command.contains("camera")){
     auto& camera=command.at("camera");auto vec=[&](const char* key){auto a=camera.at(key).get<std::vector<double>>();if(a.size()!=3||!std::all_of(a.begin(),a.end(),[](double v){return std::isfinite(v);}))throw std::runtime_error("Invalid camera vector");return osg::Vec3d(a[0],a[1],a[2]);};
     auto eye=vec("eye"),center=vec("center"),up=vec("up");double nextFov=camera.value("fovy",35.);
     if((center-eye).length2()>1e-20&&((center-eye)^up).length2()>1e-20&&std::isfinite(nextFov)&&nextFov>1&&nextFov<179){lastPickedPoint.reset();manip->applyPose(eye,center,up);fovy=nextFov;projection();}
    }
   }}}catch(...){}}
  if(frames%30==0){DisplayMaterials materials;model->accept(materials);}
  if(frames%3==0){
   try{
    std::ifstream input("snapshot_request.json");json request;
    if(input>>request){
     auto id=request.at("id").get<std::string>();
     if(!id.empty()&&id!=snapshotId&&last>=request.value("after_seq",-1LL)){
      snapshotId=id;snapshot->requested=true;
     }
    }
   }catch(const std::exception&){}
  }
  auto now=std::chrono::steady_clock::now();double dt=std::chrono::duration<double>(now-lastMove).count();lastMove=now;
  // Focus stays with text fields until the user clicks inside the viewport.
  if(GetFocus()==child&&GetForegroundWindow()==GetAncestor(parent,GA_ROOT)){
   auto held=[](int key){return (GetAsyncKeyState(key)&0x8000)?1.:0.;};
   osg::Vec3d eye,center,up;manip->getTransformation(eye,center,up);
   double speed=navigationSpeed*(held(VK_SHIFT)?3.:1.)*(held(VK_CONTROL)?.2:1.);
   auto delta=navigationDelta(center-eye,up,held('D')-held('A'),held('W')-held('S'),held('Q')-held('E'),speed,dt);
   if(delta.length2()>0)manip->applyPose(eye+delta,center+delta,up);
  }
  viewer.advance();viewer.eventTraversal();viewer.updateTraversal();points.update(viewer.getCamera());
  if(analysisVisible)analysis->update(viewer.getCamera());
  viewer.renderingTraversals();
  if(snapshot->image){
   bool saved=osgDB::writeImageFile(*snapshot->image,"snapshot.png");
   snapshot->image=nullptr;
   writeState({{"id",snapshotId},{"error",!saved}},L"snapshot_result.json");
  }
  if(now-lastState>=std::chrono::milliseconds(100)){publish();lastState=now;}
  std::this_thread::sleep_for(std::chrono::milliseconds(10));
 }
 stopMouseDrag(child);mouseStart={};mouseDrag={};mouseEnd={};measureClick={};mouseWheel={};navigationPress={};
 viewer.setDone(true);return 0;
}catch(std::exception&e){state({{"error",e.what()}});std::cerr<<e.what();return 1;}}
