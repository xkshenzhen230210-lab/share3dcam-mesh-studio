#pragma once
#include <osg/Vec3d>
#include <algorithm>
#include <cmath>

// W/S follow the camera; A/D strafe; Q/E always use the model's Z axis.
inline osg::Vec3d navigationDelta(osg::Vec3d forward,osg::Vec3d up,double rightKey,double forwardKey,double verticalKey,double speed,double dt){
 if(!std::isfinite(speed)||speed<=0||!std::isfinite(dt)||dt<=0||forward.length2()<1e-20)return {};
 forward.normalize();auto right=forward^osg::Vec3d(0,0,1);
 if(right.length2()<1e-12)right=forward^up;
 if(right.length2()<1e-12)return {};right.normalize();
 auto direction=forward*forwardKey+right*rightKey+osg::Vec3d(0,0,verticalKey);
 if(direction.length2()>1)direction.normalize();return direction*(speed*std::min(dt,.1));
}
