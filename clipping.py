"""Six-plane clipping in a working frame, preserving source geometry and UVs."""
import numpy as np
from spatial_frame import ClipBox


def clip_primitive(part, box):
    volume=ClipBox(box);box=volume.bounds
    if volume.polygon is not None:
        from polygon_selection import triangulate
        boundary={frozenset((tuple(a),tuple(b))) for a,b in zip(volume.polygon,np.roll(volume.polygon,-1,axis=0))}
        pieces=[_clip(part,volume,ear,boundary) for ear in triangulate(volume.polygon)]
        result=dict(part)
        for key in ('positions','uv','normals'):
            if part[key] is not None:result[key]=np.concatenate([p[key][p['indices']].reshape(-1,p[key].shape[1]) for p in pieces],axis=0)
        result['indices']=np.arange(len(result['positions']),dtype=np.uint32).reshape(-1,3)
        return result
    return _clip(part,volume)


def _clip(part,volume,ear=None,boundary=None):
    box=volume.bounds
    positions=part['positions'];indices=part['indices']
    local=volume.local(positions)
    triangles=local[indices]
    inside=np.all((triangles>=box[:3]) & (triangles<=box[3:]),axis=(1,2))
    planes=[]
    for axis in range(3):
        n=np.zeros(3);n[axis]=1;planes.extend([(n.copy(),-box[axis]),(-n,-(-box[axis+3]))])
    excluded=np.zeros(len(indices),dtype=bool);outside_ear=excluded.copy()
    if ear is not None:
        for a,b in zip(ear,np.roll(ear,-1,axis=0)):
            d=b-a;n=np.array([-d[1],d[0],0.]);offset=-np.dot(n[:2],a)
            planes.append((n,offset));distance=triangles@n+offset
            inside &= np.all(distance>=0,axis=1);outside_ear |= np.all(distance<0,axis=1)
            # A vertical source face can lie exactly on an internal ear edge.
            # Give it one owner, avoiding duplicate faces in exported geometry.
            if frozenset((tuple(a),tuple(b))) not in boundary and tuple(a)>tuple(b):
                excluded |= np.all(abs(triangles@n+offset)<=np.linalg.norm(n)*1e-10,axis=1)
        inside &= ~excluded
    if inside.all():return part
    outside=np.any(triangles.max(axis=1)<box[:3],axis=1)|np.any(triangles.min(axis=1)>box[3:],axis=1)
    outside |= excluded|outside_ear
    # Carry world positions as attributes: untouched vertices stay exact, while
    # intersections interpolate world positions, UVs and normals together.
    attrs=[local,positions];widths=[3,3]
    for key in ('uv','normals'):
        if part[key] is not None:attrs.append(part[key]);widths.append(part[key].shape[1])
    data=np.concatenate(attrs,axis=1)
    output=[data[indices[inside]].reshape(-1,data.shape[1])]
    for face in indices[~inside & ~outside]:
        polygon=[data[i] for i in face]
        for normal,offset in planes:
            if not polygon:break
            clipped=[];previous=polygon[-1];dp=previous[:3]@normal+offset
            for current in polygon:
                dc=current[:3]@normal+offset
                if (dc>=0)!=(dp>=0):
                    t=dp/(dp-dc);point=previous+t*(current-previous);clipped.append(point)
                if dc>=0:clipped.append(current)
                previous=current;dp=dc
            polygon=clipped
        if len(polygon)>=3:
            output.append(np.array([p for i in range(1,len(polygon)-1) if np.linalg.norm(np.cross(polygon[i][3:6]-polygon[0][3:6],polygon[i+1][3:6]-polygon[0][3:6]))>1e-20 for p in (polygon[0],polygon[i],polygon[i+1])]).reshape(-1,data.shape[1]))
    merged=np.concatenate(output,axis=0)
    result=dict(part);result['positions']=merged[:,3:6];cursor=6
    for key in ('uv','normals'):
        if part[key] is not None:
            width=part[key].shape[1];result[key]=merged[:,cursor:cursor+width];cursor+=width
            if key=='normals':result[key]/=np.maximum(np.linalg.norm(result[key],axis=1)[:,None],1e-30)
    result['indices']=np.arange(len(merged),dtype=np.uint32).reshape(-1,3)
    return result
