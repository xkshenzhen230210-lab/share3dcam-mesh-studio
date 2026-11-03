"""Run real-data subset conversions without modifying source files."""
import json
import shutil
from pathlib import Path
from converter import convert,Control,RUNTIME
from gltf import Glb
from tiles import load_tiles,flatten
import numpy as np

SOURCE=Path(r'V:\给泽强\2.7版本\mesh\2.7.5新\藏经阁')
OUT=Path(__file__).parent/'validation';OUT.mkdir(exist_ok=True)

def main():
    tile=SOURCE/'3dtiles/Block_0/Block_0_Level18_1.glb'
    report=convert(tile,OUT/'real_tile_both','both')
    for p in (OUT/'real_tile_both/osgb').rglob('*Part*.osgb'):
        shutil.copy2(p,OUT/'check.osgb')
        info=json.loads(Control().run([RUNTIME/'mesh_writer.exe','inspect','check.osgb'],OUT))
        print('OSGB ROUNDTRIP',info,flush=True)
        assert info['textures']>0 and info['triangles']>0
    tree=load_tiles(SOURCE/'3dtiles/tileset.json')
    print('FULL TREE',len(list(flatten(tree))),flush=True)
    # Keep a real complete 2-leaf branch including its original bounds and refinement.
    doc=json.loads((SOURCE/'3dtiles/Block_0/tileset.json').read_text())
    def find(n):
        children=n.get('children',[])
        if len(children)==2 and all(not c.get('children') for c in children):return n
        for c in children:
            r=find(c)
            if r:return r
    branch=find(doc['root']);fixture=OUT/'tile_input';fixture.mkdir()
    def copy(n):
        if n.get('content'):shutil.copy2(SOURCE/'3dtiles/Block_0'/n['content']['uri'],fixture/n['content']['uri'])
        for c in n.get('children',[]):copy(c)
    copy(branch)
    (fixture/'tileset.json').write_text(json.dumps({'asset':{'version':'1.1'},'root':branch}))
    shutil.copy2(SOURCE/'3dtiles/coordinate_contract.json',fixture)
    convert(fixture/'tileset.json',OUT/'real_tiles_both','both')
    # Compare original merged GLB and original OBJ first positions independently.
    with Glb(SOURCE/'glb/Model.glb') as g:
        p=next(g.primitives());print('MERGED GLB FIRST POSITIONS',p['positions'][:2].tolist(),flush=True)
    print('DONE',flush=True)

if __name__=='__main__':main()
