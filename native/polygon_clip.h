#pragma once
#include "horizontal_frame.h"
#include <osg/ClipNode>
#include <array>

using CropPolygon=std::vector<osg::Vec2d>;
inline double polygonCross(osg::Vec2d a,osg::Vec2d b,osg::Vec2d c){auto u=b-a,v=c-a;return u.x()*v.y()-u.y()*v.x();}
inline bool polygonContains(osg::Vec2d p,const CropPolygon& polygon){
 if(polygon.empty())return true;bool inside=false;
 for(size_t i=0,j=polygon.size()-1;i<polygon.size();j=i++){
  auto a=polygon[j],b=polygon[i],d=b-a;double length=d.length(),side=polygonCross(a,b,p);
  if(std::abs(side)<=1e-7*length&&p.x()>=std::min(a.x(),b.x())-1e-7&&p.x()<=std::max(a.x(),b.x())+1e-7&&p.y()>=std::min(a.y(),b.y())-1e-7&&p.y()<=std::max(a.y(),b.y())+1e-7)return true;
  if((a.y()>p.y())!=(b.y()>p.y())&&p.x()<(b.x()-a.x())*(p.y()-a.y())/(b.y()-a.y())+a.x())inside=!inside;
 }return inside;
}
inline std::vector<std::array<osg::Vec2d,3>> polygonTriangles(CropPolygon polygon){
 if(polygon.size()<3||polygon.size()>128)throw std::runtime_error("Use 3-128 polygon vertices");
 double scale=0;for(auto p:polygon){if(!std::isfinite(p.x())||!std::isfinite(p.y()))throw std::runtime_error("Invalid polygon vertex");scale=std::max(scale,(p-polygon[0]).length());}
 double eps=std::max(1e-24,scale*scale*1e-12),tol=std::sqrt(eps)*1e-6;
 auto on=[&](auto a,auto b,auto p){return std::abs(polygonCross(a,b,p))<=eps&&p.x()>=std::min(a.x(),b.x())-tol&&p.x()<=std::max(a.x(),b.x())+tol&&p.y()>=std::min(a.y(),b.y())-tol&&p.y()<=std::max(a.y(),b.y())+tol;};
 for(size_t i=0;i<polygon.size();i++){
  auto a=polygon[i],b=polygon[(i+1)%polygon.size()];if((a-b).length2()<=eps*1e-8)throw std::runtime_error("Duplicate polygon vertex");
  for(size_t j=i+1;j<polygon.size();j++){
   if(j==i+1||(i==0&&j==polygon.size()-1))continue;auto c=polygon[j],d=polygon[(j+1)%polygon.size()];
   if((polygonCross(a,b,c)*polygonCross(a,b,d)<0&&polygonCross(c,d,a)*polygonCross(c,d,b)<0)||on(a,b,c)||on(a,b,d)||on(c,d,a)||on(c,d,b))throw std::runtime_error("CropPolygon edges intersect");
  }
 }
 bool changed=true;while(changed&&polygon.size()>3){changed=false;for(size_t i=0;i<polygon.size();i++)if(on(polygon[(i+polygon.size()-1)%polygon.size()],polygon[(i+1)%polygon.size()],polygon[i])){polygon.erase(polygon.begin()+i);changed=true;break;}}
 double area=0;for(size_t i=1;i+1<polygon.size();i++)area+=polygonCross(polygon[0],polygon[i],polygon[i+1]);
 if(std::abs(area)<=eps)throw std::runtime_error("CropPolygon has no area");if(area<0)std::reverse(polygon.begin(),polygon.end());
 std::vector<std::array<osg::Vec2d,3>> result;
 while(polygon.size()>3){bool found=false;
  for(size_t i=0;i<polygon.size();i++){
   size_t a=(i+polygon.size()-1)%polygon.size(),c=(i+1)%polygon.size();if(polygonCross(polygon[a],polygon[i],polygon[c])<=eps)continue;
   bool blocked=false;for(size_t k=0;k<polygon.size();k++)if(k!=a&&k!=i&&k!=c&&polygonCross(polygon[a],polygon[i],polygon[k])>=-eps&&polygonCross(polygon[i],polygon[c],polygon[k])>=-eps&&polygonCross(polygon[c],polygon[a],polygon[k])>=-eps){blocked=true;break;}
   if(blocked)continue;result.push_back({polygon[a],polygon[i],polygon[c]});polygon.erase(polygon.begin()+i);found=true;break;
  }if(!found)throw std::runtime_error("Cannot triangulate polygon");
 }result.push_back({polygon[0],polygon[1],polygon[2]});return result;
}
inline CropPolygon readPolygon(const nlohmann::json& value){
 CropPolygon result;if(!value.is_object()||!value.contains("polygon")||value["polygon"].is_null())return result;
 for(auto& p:value.at("polygon")){auto a=p.get<std::vector<double>>();if(a.size()!=2)throw std::runtime_error("Invalid polygon vertex");result.push_back({a[0],a[1]});}
 polygonTriangles(result);return result;
}
inline nlohmann::json polygonJson(const CropPolygon& p){auto result=nlohmann::json::array();for(auto v:p)result.push_back({v.x(),v.y()});return result;}
// Existing six-plane clipping remains responsible for the height and bounds.
inline void setMeshClip(osg::ClipNode& root,bool enabled,const std::vector<double>& b,const HorizontalFrame& frame){
 while(root.getNumClipPlanes())root.removeClipPlane(root.getClipPlane(0));
 if(enabled)for(unsigned i=0;i<6;i++)root.addClipPlane(new osg::ClipPlane(i,frame.plane(i,b)));
}

struct MeshPolygonClip {
 osg::StateSet* state;osg::ref_ptr<osg::Program> program=new osg::Program;
 osg::ref_ptr<osg::Uniform> count=new osg::Uniform("outlineCount",0),vertices=new osg::Uniform(osg::Uniform::FLOAT_VEC2,"outlineVertices",128),matrix=new osg::Uniform("eyeToSelection",osg::Matrixf());
 HorizontalFrame frame;bool active=false;
 explicit MeshPolygonClip(osg::Node& root):state(root.getOrCreateStateSet()){
  program->addShader(new osg::Shader(osg::Shader::VERTEX,R"GLSL(
#version 150 compatibility
uniform mat4 eyeToSelection;out vec3 selectionPoint;out vec4 baseColor;out vec2 baseUV;out float shade;
void main(){
 vec4 eye=gl_ModelViewMatrix*gl_Vertex;selectionPoint=(eyeToSelection*eye).xyz;
 gl_Position=gl_ProjectionMatrix*eye;gl_ClipVertex=eye;baseColor=gl_Color;baseUV=(gl_TextureMatrix[0]*gl_MultiTexCoord0).xy;
 shade=0.3+0.7*abs(dot(normalize(gl_NormalMatrix*gl_Normal),normalize(-eye.xyz)));
}
)GLSL"));
  program->addShader(new osg::Shader(osg::Shader::FRAGMENT,R"GLSL(
#version 150 compatibility
uniform int outlineCount;uniform vec2 outlineVertices[128];uniform bool polygonTextured;uniform sampler2D baseTexture;
in vec3 selectionPoint;in vec4 baseColor;in vec2 baseUV;in float shade;
void main(){
 bool inside=false,boundary=false;vec2 p=selectionPoint.xy;
 for(int i=0;i<outlineCount;i++){
  vec2 a=outlineVertices[i],b=outlineVertices[(i+1)%outlineCount],d=b-a;
  float side=d.x*(p.y-a.y)-d.y*(p.x-a.x);
  boundary=boundary||(abs(side)<=0.000001*length(d)&&all(greaterThanEqual(p,min(a,b)-vec2(0.000001)))&&all(lessThanEqual(p,max(a,b)+vec2(0.000001))));
  if((a.y>p.y)!=(b.y>p.y)&&p.x<(b.x-a.x)*(p.y-a.y)/(b.y-a.y)+a.x)inside=!inside;
 }
 if(!inside&&!boundary)discard;
 gl_FragColor=baseColor*(polygonTextured?texture2D(baseTexture,baseUV):vec4(vec3(shade),1.0));
}
)GLSL"));
  state->addUniform(count);state->addUniform(vertices);state->addUniform(matrix);state->addUniform(new osg::Uniform("baseTexture",0));
 }
 void set(const CropPolygon& polygon,const HorizontalFrame& f,bool enabled){
  frame=f;active=enabled&&!polygon.empty();count->set(int(polygon.size()));
  for(unsigned i=0;i<polygon.size();i++)vertices->setElement(i,osg::Vec2(polygon[i].x(),polygon[i].y()));
  if(active)state->setAttributeAndModes(program,osg::StateAttribute::ON|osg::StateAttribute::OVERRIDE);
  else state->removeAttribute(osg::StateAttribute::PROGRAM);
 }
 void update(osg::Camera* camera){
  if(!active)return;auto transform=camera->getInverseViewMatrix()*osg::Matrixd::translate(-frame.origin)*osg::Matrixd::rotate(-frame.yaw*3.14159265358979323846/180.,osg::Vec3d(0,0,1));matrix->set(osg::Matrixf(transform));
 }
};
