"""Bounded-memory static GLB reader. Output is Z-up, with OBJ/OSG UVs."""
import base64
import json
import mmap
import struct
from functools import lru_cache
from pathlib import Path
from urllib.parse import unquote, urlparse
import numpy as np

Y_TO_Z = np.array([[1,0,0,0],[0,0,-1,0],[0,1,0,0],[0,0,0,1]], dtype=float)
DTYPES = {5120:'i1',5121:'u1',5122:'<i2',5123:'<u2',5125:'<u4',5126:'<f4'}
WIDTHS = {'SCALAR':1,'VEC2':2,'VEC3':3,'VEC4':4}


@lru_cache(maxsize=16)
def parse_document(data):
    """Immutable source JSON shared by the many chunks of one GLB."""
    return json.loads(data)


def local_uri(base, uri):
    if urlparse(uri).scheme or uri.startswith(('//','\\')):
        raise ValueError(f'只支持本地相对文件引用: {uri}')
    result=(base/unquote(uri)).resolve()
    return result


def matrix_of(node):
    if 'matrix' in node:
        return np.array(node['matrix'],dtype=float).reshape(4,4).T
    x,y,z,w=node.get('rotation',[0,0,0,1])
    m=np.eye(4)
    m[:3,:3]=[[1-2*(y*y+z*z),2*(x*y-z*w),2*(x*z+y*w)],
               [2*(x*y+z*w),1-2*(x*x+z*z),2*(y*z-x*w)],
               [2*(x*z-y*w),2*(y*z+x*w),1-2*(x*x+y*y)]]
    m[:3,:3] @= np.diag(node.get('scale',[1,1,1]))
    m[:3,3]=node.get('translation',[0,0,0])
    return m


class Glb:
    def __init__(self, path):
        self.path=Path(path)
        self.file=self.path.open('rb')
        self.mm=None
        try:
            self.mm=mmap.mmap(self.file.fileno(),0,access=mmap.ACCESS_READ)
            start=0; self.rtc=np.eye(4)
            if self.mm[:4]==b'b3dm':
                magic,v,total,fj,fb,bj,bb=struct.unpack_from('<4s6I',self.mm)
                if v!=1 or total!=len(self.mm):raise ValueError('无效 b3dm 长度/版本')
                feature=json.loads(self.mm[28:28+fj] or b'{}')
                rtc=feature.get('RTC_CENTER',[0,0,0])
                if isinstance(rtc,dict):rtc=struct.unpack_from('<3f',self.mm,28+fj+rtc['byteOffset'])
                self.rtc[:3,3]=rtc
                start=28+fj+fb+bj+bb
            magic,version,total=struct.unpack_from('<4sII',self.mm,start)
            if magic!=b'glTF' or version!=2 or start+total!=len(self.mm):
                raise ValueError('GLB 文件头、版本或长度无效（可能被截断）')
            pos=start+12; self.bin_offset=None; self.bin_length=0; self.doc=None
            while pos<start+total:
                size,kind=struct.unpack_from('<II',self.mm,pos);pos+=8
                if pos+size>start+total:raise ValueError('GLB chunk 越界')
                if kind==0x4e4f534a:self.doc=parse_document(self.mm[pos:pos+size])
                if kind==0x004e4942:self.bin_offset=pos;self.bin_length=size
                pos+=size
            if self.doc is None or self.bin_offset is None:raise ValueError('缺少 GLB JSON/BIN')
            required=set(self.doc.get('extensionsRequired',[]))
            supported={'KHR_materials_unlit','KHR_texture_basisu','KHR_mesh_quantization','KHR_texture_transform'}
            if required-supported:raise ValueError(f'不支持必需扩展: {required-supported}')
            if self.doc.get('skins') or self.doc.get('animations'):raise ValueError('只支持静态 mesh，包含骨骼或动画')
            if len(self.doc.get('buffers',[]))!=1 or self.doc['buffers'][0].get('uri'):
                raise ValueError('只支持单一内嵌 GLB buffer')
        except Exception:
            self.close();raise

    def __enter__(self):return self
    def __exit__(self,*args):self.close()
    def close(self):
        if self.mm is not None:self.mm.close()
        self.file.close()

    def view_bytes(self,index):
        v=self.doc['bufferViews'][index]
        start=v.get('byteOffset',0);size=v['byteLength']
        if v.get('buffer',0)!=0 or start<0 or start+size>self.bin_length:raise ValueError('bufferView 越界')
        return self.mm[self.bin_offset+start:self.bin_offset+start+size]

    def accessor(self,index):
        a=self.doc['accessors'][index]
        if a.get('sparse'):raise ValueError('暂不支持 sparse accessor')
        v=self.doc['bufferViews'][a['bufferView']]
        if v.get('extensions'):raise ValueError('不支持压缩 bufferView')
        dtype=np.dtype(DTYPES[a['componentType']]);width=WIDTHS[a['type']]
        stride=v.get('byteStride',dtype.itemsize*width);offset=a.get('byteOffset',0)
        count=a['count'];length=(count-1)*stride+dtype.itemsize*width if count else 0
        if offset<0 or offset+length>v['byteLength'] or v.get('byteOffset',0)+v['byteLength']>self.bin_length:
            raise ValueError('accessor 越界')
        arr=np.ndarray((count,width),dtype=dtype,buffer=self.mm,
                       offset=self.bin_offset+v.get('byteOffset',0)+offset,
                       strides=(stride,dtype.itemsize)).copy()
        if a.get('normalized') and dtype.kind in 'iu':
            arr=np.maximum(arr.astype(float)/np.iinfo(dtype).max,-1)
        return arr

    def instances(self):
        nodes=self.doc.get('nodes',[])
        def walk(i,parent,active):
            if i in active:raise ValueError('GLB 节点循环引用')
            n=nodes[i]
            if n.get('extensions',{}).get('EXT_mesh_gpu_instancing'):raise ValueError('不支持 GPU 实例扩展')
            m=parent @ matrix_of(n)
            if 'mesh' in n:yield i,n['mesh'],m
            for c in n.get('children',[]):yield from walk(c,m,active|{i})
        roots=self.doc.get('scenes',[{'nodes':list(range(len(nodes)))}])[self.doc.get('scene',0)].get('nodes',[])
        for root in roots:yield from walk(root,np.eye(4),set())

    def primitives(self, transform=None, instance=None, chunk=None):
        base=np.eye(4) if transform is None else transform
        for node_id,mesh_id,node_matrix in self.instances():
            if instance is not None and node_id!=instance:continue
            m=base @ self.rtc @ Y_TO_Z @ node_matrix
            for number,p in enumerate(self.doc['meshes'][mesh_id]['primitives']):
                if chunk is not None and not chunk[0]<=number<chunk[1]:continue
                if p.get('mode',4)!=4 or p.get('targets') or p.get('extensions'):
                    raise ValueError('只支持未压缩静态三角形 primitive')
                attrs=p['attributes']; xyz=self.accessor(attrs['POSITION']).astype(float)
                xyz=xyz @ m[:3,:3].T+m[:3,3]
                idx=self.accessor(p['indices']).reshape(-1) if 'indices' in p else np.arange(len(xyz))
                if len(idx)%3 or (len(idx) and (idx.min()<0 or idx.max()>=len(xyz))):raise ValueError('三角形索引无效')
                idx=idx.astype('<u4').reshape(-1,3)
                if np.linalg.det(m[:3,:3])<0:idx=idx[:,[0,2,1]]
                material=self.doc.get('materials',[])[p['material']] if 'material' in p else {}
                pbr=material.get('pbrMetallicRoughness',{})
                tex=pbr.get('baseColorTexture',{})
                transform_uv=tex.get('extensions',{}).get('KHR_texture_transform',{})
                uv_key='TEXCOORD_'+str(transform_uv.get('texCoord',tex.get('texCoord',0)))
                uv=self.accessor(attrs[uv_key]).astype(float) if uv_key in attrs else None
                if tex and uv is None:raise ValueError('纹理缺少对应 UV')
                if uv is not None:
                    angle=transform_uv.get('rotation',0);c=np.cos(angle);s=np.sin(angle)
                    uv=(uv*np.array(transform_uv.get('scale',[1,1]))) @ np.array([[c,s],[-s,c]])
                    uv+=transform_uv.get('offset',[0,0]);uv[:,1]=1-uv[:,1]
                normals=None
                if 'NORMAL' in attrs:
                    normals=self.accessor(attrs['NORMAL']) @ np.linalg.inv(m[:3,:3])
                    norms=np.linalg.norm(normals,axis=1);normals/=np.maximum(norms[:,None],1e-30)
                if not np.isfinite(xyz).all():raise ValueError('顶点包含 NaN/Inf')
                if 'COLOR_0' in attrs:raise ValueError('暂不支持顶点颜色，请使用烘焙纹理数据')
                if any(k in material for k in ('normalTexture','occlusionTexture','emissiveTexture')) or pbr.get('metallicRoughnessTexture'):
                    raise ValueError('OBJ/OSGB 无法无损保留此 PBR 材质，请先烘焙为基础颜色纹理')
                yield {'positions':xyz,'indices':idx,'uv':uv,'normals':normals,
                       'material':material,'texture':tex.get('index'),
                       'color':pbr.get('baseColorFactor',[1,1,1,1]),'node':node_id,'primitive':number}

    def image(self,texture):
        t=self.doc['textures'][texture]
        image_index=t.get('extensions',{}).get('KHR_texture_basisu',{}).get('source',t.get('source'))
        im=self.doc['images'][image_index]
        if 'bufferView' in im:data=self.view_bytes(im['bufferView'])
        else:
            uri=im['uri']
            data=base64.b64decode(uri.split(',',1)[1]) if uri.startswith('data:') else local_uri(self.path.parent,uri).read_bytes()
        ext={'image/jpeg':'.jpg','image/png':'.png','image/ktx2':'.ktx2'}.get(im.get('mimeType'))
        if ext is None:
            ext='.png' if data.startswith(b'\x89PNG') else '.jpg' if data.startswith(b'\xff\xd8') else None
        if ext is None:raise ValueError('不支持的纹理图像格式')
        sampler=self.doc.get('samplers',[])[t['sampler']] if 'sampler' in t else {}
        return data,ext,sampler
