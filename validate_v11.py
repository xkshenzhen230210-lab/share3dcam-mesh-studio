"""Real data regression: read complete inputs and export a bounded mesh section."""
import json,time,traceback,sys
from pathlib import Path
from converter import convert,Control,write_json

root=Path(__file__).parent
sample=Path(r'V:\给泽强\2.7版本\mesh\2.7.5新\藏经阁')
output=root/'validation'/('v11_'+time.strftime('%Y%m%d_%H%M%S'));output.mkdir(parents=True)
box=[-20,-10,-15,-10,0,5]
summary={'clip_box':box,'results':[]}
for kind in (sys.argv[1:] or ('stl','ply','glb','obj','osgb','3dtiles')):
    source=sample/kind/('Model.'+kind) if kind!='3dtiles' else root/'validation/tile_input/tileset.json'
    try:
        started=time.time();print('START',kind,str(source),flush=True)
        report=convert(source,output/kind,'both',Control(),clip_box=box if kind!='3dtiles' else None)
        summary['results'].append({'format':kind,'source':str(source),'seconds':round(time.time()-started,2),'triangles':report['obj_triangles'],'bounds':report.get('obj_bounds'),'state':'passed'})
    except Exception as e:
        traceback.print_exc();summary['results'].append({'format':kind,'state':'failed','error':str(e)})
    write_json(output/'summary.json',summary);print('RESULT',summary['results'][-1],flush=True)
print('OUTPUT',output,flush=True)
