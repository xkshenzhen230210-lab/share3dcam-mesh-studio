#pragma once
#include <osg/Vec3d>
#include <osg/Vec2d>
#include <osg/BoundingBox>
#include <osg/Geometry>
#include <osg/Geode>
#include <osg/PagedLOD>
#include <osg/Transform>
#include <osg/ComputeBoundsVisitor>
#include <osgDB/ReadFile>
#include <filesystem>
#include <vector>
#include <algorithm>
#include <cmath>
#include <limits>
#include "json.hpp"

struct HorizontalFrame {
 osg::Vec3d origin;double yaw=0;
 osg::Vec3d localVector(const osg::Vec3d& p)const{
  double a=yaw*3.14159265358979323846/180.,c=std::cos(a),s=std::sin(a);
  return {c*p.x()+s*p.y(),-s*p.x()+c*p.y(),p.z()};
 }
 osg::Vec3d direction(const osg::Vec3d& p)const{
  double a=yaw*3.14159265358979323846/180.,c=std::cos(a),s=std::sin(a);
  return {c*p.x()-s*p.y(),s*p.x()+c*p.y(),p.z()};
 }
 osg::Vec3d local(const osg::Vec3d& p)const{return localVector(p-origin);}
 osg::Vec3d world(const osg::Vec3d& p)const{return direction(p)+origin;}
 nlohmann::json json()const{return {{"origin",{origin.x(),origin.y(),origin.z()}},{"yaw_degrees",yaw}};}
 static HorizontalFrame read(const nlohmann::json& value){
  HorizontalFrame frame;if(!value.is_object())return frame;
  auto p=value.value("origin",std::vector<double>{0,0,0});frame.yaw=value.value("yaw_degrees",0.);
  if(p.size()!=3||!std::isfinite(frame.yaw)||!std::all_of(p.begin(),p.end(),[](double x){return std::isfinite(x);}))throw std::runtime_error("Invalid horizontal frame");
  frame.origin.set(p[0],p[1],p[2]);return frame;
 }
 osg::Vec4d plane(unsigned i,const std::vector<double>& b)const{
  osg::Vec3d n;n[i%3]=i<3?1:-1;n=direction(n);
  return {n.x(),n.y(),n.z(),(i<3?-b[i]:b[i])-n*origin};
 }
};

inline std::vector<double> clipValues(const nlohmann::json& value){
 auto b=(value.is_object()?value.at("bounds"):value).get<std::vector<double>>();
 if(b.size()!=6||!std::all_of(b.begin(),b.end(),[](double x){return std::isfinite(x);})||b[0]>=b[3]||b[1]>=b[4]||b[2]>=b[5])throw std::runtime_error("Invalid clipping box");
 return b;
}

inline std::vector<osg::Vec2d> footprintHull(std::vector<osg::Vec2d> p){
 std::sort(p.begin(),p.end(),[](auto a,auto b){return a.x()<b.x()||(a.x()==b.x()&&a.y()<b.y());});
 p.erase(std::unique(p.begin(),p.end()),p.end());if(p.size()<3)return p;
 auto cross=[](auto a,auto b,auto c){auto u=b-a,v=c-a;return u.x()*v.y()-u.y()*v.x();};
 std::vector<osg::Vec2d> hull;
 for(auto v:p){while(hull.size()>1&&cross(hull[hull.size()-2],hull.back(),v)<=0)hull.pop_back();hull.push_back(v);}
 auto lower=hull.size();
 for(auto it=p.rbegin()+1;it!=p.rend();++it){while(hull.size()>lower&&cross(hull[hull.size()-2],hull.back(),*it)<=0)hull.pop_back();hull.push_back(*it);}
 hull.pop_back();return hull;
}

struct FootprintVisitor:osg::NodeVisitor {
 std::filesystem::path folder;unsigned depth=0;std::vector<osg::Vec2d> hull;
 osg::BoundingBoxd bounds;
 explicit FootprintVisitor(std::filesystem::path path):NodeVisitor(TRAVERSE_ALL_CHILDREN),folder(path){}
 void apply(osg::Geode& node)override{
  auto matrix=osg::computeLocalToWorld(getNodePath());std::vector<osg::Vec2d> batch;
  for(unsigned i=0;i<node.getNumDrawables();i++)if(auto g=node.getDrawable(i)->asGeometry()){
   auto add=[&](auto* vertices){if(!vertices)return;for(auto& v:*vertices){
    osg::Vec3d p=osg::Vec3d(v)*matrix;
    if(!std::isfinite(p.x())||!std::isfinite(p.y())||!std::isfinite(p.z()))continue;
    bounds.expandBy(p);batch.push_back({p.x(),p.y()});
    if(batch.size()>=100000){batch=footprintHull(std::move(batch));}
   }};
   add(dynamic_cast<osg::Vec3Array*>(g->getVertexArray()));add(dynamic_cast<osg::Vec3dArray*>(g->getVertexArray()));
  }
  batch.insert(batch.end(),hull.begin(),hull.end());hull=footprintHull(std::move(batch));traverse(node);
 }
 void apply(osg::PagedLOD& node)override{
  auto count=hull.size();auto before=bounds;traverse(node);
  if(bounds!=before||count!=hull.size()||node.getNumChildren()>0){
   // Loaded children may be empty placeholders; use their geometric bounds.
   osg::ComputeBoundsVisitor check;for(unsigned i=0;i<node.getNumChildren();i++)node.getChild(i)->accept(check);
   if(check.getBoundingBox().valid())return;
  }
  if(depth>=32)return;
  for(unsigned i=0;i<node.getNumFileNames();i++)if(!node.getFileName(i).empty()){
   auto path=std::filesystem::u8path(node.getFileName(i));
   if(!path.is_absolute()){
    auto database=std::filesystem::u8path(node.getDatabasePath());
    auto base=database.is_absolute()?database:folder/database;
    auto candidate=base/path;path=std::filesystem::is_regular_file(candidate)?candidate:folder/path;
   }
   auto child=osgDB::readRefNodeFile(path.u8string());
   if(child){auto previous=folder;folder=path.parent_path();depth++;child->accept(*this);depth--;folder=previous;break;}
  }
 }
};

inline HorizontalFrame principalFrame(const std::vector<osg::Vec2d>& footprint,const osg::BoundingBoxd& bounds){
 HorizontalFrame frame;if(footprint.size()<2||!bounds.valid())return frame;
 frame.origin=bounds.center();double best=std::numeric_limits<double>::infinity(),selected=0;
 for(size_t i=0;i<footprint.size();i++){
  auto edge=footprint[(i+1)%footprint.size()]-footprint[i];if(edge.length2()<1e-20)continue;
  double a=std::atan2(edge.y(),edge.x()),c=std::cos(a),s=std::sin(a);
  double xmin=1e300,ymin=1e300,xmax=-1e300,ymax=-1e300;
  for(auto p:footprint){p-=osg::Vec2d(frame.origin.x(),frame.origin.y());double x=c*p.x()+s*p.y(),y=-s*p.x()+c*p.y();xmin=std::min(xmin,x);xmax=std::max(xmax,x);ymin=std::min(ymin,y);ymax=std::max(ymax,y);}
  double dx=xmax-xmin,dy=ymax-ymin,area=dx*dy;
  if(dy>dx)a+=3.14159265358979323846/2.;
  double degrees=std::remainder(a*180./3.14159265358979323846,180.);
  if(degrees>=90.)degrees-=180.;
  double tolerance=std::isfinite(best)?std::max(1e-12,best*1e-10):0;
  if(area<best-tolerance||(std::abs(area-best)<=tolerance&&std::abs(degrees)<std::abs(selected))){best=area;selected=degrees;}
 }
 frame.yaw=selected;return frame;
}

inline osg::BoundingBoxd frameBounds(const HorizontalFrame& frame,const std::vector<osg::Vec2d>& footprint,const osg::BoundingBoxd& source){
 osg::BoundingBoxd result;
 for(auto p:footprint){result.expandBy(frame.local({p.x(),p.y(),source.zMin()}));result.expandBy(frame.local({p.x(),p.y(),source.zMax()}));}
 if(!result.valid())for(unsigned i=0;i<8;i++)result.expandBy(frame.local(source.corner(i)));
 // Include floating-point boundary roundoff, including flat or linear inputs.
 for(int i=0;i<3;i++){double pad=std::max(1e-7,std::max(std::abs(result._min[i]),std::abs(result._max[i]))*1e-12);result._min[i]-=pad;result._max[i]+=pad;}
 return result;
}
