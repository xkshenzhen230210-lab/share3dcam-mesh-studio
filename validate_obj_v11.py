"""Validate the final bulk OBJ parser while another native read is running."""
from pathlib import Path
import tempfile,time
from converter import Control,write_json,_convert
from formats import mesh_tree
root=Path(__file__).parent
source=Path(r'V:\给泽强\2.7版本\mesh\2.7.5新\藏经阁\obj\Model.obj')
output=root/'validation'/('v11_obj_'+time.strftime('%Y%m%d_%H%M%S'))
control=Control();started=time.time()
with tempfile.TemporaryDirectory(prefix='obj_verified_') as temp:
    work=Path(temp);write_json(work/'job.json',{'source':str(source),'output':str(work/'mesh')})
    control.run([root/'build/native/Release/mesh_reader.exe','job.json'],work)
    print('OBJ parsed in',time.time()-started,flush=True)
    tree=mesh_tree(work/'mesh/model.mesh')
    report=_convert(source,output,'both',control,[-20,-10,-15,-10,0,5],False,(tree,source,'obj'))
    print('RESULT',report['obj_triangles'],report['obj_bounds'],time.time()-started,flush=True)
