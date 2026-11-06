"""Time-aware camera curves with shared velocity and zero acceleration at keys.

Quintic Bezier control pairs share each key's tangent. Rotation uses the same
construction on the unit-quaternion sphere (spherical de Casteljau), so a key
is passed continuously rather than easing to rest on every segment. Repeated
values have zero tangents and remain a true hold. Only endpoints must stop.
"""
import bisect
import math

import numpy as np


def quaternion(matrix):
    """Right-handed camera matrix -> unit quaternion (w, x, y, z)."""
    m=matrix;trace=float(np.trace(m))
    if trace>0:
        s=math.sqrt(trace+1)*2
        q=np.array([s/4,(m[2,1]-m[1,2])/s,(m[0,2]-m[2,0])/s,(m[1,0]-m[0,1])/s])
    else:
        i=int(np.argmax(np.diag(m)));j=(i+1)%3;k=(i+2)%3
        s=math.sqrt(max(0,1+m[i,i]-m[j,j]-m[k,k]))*2
        q=np.zeros(4);q[0]=(m[k,j]-m[j,k])/s;q[i+1]=s/4
        q[j+1]=(m[j,i]+m[i,j])/s;q[k+1]=(m[k,i]+m[i,k])/s
    return q/np.linalg.norm(q)


def rotation(q):
    w,x,y,z=q
    return np.array([[1-2*(y*y+z*z),2*(x*y-z*w),2*(x*z+y*w)],
                     [2*(x*y+z*w),1-2*(x*x+z*z),2*(y*z-x*w)],
                     [2*(x*z-y*w),2*(y*z+x*w),1-2*(x*x+y*y)]])


def _multiply(a,b):
    return np.r_[a[0]*b[0]-np.dot(a[1:],b[1:]),a[0]*b[1:]+b[0]*a[1:]+np.cross(a[1:],b[1:])]


def _log(q):
    length=float(np.linalg.norm(q[1:]))
    return q[1:]*(math.atan2(length,q[0])/length if length>1e-15 else 1)


def _exp(vector):
    angle=float(np.linalg.norm(vector))
    return np.r_[math.cos(angle),vector*np.sinc(angle/np.pi)]


def _slerp(a,b,t):
    # Controls already share a coherent quaternion sign. Flipping signs inside
    # de Casteljau would change the curve and break its endpoint derivatives.
    angle=np.arccos(np.clip(np.sum(a*b,axis=-1),-1,1))/np.pi
    q=((1-t)*np.sinc((1-t)*angle)[:,None]*a+t*np.sinc(t*angle)[:,None]*b)/np.sinc(angle)[:,None]
    return q/np.linalg.norm(q,axis=-1)[:,None]


def _shared_velocity(before,after,h0,h1):
    velocity=(before*h1+after*h0)/(h0+h1)
    speed0,speed1=float(np.linalg.norm(before)),float(np.linalg.norm(after))
    # A long segment must not turn a tiny neighbouring move into a large loop.
    limit=min(speed0,speed1,2*min(speed0*h0,speed1*h1)/max(h0,h1))
    length=float(np.linalg.norm(velocity))
    return velocity*min(1,limit/length) if length>0 else velocity


def _tangents(values,times,scalar=False):
    delta=np.diff(times);slopes=np.diff(values,axis=0)/delta[:,None]
    result=np.zeros_like(values)
    for i in range(1,len(times)-1):
        a,b=slopes[i-1:i+1]
        if scalar:
            # Bound both inner control points to the interval's value range.
            # This preserves positive distance and valid FOV without clipping.
            same=a*b>0
            result[i,same]=np.sign(a[same])*np.minimum(np.abs(a[same]),np.abs(b[same]))
        else:result[i]=_shared_velocity(a,b,delta[i-1],delta[i])
    return result


def _controls(a,b,va,vb,seconds):
    return np.array([a,a+va*seconds/5,a+2*va*seconds/5,b-2*vb*seconds/5,b-vb*seconds/5,b])


def _bezier(controls,t):
    powers=np.arange(6)
    weights=np.array([1,5,10,10,5,1])*t**powers*(1-t)**(5-powers)
    return weights@controls


class CameraPath:
    def __init__(self,keys,bases):
        self.keys=keys;self.times=np.array([k['time'] for k in keys])
        self.origin=np.array(keys[0]['center'])
        centers=np.array([k['center'] for k in keys])-self.origin
        scalars=np.array([[math.log(distance),k['fovy']] for k,(_,distance) in zip(keys,bases)])
        q=np.array([quaternion(basis) for basis,_ in bases])
        for i in range(1,len(q)):
            if np.dot(q[i-1],q[i])<0:q[i]*=-1
        center_v=_tangents(centers,self.times);scalar_v=_tangents(scalars,self.times,scalar=True)
        angular=np.zeros((len(q),3));delta=np.diff(self.times)
        for i in range(1,len(q)-1):
            inverse=q[i]*np.array([1,-1,-1,-1])
            before=-_log(_multiply(inverse,q[i-1]))/delta[i-1]
            after=_log(_multiply(inverse,q[i+1]))/delta[i]
            angular[i]=_shared_velocity(before,after,delta[i-1],delta[i])
        self.centers=[];self.scalars=[];self.orientations=[]
        for i,seconds in enumerate(delta):
            self.centers.append(_controls(centers[i],centers[i+1],center_v[i],center_v[i+1],seconds))
            self.scalars.append(_controls(scalars[i],scalars[i+1],scalar_v[i],scalar_v[i+1],seconds))
            self.orientations.append(np.array([q[i],
                _multiply(q[i],_exp(angular[i]*seconds/5)),
                _multiply(q[i],_exp(angular[i]*2*seconds/5)),
                _multiply(q[i+1],_exp(-angular[i+1]*2*seconds/5)),
                _multiply(q[i+1],_exp(-angular[i+1]*seconds/5)),q[i+1]]))

    def at(self,stamp):
        stamp=float(stamp)
        if not math.isfinite(stamp):raise ValueError('时间无效 / Invalid time')
        i=max(0,min(len(self.keys)-1,bisect.bisect_right(self.times,stamp)-1))
        if stamp<=self.times[0] or stamp>=self.times[-1] or stamp==self.times[i]:
            key=self.keys[i]
            return {name:list(key[name]) if name!='fovy' else key[name] for name in ('eye','center','up','fovy')}
        t=(stamp-self.times[i])/(self.times[i+1]-self.times[i])
        q=self.orientations[i]
        while len(q)>1:q=_slerp(q[:-1],q[1:],t)
        matrix=rotation(q[0]);center=self.origin+_bezier(self.centers[i],t)
        distance,fovy=_bezier(self.scalars[i],t)
        eye=center+matrix[:,2]*math.exp(distance)
        return dict(eye=eye.tolist(),center=center.tolist(),up=matrix[:,1].tolist(),fovy=float(fovy))
