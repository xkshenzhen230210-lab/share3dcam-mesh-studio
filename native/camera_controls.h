#pragma once
#include <osg/Vec3d>
#include <algorithm>
#include <cmath>

// Desktop coordinates: +x is right and +y is down. Rotation always uses
// world Z as the vertical axis, independent of the previous camera roll.
struct MouseCamera {
 osg::Vec3d eye,center,up;
 double fovy=35.;
};
enum class MouseMotion { Look,Orbit,Pan };
inline void moveMouseCamera(MouseCamera& camera,MouseMotion motion,double dx,double dy,double height,double sensitivity=1.){
 if(!std::isfinite(dx)||!std::isfinite(dy)||!std::isfinite(height)||height<=0||!std::isfinite(sensitivity)||sensitivity<=0)return;
 auto forward=camera.center-camera.eye;double distance=forward.normalize();if(!std::isfinite(distance)||distance<1e-10)return;
 constexpr double pi=3.14159265358979323846;
 if(motion==MouseMotion::Pan){
  auto right=forward^camera.up;if(right.normalize()<1e-10)return;
  auto up=right^forward;up.normalize();
  auto delta=(-right*dx+up*dy)*(2.*distance*std::tan(camera.fovy*pi/360.)/height*sensitivity);
  camera.eye+=delta;camera.center+=delta;return;
 }
 double yaw=std::atan2(forward.x(),forward.y());
 double pitch=std::asin(std::clamp(forward.z(),-1.,1.));
 double angle=120.*pi/180./height*sensitivity;
 yaw+=dx*angle;pitch=std::clamp(pitch-dy*angle,-85.*pi/180.,85.*pi/180.);
 forward.set(std::sin(yaw)*std::cos(pitch),std::cos(yaw)*std::cos(pitch),std::sin(pitch));
 auto right=forward^osg::Vec3d(0,0,1);right.normalize();camera.up=right^forward;
 if(motion==MouseMotion::Look)camera.center=camera.eye+forward*distance;
 else camera.eye=camera.center-forward*distance;
}
inline void zoomMouseCamera(MouseCamera& camera,double steps){
 if(!std::isfinite(steps))return;
 auto forward=camera.center-camera.eye;double distance=forward.normalize();if(!std::isfinite(distance)||distance<1e-10)return;
 distance=std::clamp(distance*std::exp(std::clamp(-.12*steps,-20.,20.)),1e-5,1e12);
 camera.eye=camera.center-forward*distance;
}
