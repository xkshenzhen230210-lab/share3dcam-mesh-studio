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
#include <fstream>
#include <filesystem>
#include <thread>
#include <iostream>
#include <cmath>
#include <functional>
#include <optional>
#include "json.hpp"
#include "navigation.h"
#include "camera_controls.h"
#include "point_scene.h"
using json=nlohmann::json;namespace fs=std::filesystem;
static WNDPROC osgWindowProcedure=nullptr;static WPARAM lastNativeKey=0,lastNativeChar=0;static int lastEventKey=0;static unsigned navigationSteps=0;
static std::function<bool(unsigned)> navigationPress;
static std::function<bool(MouseMotion,POINT,bool)> mouseStart;
static std::function<void(MouseMotion,double,double)> mouseDrag;
static std::function<void()> mouseEnd;
static std::function<void(POINT,double)> mouseWheel;
static UINT dragButton=0;static POINT dragPoint{};static MouseMotion dragMotion=MouseMotion::Orbit;
void stopMouseDrag(HWND window){
 if(dragButton&&mouseEnd)mouseEnd();
 dragButton=0;
 if(GetCapture()==window)ReleaseCapture();
}
void updateMouseDrag(LPARAM detail){
 POINT next{GET_X_LPARAM(detail),GET_Y_LPARAM(detail)};
 auto previous=dragPoint;dragPoint=next;
 if(mouseDrag&&(next.x!=previous.x||next.y!=previous.y))mouseDrag(dragMotion,next.x-previous.x,next.y-previous.y);
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
  if(dragButton==released){updateMouseDrag(detail);stopMouseDrag(window);}return 0;
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

std::optional<osg::Vec3d> pickSurface(osg::Node& model,const PointScene& points,
                                     const MouseCamera& camera,double x,double y,double height,
                                     const osg::BoundingBoxd& clipBounds){
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
   if(clipBounds.valid()&&!clipBounds.contains(world))continue;
   nearest=depth;
   hit=world;
  }
  return hit;
 }
 auto ray=forward+right*sx+up*sy;
 double start=pickNear,end=pickFar;
 // Clip the ray before intersecting so hidden triangles cannot become the pivot.
 if(clipBounds.valid())for(int axis=0;axis<3;axis++){
  if(std::abs(ray[axis])<1e-12){
   if(camera.eye[axis]<clipBounds._min[axis]||camera.eye[axis]>clipBounds._max[axis])return {};
   continue;
  }
  double a=(clipBounds._min[axis]-camera.eye[axis])/ray[axis];
  double b=(clipBounds._max[axis]-camera.eye[axis])/ray[axis];
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
void state(json value){std::ofstream f("state.tmp");f<<value.dump();f.close();MoveFileExW(L"state.tmp",L"state.json",MOVEFILE_REPLACE_EXISTING);}
int main(int argc,char**argv){try{
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
 auto box=new osg::Geode;auto geom=new osg::Geometry;auto vertices=new osg::Vec3Array(24);geom->setVertexArray(vertices);geom->addPrimitiveSet(new osg::DrawArrays(GL_LINES,0,24));auto colors=new osg::Vec4Array;colors->push_back(osg::Vec4(1,.52,.18,1));geom->setColorArray(colors,osg::Array::BIND_OVERALL);box->addDrawable(geom);box->getOrCreateStateSet()->setMode(GL_LIGHTING,osg::StateAttribute::OFF);box->getOrCreateStateSet()->setAttribute(new osg::LineWidth(2));scene->addChild(box);box->setNodeMask(0);
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
 json lohi;if(bb.valid())lohi={bb.xMin(),bb.yMin(),bb.zMin(),bb.xMax(),bb.yMax(),bb.zMax()};else lohi={sphere.center().x()-sphere.radius(),sphere.center().y()-sphere.radius(),sphere.center().z()-sphere.radius(),sphere.center().x()+sphere.radius(),sphere.center().y()+sphere.radius(),sphere.center().z()+sphere.radius()};
 auto home=sphere.center();double distance=std::max(1.f,sphere.radius());manip->setHomePosition(home+osg::Vec3d(distance*1.2,-distance*1.8,distance*1.3),home,osg::Vec3d(0,0,1));viewer.home();
 long long last=-1;int frames=0;double fovy=35.,fixedAspect=0.,navigationSpeed=1.5,mouseSensitivity=1.;unsigned mouseSteps=0;
 osg::BoundingBoxd clipBounds;
 std::optional<osg::Vec3d> lastPickedPoint;
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
  return pickSurface(*model,points,p,x,y,vp->height(),clipBounds);
 };
 mouseStart=[&](MouseMotion motion,POINT cursor,bool centerOnPoint){
  if(!insideViewport(cursor))return false;
  if(motion==MouseMotion::Look)return true;
  auto p=pose();
  auto hit=pick(p,cursor);
  if(hit)lastPickedPoint=hit;
  auto forward=p.center-p.eye;
  forward.normalize();
  auto pivot=p.center;
  if(lastPickedPoint&&(!clipBounds.valid()||clipBounds.contains(*lastPickedPoint))&&
     (*lastPickedPoint-p.eye)*forward>pickNear)pivot=*lastPickedPoint;
  dragPivot=pivot;
  panDepth=(pivot-p.eye)*forward;
  if(centerOnPoint&&hit){
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
 mouseWheel=[&](POINT cursor,double steps){
  if(!insideViewport(cursor))return;
  auto p=pose();
  auto hit=pick(p,cursor);
  zoomMouseCamera(p,steps,hit?&*hit:nullptr);
  manip->applyPose(p.eye,p.center,p.up);mouseSteps++;
 };
 navigationPress=[&](unsigned key){
  if(key>='A'&&key<='Z')key+=32;
  double right=(key=='d')-(key=='a'),forward=(key=='w')-(key=='s'),vertical=(key=='q')-(key=='e');
  if(!right&&!forward&&!vertical)return false;
  osg::Vec3d eye,center,up;manip->getTransformation(eye,center,up);
  double multiplier=(GetKeyState(VK_SHIFT)&0x8000)?3.:1.;if(GetKeyState(VK_CONTROL)&0x8000)multiplier*=.2;
  auto delta=navigationDelta(center-eye,up,right,forward,vertical,navigationSpeed*multiplier,1./60.);
  manip->applyPose(eye+delta,center+delta,up);lastEventKey=key;navigationSteps++;return true;
 };
 auto projection=[&](){int vw=w,vh=h;if(fixedAspect>0){if(double(w)/h>fixedAspect)vw=std::max(1,int(h*fixedAspect));else vh=std::max(1,int(w/fixedAspect));}viewer.getCamera()->setViewport((w-vw)/2,(h-vh)/2,vw,vh);viewer.getCamera()->setProjectionMatrixAsPerspective(fovy,fixedAspect>0?fixedAspect:double(w)/h,.01,100000.);};
 auto publish=[&](){osg::Vec3d eye,center,up;manip->getTransformation(eye,center,up);state({{"ready",true},{"bounds",job.value("bounds",lohi)},{"applied_seq",last},{"navigation_focused",GetFocus()==child},{"navigation_foreground",GetForegroundWindow()==GetAncestor(parent,GA_ROOT)},{"navigation_input",{lastNativeKey,lastNativeChar,lastEventKey,navigationSteps}},{"mouse_steps",mouseSteps},{"mouse_sensitivity",mouseSensitivity},{"camera",{{"eye",{eye.x(),eye.y(),eye.z()}},{"center",{center.x(),center.y(),center.z()}},{"up",{up.x(),up.y(),up.z()}},{"fovy",fovy}}}});};
 auto lastState=std::chrono::steady_clock::now(),lastMove=lastState;publish();
 while(!viewer.done()&&IsWindow(parent)){
  GetClientRect(parent,&r);if(r.right!=w||r.bottom!=h){w=std::max(10L,r.right);h=std::max(10L,r.bottom);SetWindowPos(child,nullptr,0,0,w,h,SWP_NOZORDER);gc->resized(0,0,w,h);projection();}
  if(frames++%3==0){try{std::ifstream f("command.json");json command;if(f){f>>command;long long seq=command.value("seq",0LL);if(seq!=last){last=seq;if(command.value("quit",false))break;
    if(command.contains("aspect")){double next=command.at("aspect");if(std::isfinite(next)&&next>=0&&next<=10){fixedAspect=next;projection();}}
    bool enabled=command.value("enabled",false);auto b=command.value("box",std::vector<double>{-1,-1,-1,1,1,1});
    clipBounds.init();if(enabled&&b.size()==6)clipBounds.set(b[0],b[1],b[2],b[3],b[4],b[5]);
    while(clip->getNumClipPlanes())clip->removeClipPlane(clip->getClipPlane(0));
    if(enabled&&!points.active)for(unsigned i=0;i<6;i++){osg::Vec4d p(0,0,0,0);p[i%3]=i<3?1:-1;p[3]=i<3?-b[i]:b[i];clip->addClipPlane(new osg::ClipPlane(i,p));}
    points.setClip(enabled,b);
    double speed=command.value("navigation_speed",navigationSpeed);if(std::isfinite(speed)&&speed>0&&speed<=100000)navigationSpeed=speed;
    double sensitivity=command.value("mouse_sensitivity",mouseSensitivity);if(std::isfinite(sensitivity)&&sensitivity>=.1&&sensitivity<=3.)mouseSensitivity=sensitivity;
    if(command.contains("move")){
     auto step=command.at("move").get<std::vector<double>>();if(step.size()==3&&std::all_of(step.begin(),step.end(),[](double v){return std::isfinite(v)&&std::abs(v)<=3.;})){
      double factor=std::max({std::abs(step[0]),std::abs(step[1]),std::abs(step[2])});if(factor<=0)factor=1;
      osg::Vec3d eye,center,up;manip->getTransformation(eye,center,up);auto delta=navigationDelta(center-eye,up,step[0]/factor,step[1]/factor,step[2]/factor,navigationSpeed*factor,1./30.);
      manip->applyPose(eye+delta,center+delta,up);
     }
    }
    box->setNodeMask(command.value("showBox",false)?~0u:0u);unsigned at=0;for(int axis=0;axis<3;axis++)for(int j=0;j<4;j++){osg::Vec3 a,c;for(int k=0;k<3;k++)a[k]=c[k]=b[k];int a1=(axis+1)%3,a2=(axis+2)%3;a[a1]=c[a1]=b[a1+((j&1)?3:0)];a[a2]=c[a2]=b[a2+((j&2)?3:0)];c[axis]=b[axis+3];(*vertices)[at++]=a;(*vertices)[at++]=c;}vertices->dirty();geom->dirtyBound();geom->dirtyDisplayList();
    scene->getOrCreateStateSet()->setAttributeAndModes(new osg::PolygonMode(osg::PolygonMode::FRONT_AND_BACK,command.value("wire",false)?osg::PolygonMode::LINE:osg::PolygonMode::FILL));
    std::string view=command.value("view",std::string());if(!view.empty())lastPickedPoint.reset();if(view=="fit")viewer.home();else if(!view.empty()){auto c=sphere.center();double d=std::max(1.f,sphere.radius())*3.5;osg::Vec3d eye=c,up(0,0,1);if(view=="top"){eye.z()+=d;up.set(0,1,0);}else if(view=="front")eye.y()-=d;else eye.x()+=d;manip->setTransformation(eye,c,up);}
    if(command.contains("camera")){
     auto& camera=command.at("camera");auto vec=[&](const char* key){auto a=camera.at(key).get<std::vector<double>>();if(a.size()!=3||!std::all_of(a.begin(),a.end(),[](double v){return std::isfinite(v);}))throw std::runtime_error("Invalid camera vector");return osg::Vec3d(a[0],a[1],a[2]);};
     auto eye=vec("eye"),center=vec("center"),up=vec("up");double nextFov=camera.value("fovy",35.);
     if((center-eye).length2()>1e-20&&((center-eye)^up).length2()>1e-20&&std::isfinite(nextFov)&&nextFov>1&&nextFov<179){lastPickedPoint.reset();manip->applyPose(eye,center,up);fovy=nextFov;projection();}
    }
   }}}catch(...){}}
  if(frames%30==0){DisplayMaterials materials;model->accept(materials);}
  auto now=std::chrono::steady_clock::now();double dt=std::chrono::duration<double>(now-lastMove).count();lastMove=now;
  // Focus stays with text fields until the user clicks inside the viewport.
  if(GetFocus()==child&&GetForegroundWindow()==GetAncestor(parent,GA_ROOT)){
   auto held=[](int key){return (GetAsyncKeyState(key)&0x8000)?1.:0.;};
   osg::Vec3d eye,center,up;manip->getTransformation(eye,center,up);
   double speed=navigationSpeed*(held(VK_SHIFT)?3.:1.)*(held(VK_CONTROL)?.2:1.);
   auto delta=navigationDelta(center-eye,up,held('D')-held('A'),held('W')-held('S'),held('Q')-held('E'),speed,dt);
   if(delta.length2()>0)manip->applyPose(eye+delta,center+delta,up);
  }
  viewer.advance();viewer.eventTraversal();viewer.updateTraversal();points.update(viewer.getCamera());viewer.renderingTraversals();if(now-lastState>=std::chrono::milliseconds(100)){publish();lastState=now;}std::this_thread::sleep_for(std::chrono::milliseconds(10));
 }
 stopMouseDrag(child);mouseStart={};mouseDrag={};mouseEnd={};mouseWheel={};navigationPress={};
 viewer.setDone(true);return 0;
}catch(std::exception&e){state({{"error",e.what()}});std::cerr<<e.what();return 1;}}
