import collections
import json
import struct
from pathlib import Path
from gltf import Glb
from tiles import load_tiles,flatten,obj_nodes

SOURCE=Path(r'V:\给泽强\2.7版本\mesh\2.7.5新\藏经阁')
tree=load_tiles(SOURCE/'3dtiles/tileset.json')
stats={'tile_files':0,'tile_triangles_all_lods':0,'tile_triangles_finest':0,'texture_mime_counts':collections.Counter(),
       'required_extensions':collections.Counter(),'glb_triangles':0,'glb_vertices':0}
selected=set(obj_nodes(tree))
for node in flatten(tree):
    if not node.source:continue
    with Glb(node.source) as glb:
        j=glb.doc
        tris=sum(j['accessors'][p['indices']]['count']//3 for m in j['meshes'] for p in m['primitives'])
        stats['tile_files']+=1;stats['tile_triangles_all_lods']+=tris
        if node in selected:stats['tile_triangles_finest']+=tris
        stats['texture_mime_counts'].update(i['mimeType'] for i in j['images'])
        stats['required_extensions'].update(j.get('extensionsRequired',[]))
with Glb(SOURCE/'glb/Model.glb') as glb:
    j=glb.doc
    stats['glb_triangles']=sum(j['accessors'][p['indices']]['count']//3 for m in j['meshes'] for p in m['primitives'])
    stats['glb_vertices']=sum(j['accessors'][p['attributes']['POSITION']]['count'] for m in j['meshes'] for p in m['primitives'])
    stats['glb_images']=len(j['images'])
Path('validation/sample_inventory.json').write_text(json.dumps(stats,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(stats,ensure_ascii=False,indent=2))
