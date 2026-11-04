"""Readers for the generated PLY/STL and native extracted OBJ/OSGB meshes."""
import json
import struct
from pathlib import Path
from functools import lru_cache
import numpy as np
from gltf import Glb
from tiles import Tile

CHUNK=100000


@lru_cache(maxsize=4)
def mesh_document(path,mtime,size):
    return json.loads(Path(path).read_text(encoding='utf-8'))


class Mesh:
    def __init__(self,path):
        self.path=Path(path);self.ext=self.path.suffix.lower();self.textures=[]
        if self.ext=='.mesh':
            stat=self.path.stat();self.doc=mesh_document(str(self.path),stat.st_mtime_ns,stat.st_size);self.count=len(self.doc['parts'])
        elif self.ext=='.stl':
            with self.path.open('rb') as f:f.seek(80);self.count=struct.unpack('<I',f.read(4))[0]
            if self.path.stat().st_size!=84+50*self.count:raise ValueError('需要 binary STL / Binary STL required')
            self.faces=np.memmap(self.path,mode='r',offset=84,dtype=[('normal','<f4',3),('xyz','<f4',(3,3)),('attr','<u2')],shape=(self.count,))
        elif self.ext=='.ply':
            with self.path.open('rb') as f:
                header=[]
                while True:
                    line=f.readline()
                    if not line or len(header)>100000:raise ValueError('Invalid PLY header')
                    header.append(line.decode('utf-8').strip())
                    if line.strip()==b'end_header':break
                offset=f.tell()
            if 'format binary_little_endian 1.0' not in header:raise ValueError('需要 binary little-endian PLY')
            nv=int(next(x.split()[-1] for x in header if x.startswith('element vertex ')))
            self.count=int(next(x.split()[-1] for x in header if x.startswith('element face ')))
            vi=header.index(f'element vertex {nv}');fi=header.index(f'element face {self.count}')
            if header[vi+1:fi]!=['property float x','property float y','property float z']:raise ValueError('PLY vertex layout unsupported')
            self.textures=[x[len('comment TextureFile '):] for x in header if x.startswith('comment TextureFile ')]
            faceprops=header[fi+1:-1];self.textured='property list uchar float texcoord' in faceprops
            expected=['property list uchar uint vertex_indices']
            if self.textured:expected+=['property list uchar float texcoord','property int texnumber']
            if faceprops!=expected:raise ValueError('PLY face layout unsupported')
            dtype=[('nv','u1'),('idx','<u4',3)]
            if self.textured:dtype += [('nt','u1'),('uv','<f4',(3,2)),('tex','<i4')]
            if offset+nv*12+self.count*np.dtype(dtype).itemsize!=self.path.stat().st_size:raise ValueError('PLY must contain triangular faces / PLY 面结构或长度无效')
            self.xyz=np.memmap(self.path,mode='r',offset=offset,dtype='<f4',shape=(nv,3))
            self.faces=np.memmap(self.path,mode='r',offset=offset+nv*12,dtype=dtype,shape=(self.count,))
        else:raise ValueError(f'Unsupported mesh {self.ext}')
    def __enter__(self):return self
    def __exit__(self,*args):
        for name in ('xyz','faces'):
            value=getattr(self,name,None)
            if value is not None:value._mmap.close()
    def image(self,tid):
        name=self.doc['textures'][tid] if self.ext=='.mesh' else self.textures[tid]
        p=Path(name)
        if not p.is_absolute():p=self.path.parent/p
        samplers=self.doc.get('samplers',[]) if self.ext=='.mesh' else []
        return p.read_bytes(),p.suffix.lower(),samplers[tid] if tid<len(samplers) else {}
    def primitives(self,transform=None,instance=None,chunk=None):
        start,end=chunk or (0,self.count)
        if self.ext=='.mesh':
            for i in range(start,end):
                p=dict(self.doc['parts'][i]);n=p.pop('vertices');filename=p.pop('buffer')
                with (self.path.parent/filename).open('rb') as f:
                    xyz=np.fromfile(f,dtype='<f8',count=n*3).reshape(-1,3)
                    uv=np.fromfile(f,dtype='<f4',count=n*2).reshape(-1,2) if p.pop('has_uv') else None
                    normals=np.fromfile(f,dtype='<f4',count=n*3).reshape(-1,3) if p.pop('has_normals',False) else None
                yield dict(positions=xyz,indices=np.arange(n,dtype=np.uint32).reshape(-1,3),uv=uv,normals=normals,material=p.get('material',{}),color=p.get('color',[1,1,1,1]),texture=p.get('texture'),node=0,primitive=i)
            return
        for begin in range(start,end,CHUNK):
            faces=self.faces[begin:min(begin+CHUNK,end)]
            if self.ext=='.stl':
                xyz=faces['xyz'].reshape(-1,3).astype(float);uv=None;groups=[(None,xyz,uv)]
            else:
                if np.any(faces['nv']!=3) or (self.textured and np.any(faces['nt']!=6)):raise ValueError('PLY triangles / UV lists invalid')
                if np.any(faces['idx']>=len(self.xyz)):raise ValueError('PLY index out of range')
                groups=[]
                for tid in np.unique(faces['tex']) if self.textured else [None]:
                    subset=faces[faces['tex']==tid] if tid is not None else faces
                    xyz=self.xyz[subset['idx']].reshape(-1,3).astype(float)
                    uv=subset['uv'].reshape(-1,2).copy() if tid is not None else None
                    if tid is not None and not 0<=tid<len(self.textures):raise ValueError('PLY texture index invalid')
                    groups.append((int(tid) if tid is not None else None,xyz,uv))
            for tid,xyz,uv in groups:
                yield dict(positions=xyz,indices=np.arange(len(xyz),dtype=np.uint32).reshape(-1,3),uv=uv,normals=None,material={'doubleSided':True},color=[1,1,1,1] if tid is not None else [.74,.78,.83,1],texture=tid,node=0,primitive=begin)


def reader(path):return Glb(path) if Path(path).suffix.lower() in ('.glb','.b3dm') else Mesh(path)


def mesh_tree(path):
    root=Tile(Path('Model.osgb'));block=Tile(Path('Block_0/Block_0.osgb'));root.children.append(block)
    with Mesh(path) as mesh:
        step=1 if mesh.ext=='.mesh' else CHUNK
        for i,start in enumerate(range(0,mesh.count,step)):
            block.children.append(Tile(Path(f'Block_0/Block_0_Part{i}.osgb'),Path(path),chunk=(start,min(start+step,mesh.count))))
    return root
