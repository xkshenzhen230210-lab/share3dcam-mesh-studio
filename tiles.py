import json
from dataclasses import dataclass, field
from pathlib import Path
import numpy as np
from gltf import local_uri


@dataclass(eq=False)
class Tile:
    output: Path
    source: Path | None = None
    transform: np.ndarray = field(default_factory=lambda:np.eye(4))
    children: list = field(default_factory=list)
    error: float = 0
    refine: str = 'REPLACE'
    center: list = field(default_factory=lambda:[0,0,0])
    radius: float = 1
    instance: int | None = None
    chunk: tuple | None = None


def flatten(root):
    yield root
    for c in root.children:yield from flatten(c)


def obj_nodes(root):
    result=[]
    if root.source and (not root.children or root.refine=='ADD'):result.append(root)
    for c in root.children:result.extend(obj_nodes(c))
    return result


def load_tiles(path):
    path=Path(path).resolve();base=path.parent;used=set();counter=0
    def allocate(candidate):
        nonlocal counter
        candidate=Path(candidate)
        if candidate in used:
            counter+=1;candidate=candidate.with_stem(candidate.stem+f'_{counter}')
        used.add(candidate);return candidate
    def load_file(file,parent,refine,active,output=None):
        if file in active:raise ValueError(f'Tileset 循环引用: {file}')
        doc=json.loads(file.read_text(encoding='utf-8-sig'))
        if doc.get('extensionsRequired'):raise ValueError('不支持 Tileset 必需扩展')
        return visit(doc['root'],file.parent,parent,refine,active|{file},output)
    def visit(n,folder,parent,refine,active,output=None):
        nonlocal counter
        if n.get('implicitTiling') or n.get('contents') or n.get('extensions'):
            raise ValueError('暂不支持隐式瓦片、多 content 或瓦片扩展')
        m=parent @ np.array(n.get('transform',np.eye(4).T.reshape(-1)),dtype=float).reshape(4,4).T
        refine=n.get('refine',refine).upper()
        if refine not in ('ADD','REPLACE'):raise ValueError('无效 refine')
        content=n.get('content',{});uri=content.get('uri',content.get('url'))
        source=local_uri(folder,uri) if uri else None
        if source:
            if not source.is_file():raise FileNotFoundError(f'缺少瓦片: {source}')
            if not source.is_relative_to(base):raise ValueError(f'瓦片引用超出输入目录: {source}')
        if source and source.suffix.lower()=='.json':
            child_output=source.relative_to(base).with_name(source.parent.name+'.osgb')
            tree=load_file(source,m,refine,active,output or child_output)
            tree.children.extend(visit(c,folder,m,refine,active) for c in n.get('children',[]))
            return tree
        if source and source.suffix.lower() not in ('.glb','.b3dm'):raise ValueError(f'不支持瓦片格式: {source.suffix}')
        if output is None:
            if source:output=source.relative_to(base).with_suffix('.osgb')
            else:
                counter+=1;output=Path('_nodes')/f'node_{counter:05}.osgb'
        tile=Tile(allocate(output),source,m,error=float(n.get('geometricError',0)),refine=refine)
        bv=n.get('boundingVolume',{})
        if 'box' in bv:
            b=np.array(bv['box']);tile.center=(m[:3,:3]@b[:3]+m[:3,3]).tolist()
            axes=b[3:].reshape(3,3).T
            tile.radius=max(float(np.linalg.norm(m[:3,:3]@axes@np.array(s))) for s in __import__('itertools').product([-1,1],repeat=3))
        elif 'sphere' in bv:
            s=bv['sphere'];tile.center=(m[:3,:3]@s[:3]+m[:3,3]).tolist();tile.radius=float(s[3]*np.linalg.norm(m[:3,:3],2))
        elif 'region' in bv:
            raise ValueError('暂不支持 region 包围体，请使用本地 box/sphere Tileset')
        tile.error*=float(np.linalg.norm(m[:3,:3],2))
        tile.children=[visit(c,folder,m,refine,active) for c in n.get('children',[])]
        return tile
    return load_file(path,np.eye(4),'REPLACE',set(),Path('Model.osgb'))
