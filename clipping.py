"""Axis-aligned six-plane triangle clipping, including UV and normal interpolation."""
import numpy as np


def clip_primitive(part, box):
    box=np.asarray(box,dtype=float)
    if box.shape!=(6,) or not np.isfinite(box).all() or np.any(box[:3]>=box[3:]):
        raise ValueError('剪切盒范围无效 / Invalid clipping box')
    positions=part['positions'];indices=part['indices']
    triangles=positions[indices]
    inside=np.all((triangles>=box[:3]) & (triangles<=box[3:]),axis=(1,2))
    if inside.all():return part
    outside=np.any(triangles.max(axis=1)<box[:3],axis=1)|np.any(triangles.min(axis=1)>box[3:],axis=1)
    attrs=[positions];widths=[3]
    for key in ('uv','normals'):
        if part[key] is not None:attrs.append(part[key]);widths.append(part[key].shape[1])
    data=np.concatenate(attrs,axis=1)
    output=[data[indices[inside]].reshape(-1,data.shape[1])]
    for face in indices[~inside & ~outside]:
        polygon=[data[i] for i in face]
        for axis in range(3):
            for sign,limit in [(1,box[axis]),(-1,box[axis+3])]:
                if not polygon:break
                clipped=[];previous=polygon[-1];dp=sign*(previous[axis]-limit)
                for current in polygon:
                    dc=sign*(current[axis]-limit)
                    if (dc>=0)!=(dp>=0):
                        t=dp/(dp-dc);point=previous+t*(current-previous);point[axis]=limit;clipped.append(point)
                    if dc>=0:clipped.append(current)
                    previous=current;dp=dc
                polygon=clipped
        if len(polygon)>=3:
            output.append(np.array([p for i in range(1,len(polygon)-1) for p in (polygon[0],polygon[i],polygon[i+1])]))
    merged=np.concatenate(output,axis=0)
    result=dict(part);result['positions']=merged[:,:3];cursor=3
    for key in ('uv','normals'):
        if part[key] is not None:
            width=part[key].shape[1];result[key]=merged[:,cursor:cursor+width];cursor+=width
            if key=='normals':result[key]/=np.maximum(np.linalg.norm(result[key],axis=1)[:,None],1e-30)
    result['indices']=np.arange(len(merged),dtype=np.uint32).reshape(-1,3)
    return result
