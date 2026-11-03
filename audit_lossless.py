"""Re-read OBJ independently and compare it to source GLB geometry and embedded images."""
import argparse
import hashlib
import io
import json
import re
from pathlib import Path
import numpy as np
from PIL import Image
from gltf import Glb
from clipping import clip_primitive
from converter import write_json


def read_obj(path):
    groups={};current=None;vc=tc=nc=0
    def finish():
        if current is None:return
        for k,width,dtype in [('v',3,float),('vt',2,float),('vn',3,float),('f',3,np.int64),('ft',3,np.int64)]:
            current[k]=np.asarray(current[k],dtype=dtype).reshape(-1,width)
        if current['f'].size:
            assert current['f'].min()>=0 and current['f'].max()<len(current['v'])
            assert current['ft'].min()>=0 and current['ft'].max()<len(current['vt'])
        groups[current['key']]=current
    with path.open(encoding='utf-8') as f:
        for line in f:
            words=line.split()
            if not words:continue
            tag=words[0]
            if tag=='g':
                finish();match=re.search(r'_n(\d+)_p(\d+)$',words[1]);assert match
                current={'key':tuple(map(int,match.groups())),'name':words[1],'v':[],'vt':[],'vn':[],'f':[],'ft':[],'vb':vc,'tb':tc,'nb':nc}
            elif tag=='usemtl':current['material']=words[1]
            elif tag=='v':current['v'].append(tuple(map(float,words[1:])));vc+=1
            elif tag=='vt':current['vt'].append(tuple(map(float,words[1:])));tc+=1
            elif tag=='vn':current['vn'].append(tuple(map(float,words[1:])));nc+=1
            elif tag=='f':
                assert len(words)==4
                parts=[w.split('/') for w in words[1:]]
                current['f'].append([int(p[0])-1-current['vb'] for p in parts])
                current['ft'].append([int(p[1])-1-current['tb'] for p in parts])
    finish();return groups


def reference_boundary(source,faces,box):
    """Independent clipping in barycentric coordinates, not interpolated world-space attributes."""
    result=[];tex=[];degenerate_origins=[]
    for face in faces:
        p=source['positions'][face];uv=source['uv'][face]
        polygon=[np.array([1.,0,0]),np.array([0.,1,0]),np.array([0.,0,1])]
        for axis in range(3):
            for sign,bound in [(1,box[axis]),(-1,box[axis+3])]:
                if not polygon:break
                out=[]
                for a,b in zip(polygon[-1:]+polygon[:-1],polygon):
                    da=sign*(a@p[:,axis]-bound);db=sign*(b@p[:,axis]-bound)
                    if (da>=0)!=(db>=0):out.append((db*a-da*b)/(db-da))
                    if db>=0:out.append(b)
                polygon=out
        for i in range(1,len(polygon)-1):
            weights=np.stack([polygon[0],polygon[i],polygon[i+1]])
            result.append(weights@p);tex.append(weights@uv)
            degenerate_origins.append(bool(np.linalg.norm(np.cross(p[1]-p[0],p[2]-p[0]))==0))
    return np.asarray(result).reshape(-1,3),np.asarray(tex).reshape(-1,2),np.array(degenerate_origins,dtype=bool)


def audit(source,folder):
    source=Path(source);folder=Path(folder);doc=json.loads((folder/'conversion_report.json').read_text(encoding='utf-8'));box=np.array(doc['clip_box'])
    groups=read_obj(folder/'obj/Model.obj');mtl={};name=None
    for line in (folder/'obj/Model.mtl').read_text(encoding='utf-8').splitlines():
        if line.startswith('newmtl '):name=line[7:];mtl[name]={}
        elif name and line.startswith('map_Kd '):mtl[name]['texture']=line[7:]
        elif name and line.startswith('Kd '):mtl[name]['color']=list(map(float,line.split()[1:]))
    report={'source':str(source),'box':box.tolist(),'groups':len(groups),'triangles':0,'vertices':0,'unchanged_triangles':0,'boundary_source_triangles':0,
            'position_roundtrip_max_error':0.,'uv_roundtrip_max_error':0.,'independent_boundary_position_max_error':0.,'independent_boundary_uv_max_error':0.,
            'zero_area_triangles':0,'source_inside_zero_area_triangles':0,'boundary_zero_area_from_source_degenerate':0,'boundary_zero_area_from_source_nondegenerate':0,'invalid_indices':0,'texture_byte_mismatches':0,'textures':{},'state':'checking'}
    matched=set();metadata_source=source.parent/'metadata.xml'
    report['metadata_identical']=(folder/'obj/metadata.xml').read_bytes()==metadata_source.read_bytes()
    with Glb(source) as glb:
        for part in glb.primitives():
            key=(part['node'],part['primitive'])
            xyz=part['positions'];idx=part['indices'];tri=xyz[idx]
            inside=np.all((tri>=box[:3])&(tri<=box[3:]),axis=(1,2))
            outside=np.any(tri.max(axis=1)<box[:3],axis=1)|np.any(tri.min(axis=1)>box[3:],axis=1)
            expected=clip_primitive(part,box)
            if not len(expected['indices']):assert key not in groups;continue
            assert key in groups,f'Missing primitive {key}';actual=groups[key];matched.add(key)
            assert np.array_equal(actual['f'],expected['indices'])
            assert np.array_equal(actual['ft'],expected['indices'])
            pe=float(np.max(np.abs(actual['v']-expected['positions'])));ue=float(np.max(np.abs(actual['vt']-expected['uv'])))
            report['position_roundtrip_max_error']=max(report['position_roundtrip_max_error'],pe)
            report['uv_roundtrip_max_error']=max(report['uv_roundtrip_max_error'],ue)
            assert pe==0 and ue==0,(key,pe,ue)
            assert np.isfinite(actual['v']).all() and np.isfinite(actual['vt']).all()
            used=actual['v'][actual['f']]
            assert np.all(used>=box[:3]-1e-12) and np.all(used<=box[3:]+1e-12)
            area=np.linalg.norm(np.cross(used[:,1]-used[:,0],used[:,2]-used[:,0]),axis=1)/2
            report['zero_area_triangles']+=int(np.count_nonzero(area==0))
            n_inside=int(inside.sum());cross=idx[~inside&~outside]
            uncut=tri[inside]
            if len(uncut):report['source_inside_zero_area_triangles']+=int(np.count_nonzero(np.linalg.norm(np.cross(uncut[:,1]-uncut[:,0],uncut[:,2]-uncut[:,0]),axis=1)==0))
            refxyz,refuv,degenerate_origins=reference_boundary(part,cross,box)
            if inside.all():refactual=np.empty((0,3));refactualuv=np.empty((0,2))
            else:refactual=actual['v'][actual['f'][n_inside:]].reshape(-1,3);refactualuv=actual['vt'][actual['ft'][n_inside:]].reshape(-1,2)
            assert refxyz.shape==refactual.shape,(key,refxyz.shape,refactual.shape)
            if len(refxyz):
                boundary_zero=area[n_inside:]==0
                report['boundary_zero_area_from_source_degenerate']+=int(np.count_nonzero(boundary_zero&degenerate_origins))
                report['boundary_zero_area_from_source_nondegenerate']+=int(np.count_nonzero(boundary_zero&~degenerate_origins))
                pe=float(np.max(np.abs(refxyz-refactual)));ue=float(np.max(np.abs(refuv-refactualuv)))
                report['independent_boundary_position_max_error']=max(report['independent_boundary_position_max_error'],pe)
                report['independent_boundary_uv_max_error']=max(report['independent_boundary_uv_max_error'],ue)
                assert pe<1e-10 and ue<1e-10,(key,pe,ue)
            report['unchanged_triangles']+=n_inside;report['boundary_source_triangles']+=len(cross)
            report['triangles']+=len(actual['f']);report['vertices']+=len(actual['v'])
            material=mtl[actual['material']];assert material['color']==part['color'][:3]
            if part['texture'] is not None:
                data,ext,sampler=glb.image(part['texture']);filename=material['texture'];target=folder/'obj'/filename
                original_hash=hashlib.sha256(data).hexdigest();target_hash=hashlib.sha256(target.read_bytes()).hexdigest()
                assert original_hash==target_hash,filename
                with Image.open(io.BytesIO(data)) as image,Image.open(target) as copy:
                    assert image.size==copy.size and image.mode==copy.mode;copy.verify()
                    report['textures'][filename]={'source_texture':part['texture'],'sha256':target_hash,'size':list(image.size),'format':image.format}
            if len(matched)%25==0:print('Audited primitives',len(matched),flush=True)
    assert matched==set(groups);assert report['triangles']==doc['obj_triangles']
    report['texture_count']=len(report['textures']);report['state']='passed'
    report['scope']='No mesh simplification; exact float64 OBJ roundtrip; embedded JPEG/PNG bytes unchanged. Cut triangles necessarily have new boundary topology; no automatic capping.'
    write_json(folder/'lossless_audit.json',report)
    print(json.dumps({k:v for k,v in report.items() if k!='textures'},ensure_ascii=False,indent=2),flush=True)
    return report

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('source');parser.add_argument('folder');args=parser.parse_args();audit(args.source,args.folder)
