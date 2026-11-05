#pragma once
#include <osg/Quat>
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
inline void panMouseCamera(MouseCamera& camera,double dx,double dy,double height,double sensitivity=1.,double depth=0.){
 if(height<=0)return;
 auto forward=camera.center-camera.eye;
 double distance=forward.normalize();
 if(distance<1e-10)return;
 auto right=forward^camera.up;
 if(right.normalize()<1e-10)return;
 auto up=right^forward;
 if(depth<=0)depth=distance;
 auto delta=(-right*dx+up*dy)*(2.*depth*std::tan(osg::DegreesToRadians(camera.fovy)*.5)/height*sensitivity);
 camera.eye+=delta;
 camera.center+=delta;
}

inline void lookMouseCamera(MouseCamera& camera,double dx,double dy,double height,double sensitivity=1.){
 if(height<=0)return;
 auto forward=camera.center-camera.eye;
 double distance=forward.normalize();
 if(distance<1e-10)return;
 double yaw=std::atan2(forward.x(),forward.y());
 double pitch=std::asin(std::clamp(forward.z(),-1.,1.));
 double angle=osg::DegreesToRadians(120.)/height*sensitivity;
 double limit=osg::DegreesToRadians(85.);
 yaw+=dx*angle;pitch=std::clamp(pitch-dy*angle,-limit,limit);
 forward.set(std::sin(yaw)*std::cos(pitch),std::cos(yaw)*std::cos(pitch),std::sin(pitch));
 auto right=forward^osg::Vec3d(0,0,1);right.normalize();camera.up=right^forward;
 camera.center=camera.eye+forward*distance;
}

inline void orbitMouseCamera(MouseCamera& camera,osg::Vec3d pivot,double dx,double dy,
                             double width,double height,double sensitivity=1.){
 if(width<=0||height<=0||(dx==0&&dy==0))return;
 auto forward=camera.center-camera.eye;
 if(forward.normalize()<1e-10)return;
 const osg::Vec3d worldUp(0,0,1);
 auto right=forward^worldUp;
 if(right.normalize()<1e-6){
  right=forward^camera.up;
  right.z()=0;
  if(right.normalize()<1e-10)return;
 }
 constexpr double pitchLimit=1.5707963267948966-.001;
 double pitch=std::atan2(forward.z(),std::hypot(forward.x(),forward.y()));
 double pitchDelta=std::clamp(pitch-2.*dy/height*sensitivity,-pitchLimit,pitchLimit)-pitch;
 osg::Quat tilt(pitchDelta,right),yaw(-5.*dx/width*sensitivity,worldUp);
 // Turn both camera points about the same surface point so it stays under the grab.
 camera.eye=pivot+yaw*(tilt*(camera.eye-pivot));
 camera.center=pivot+yaw*(tilt*(camera.center-pivot));
 camera.up=(yaw*right)^(yaw*(tilt*forward));
 camera.up.normalize();
}

inline void centerMouseCamera(MouseCamera& camera,const osg::Vec3d& point){
 auto forward=camera.center-camera.eye;
 if(forward.normalize()<1e-10)return;
 double depth=(point-camera.eye)*forward;
 if(depth<=0)return;
 camera.eye=point-forward*depth;
 camera.center=point;
}

inline void zoomMouseCamera(MouseCamera& camera,double steps,const osg::Vec3d* point=nullptr){
 if(!std::isfinite(steps))return;
 auto forward=camera.center-camera.eye;double distance=forward.normalize();if(!std::isfinite(distance)||distance<1e-10)return;
 const auto anchor=point?*point:camera.center;
 double depth=(anchor-camera.eye)*forward;
 if(depth<=0)return;
 double nextDepth=std::clamp(depth*std::exp(std::clamp(-.12*steps,-20.,20.)),point?.02:1e-5,1e12);
 camera.eye=anchor+(camera.eye-anchor)*(nextDepth/depth);
 camera.center=camera.eye+forward*nextDepth;
}
