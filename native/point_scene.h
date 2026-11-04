#pragma once
#include <osg/Geometry>
#include <osg/Geode>
#include <osg/MatrixTransform>
#include <osg/Program>
#include <osg/Shader>
#include <osg/BlendFunc>
#include <osg/Depth>
#include <osg/Camera>
#include <filesystem>
#include <fstream>
#include <numeric>
#include <algorithm>
#include <cmath>
#include <limits>
#include "json.hpp"

// Independent OpenGL EWA splat implementation. Original PLY parameters stay in
// the source; only this render cache contains activated scales and covariances.
struct PointScene {
 bool active=false,gaussian=false;int degree=0;
 osg::Vec3d origin;osg::ref_ptr<osg::Node> node;
 osg::BoundingBoxd fitBounds;
 std::vector<double> bounds;
 osg::ref_ptr<osg::Vec3Array> positions=new osg::Vec3Array;
 osg::ref_ptr<osg::Vec4Array> colors=new osg::Vec4Array;
 osg::ref_ptr<osg::Geometry> geometry;
 osg::ref_ptr<osg::Program> program;
 osg::ref_ptr<osg::DrawElementsUInt> order;
 osg::ref_ptr<osg::Uniform> viewport,clipEnabled,clipMin,clipMax;
 std::vector<float> sh;std::vector<osg::Vec4> baseColors;
 osg::Matrixd previous;bool updated=false;

 bool load(const std::filesystem::path& path){
  if(path.extension()!=L".spoints")return false;
  std::ifstream input(path);nlohmann::json doc;input>>doc;
  if(doc.at("format")!="share3dcam-points"||doc.at("version")!=1)throw std::runtime_error("Invalid point cache");
  gaussian=doc.at("kind")=="gaussian";auto stride=doc.at("stride_floats").get<unsigned>();
  auto count=doc.at("count").get<size_t>();degree=doc.value("sh_degree",0);
  if(!count||count>200000000||stride!=(gaussian?62u:7u)||degree<0||degree>3)throw std::runtime_error("Invalid point count/layout");
  auto p=doc.at("origin").get<std::vector<double>>();if(p.size()!=3)throw std::runtime_error("Invalid point origin");
  origin.set(p[0],p[1],p[2]);for(double v:p)if(!std::isfinite(v))throw std::runtime_error("Invalid point origin");
  auto box=doc.at("bounds").get<std::vector<std::vector<double>>>();
  if(box.size()!=2||box[0].size()!=3||box[1].size()!=3)throw std::runtime_error("Invalid point bounds");
  bounds=box[0];bounds.insert(bounds.end(),box[1].begin(),box[1].end());
  for(double v:bounds)if(!std::isfinite(v))throw std::runtime_error("Invalid point bounds");
  auto binary=path.parent_path()/std::filesystem::u8path(doc.at("data").get<std::string>());
  if(std::filesystem::file_size(binary)!=count*stride*sizeof(float))throw std::runtime_error("Truncated point cache");
  std::ifstream stream(binary,std::ios::binary);positions->reserve(count);colors->reserve(count);
  osg::ref_ptr<osg::Vec3Array> covA=new osg::Vec3Array,covB=new osg::Vec3Array;
  if(gaussian){covA->reserve(count);covB->reserve(count);if(degree)sh.reserve(count*48);}
  std::vector<float> record(stride);
  for(size_t i=0;i<count;i++){
   stream.read(reinterpret_cast<char*>(record.data()),stride*4);
   if(!stream||!std::all_of(record.begin(),record.end(),[](float v){return std::isfinite(v);}))throw std::runtime_error("Invalid point cache values");
   positions->push_back(osg::Vec3(record[0],record[1],record[2]));colors->push_back(osg::Vec4(record[3],record[4],record[5],record[6]));
   // Gaussians below the renderer's alpha cutoff cannot contribute any pixel;
   // their stray centers must not drag the initial camera away from the model.
   if(!gaussian||record[6]>=1.f/255.f)fitBounds.expandBy(osg::Vec3d(record[0],record[1],record[2])+origin);
   if(gaussian){
    double w=record[10],x=record[11],y=record[12],z=record[13],length=std::sqrt(w*w+x*x+y*y+z*z);
    if(length<1e-10||record[7]<=0||record[8]<=0||record[9]<=0)throw std::runtime_error("Invalid Gaussian scale/rotation");
    w/=length;x/=length;y/=length;z/=length;
    double r[3][3]={{1-2*(y*y+z*z),2*(x*y-w*z),2*(x*z+w*y)},
                    {2*(x*y+w*z),1-2*(x*x+z*z),2*(y*z-w*x)},
                    {2*(x*z-w*y),2*(y*z+w*x),1-2*(x*x+y*y)}};
    double c[3][3]={};for(int a=0;a<3;a++)for(int b=0;b<3;b++)for(int k=0;k<3;k++)c[a][b]+=r[a][k]*r[b][k]*record[7+k]*record[7+k];
    for(auto& row:c)for(double v:row)if(!std::isfinite(v)||std::abs(v)>std::numeric_limits<float>::max())throw std::runtime_error("Gaussian covariance exceeds GPU numeric range");
    covA->push_back(osg::Vec3(c[0][0],c[0][1],c[0][2]));covB->push_back(osg::Vec3(c[1][1],c[1][2],c[2][2]));
    if(degree)sh.insert(sh.end(),record.begin()+14,record.end());
   }
  }
  geometry=new osg::Geometry;geometry->setVertexArray(positions);geometry->setColorArray(colors,osg::Array::BIND_PER_VERTEX);
  geometry->setUseDisplayList(false);geometry->setUseVertexBufferObjects(true);geometry->setUserValue("share_point",true);geometry->setCullingActive(false);
  if(gaussian){
   geometry->setVertexAttribArray(6,covA,osg::Array::BIND_PER_VERTEX);geometry->setVertexAttribArray(7,covB,osg::Array::BIND_PER_VERTEX);
   order=new osg::DrawElementsUInt(GL_POINTS);order->resize(count);std::iota(order->begin(),order->end(),0);geometry->addPrimitiveSet(order);
   if(degree)baseColors.assign(colors->begin(),colors->end());
  }else geometry->addPrimitiveSet(new osg::DrawArrays(GL_POINTS,0,count));
  auto state=geometry->getOrCreateStateSet();program=new osg::Program;
  program->addBindAttribLocation("covA",6);program->addBindAttribLocation("covB",7);
  program->addShader(new osg::Shader(osg::Shader::VERTEX,R"GLSL(
#version 150 compatibility
in vec3 covA;in vec3 covB;
uniform vec2 viewportSize;uniform bool gaussian;uniform bool clipEnabled;
uniform vec3 clipMin;uniform vec3 clipMax;
out vec3 covariance;out vec4 pointColor;out float skipPoint;
void main(){
 vec3 local=gl_Vertex.xyz;vec4 eye=gl_ModelViewMatrix*gl_Vertex;
 skipPoint=(eye.z>=-0.01 || (clipEnabled && (any(lessThan(local,clipMin)) || any(greaterThan(local,clipMax)))))?1.0:0.0;
 gl_Position=gl_ProjectionMatrix*eye;pointColor=gl_Color;
 covariance=vec3(1.0,0.0,1.0);
 if(gaussian && skipPoint<0.5){
  mat3 worldCov=mat3(covA.x,covA.y,covA.z,covA.y,covB.x,covB.y,covA.z,covB.y,covB.z);
  mat3 view=mat3(gl_ModelViewMatrix);mat3 c=view*worldCov*transpose(view);
  float z=-eye.z;vec2 focal=0.5*viewportSize*vec2(gl_ProjectionMatrix[0][0],gl_ProjectionMatrix[1][1]);
  vec2 limited=clamp(eye.xy/z,-1.3/vec2(gl_ProjectionMatrix[0][0],gl_ProjectionMatrix[1][1]),1.3/vec2(gl_ProjectionMatrix[0][0],gl_ProjectionMatrix[1][1]))*z;
  vec3 jx=vec3(focal.x/z,0.0,focal.x*limited.x/(z*z));
  vec3 jy=vec3(0.0,focal.y/z,focal.y*limited.y/(z*z));
  covariance=vec3(dot(jx,c*jx)+0.3,dot(jx,c*jy),dot(jy,c*jy)+0.3);
 }
}
)GLSL"));
  program->addShader(new osg::Shader(osg::Shader::GEOMETRY,R"GLSL(
#version 150 compatibility
layout(points) in;layout(triangle_strip,max_vertices=4) out;
in vec3 covariance[];in vec4 pointColor[];in float skipPoint[];
uniform vec2 viewportSize;out vec2 coordinate;out vec4 splatColor;
void main(){
 if(skipPoint[0]>0.5)return;
 vec3 c=covariance[0];float mid=0.5*(c.x+c.z);float spread=length(vec2(0.5*(c.x-c.z),c.y));
 float l1=max(0.1,mid+spread),l2=max(0.1,mid-spread);
 vec2 axis=abs(c.y)>0.000001?normalize(vec2(c.y,l1-c.x)):(c.x>=c.z?vec2(1,0):vec2(0,1));
 vec2 a=axis*sqrt(l1),b=vec2(-axis.y,axis.x)*sqrt(l2);
 for(int i=0;i<4;i++){
  coordinate=vec2((i%2==0)?-3.0:3.0,(i<2)?-3.0:3.0);
  vec2 offset=a*coordinate.x+b*coordinate.y;vec4 center=gl_in[0].gl_Position;
  gl_Position=center+vec4(offset*2.0/viewportSize*center.w,0.0,0.0);splatColor=pointColor[0];EmitVertex();
 }EndPrimitive();
}
)GLSL"));
  program->addShader(new osg::Shader(osg::Shader::FRAGMENT,R"GLSL(
#version 150 compatibility
in vec2 coordinate;in vec4 splatColor;uniform bool gaussian;
void main(){
 float d=dot(coordinate,coordinate);if(d>(gaussian?9.0:1.0))discard;
 float alpha=gaussian?min(0.99,splatColor.a*exp(-0.5*d)):1.0;if(alpha<1.0/255.0)discard;
 gl_FragColor=vec4(splatColor.rgb*alpha,alpha);
}
)GLSL"));
  state->setAttributeAndModes(program,osg::StateAttribute::ON|osg::StateAttribute::OVERRIDE);
  viewport=new osg::Uniform("viewportSize",osg::Vec2(1920,1080));state->addUniform(viewport);
  clipEnabled=new osg::Uniform("clipEnabled",false);clipMin=new osg::Uniform("clipMin",osg::Vec3());clipMax=new osg::Uniform("clipMax",osg::Vec3());
  state->addUniform(clipEnabled);state->addUniform(clipMin);state->addUniform(clipMax);state->addUniform(new osg::Uniform("gaussian",gaussian));
  state->setMode(GL_LIGHTING,osg::StateAttribute::OFF|osg::StateAttribute::OVERRIDE);
  if(gaussian){state->setAttributeAndModes(new osg::BlendFunc(GL_ONE,GL_ONE_MINUS_SRC_ALPHA));state->setAttributeAndModes(new osg::Depth(osg::Depth::LESS,0,1,false));state->setMode(GL_BLEND,osg::StateAttribute::ON);}
  auto geode=new osg::Geode;geode->addDrawable(geometry);auto transform=new osg::MatrixTransform;
  transform->setMatrix(osg::Matrixd::translate(origin));transform->addChild(geode);node=transform;active=true;return true;
 }

 void checkProgram(osg::State& state){
  if(!active)return;program->compileGLObjects(state);
  if(!program->getPCP(state)->isLinked())throw std::runtime_error("Point renderer requires OpenGL 3.2 / GLSL 1.50; shader program could not link");
 }

 void setClip(bool enabled,const std::vector<double>& bounds){
  if(!active)return;if(bounds.size()!=6)throw std::runtime_error("Invalid point clipping bounds");
  clipEnabled->set(enabled);clipMin->set(osg::Vec3(bounds[0]-origin.x(),bounds[1]-origin.y(),bounds[2]-origin.z()));
  clipMax->set(osg::Vec3(bounds[3]-origin.x(),bounds[4]-origin.y(),bounds[5]-origin.z()));
 }
 void update(osg::Camera* camera){
  if(!active)return;auto vp=camera->getViewport();viewport->set(osg::Vec2(vp->width(),vp->height()));
  const auto& view=camera->getViewMatrix();if(!gaussian||(updated&&view==previous))return;previous=view;updated=true;
  osg::Vec3d eye,center,up;camera->getViewMatrixAsLookAt(eye,center,up);eye-=origin;auto direction=center-(eye+origin);direction.normalize();
  std::vector<float> depths(positions->size());for(size_t i=0;i<depths.size();i++)depths[i]=(*positions)[i]*direction;
  std::sort(order->begin(),order->end(),[&](unsigned a,unsigned b){return depths[a]==depths[b]?a<b:depths[a]>depths[b];});order->dirty();
  if(!degree)return;
  for(size_t i=0;i<positions->size();i++){
   osg::Vec3d d=osg::Vec3d((*positions)[i])-eye;if(d.length2()<1e-20)d.set(0,0,1);d.normalize();double x=d.x(),y=d.y(),z=d.z();
   double basis[16]={.28209479177387814,-.4886025119029199*y,.4886025119029199*z,-.4886025119029199*x,
    1.0925484305920792*x*y,-1.0925484305920792*y*z,.31539156525252005*(2*z*z-x*x-y*y),-1.0925484305920792*x*z,.5462742152960396*(x*x-y*y),
    -.5900435899266435*y*(3*x*x-y*y),2.890611442640554*x*y*z,-.4570457994644658*y*(4*z*z-x*x-y*y),.3731763325901154*z*(2*z*z-3*x*x-3*y*y),
    -.4570457994644658*x*(4*z*z-x*x-y*y),1.445305721320277*z*(x*x-y*y),-.5900435899266435*x*(x*x-3*y*y)};
   for(int channel=0;channel<3;channel++){double color=.5;for(int k=0;k<(degree+1)*(degree+1);k++)color+=basis[k]*sh[i*48+k*3+channel];(*colors)[i][channel]=std::max(0.0,color);}
  }colors->dirty();
 }
};
