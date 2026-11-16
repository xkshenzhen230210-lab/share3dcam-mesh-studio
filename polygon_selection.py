"""Simple horizontal polygons, with inclusive boundaries and ear triangulation."""
import numpy as np


def cross(a,b,c):
    u,v=b-a,c-a
    return u[0]*v[1]-u[1]*v[0]


def validate_polygon(value):
    p=np.asarray(value,dtype=float)
    if p.ndim!=2 or p.shape[1]!=2 or not 3<=len(p)<=128 or not np.isfinite(p).all():
        raise ValueError('范围需 3–128 个有限顶点 / Use 3–128 polygon vertices')
    p=p.copy();scale=max(float(np.ptp(p,axis=0).max()),1e-6);eps=scale*scale*1e-12
    if np.any(np.linalg.norm(p-np.roll(p,1,axis=0),axis=1)<=scale*1e-10):
        raise ValueError('相邻顶点不能重合 / Duplicate polygon vertex')
    def on(a,b,c):
        return abs(cross(a,b,c))<=eps and np.all(c>=np.minimum(a,b)-scale*1e-12) and np.all(c<=np.maximum(a,b)+scale*1e-12)
    for i in range(len(p)):
        a,b=p[i],p[(i+1)%len(p)]
        for j in range(i+1,len(p)):
            if j==i+1 or (i==0 and j==len(p)-1):continue
            c,d=p[j],p[(j+1)%len(p)]
            if (cross(a,b,c)*cross(a,b,d)<0 and cross(c,d,a)*cross(c,d,b)<0) or on(a,b,c) or on(a,b,d) or on(c,d,a) or on(c,d,b):
                raise ValueError('范围边线不能交叉或相碰 / Polygon edges intersect')
    # Collinear corners add no boundary and make ear selection ambiguous.
    changed=True
    while changed and len(p)>3:
        changed=False
        for i in range(len(p)):
            if on(p[i-1],p[(i+1)%len(p)],p[i]):p=np.delete(p,i,axis=0);changed=True;break
    area=sum(cross(p[0],p[i],p[i+1]) for i in range(1,len(p)-1))
    if abs(area)<=eps:raise ValueError('范围面积过小 / Polygon has no area')
    return p if area>0 else p[::-1].copy()


def triangulate(p):
    indices=list(range(len(p)));result=[]
    eps=max(float(np.ptp(p,axis=0).max())**2*1e-13,1e-24)
    while len(indices)>3:
        for at,b in enumerate(indices):
            a,c=indices[at-1],indices[(at+1)%len(indices)]
            if cross(p[a],p[b],p[c])<=eps:continue
            if any(all(cross(p[u],p[v],p[k])>=-eps for u,v in ((a,b),(b,c),(c,a))) for k in indices if k not in (a,b,c)):continue
            result.append(p[[a,b,c]]);indices.pop(at);break
        else:raise ValueError('无法分解范围 / Cannot triangulate polygon')
    result.append(p[indices]);return result


def contains_xy(xy,p):
    xy=np.asarray(xy);inside=np.zeros(xy.shape[:-1],dtype=bool);boundary=inside.copy()
    tol=max(float(np.ptp(p,axis=0).max())*1e-10,1e-12)
    for a,b in zip(p,np.roll(p,-1,axis=0)):
        u=b-a;delta=xy-a
        side=u[0]*delta[...,1]-u[1]*delta[...,0]
        boundary|=(abs(side)<=tol*np.linalg.norm(u)) & np.all(xy>=np.minimum(a,b)-tol,axis=-1) & np.all(xy<=np.maximum(a,b)+tol,axis=-1)
        if b[1]!=a[1]:
            inside^=((a[1]>xy[...,1])!=(b[1]>xy[...,1])) & (xy[...,0]<(b[0]-a[0])*(xy[...,1]-a[1])/(b[1]-a[1])+a[0])
    return inside|boundary
