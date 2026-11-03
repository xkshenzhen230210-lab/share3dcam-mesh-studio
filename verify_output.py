"""Re-open output OSGB files and check all page references without a viewer."""
import argparse
import json
import shutil
import tempfile
from pathlib import Path
from converter import Control,RUNTIME,write_json


def verify(folder):
    base=Path(folder).resolve();report=json.loads((base/'conversion_report.json').read_text(encoding='utf-8'))
    if report['state']!='succeeded':raise ValueError('Conversion did not succeed')
    result={'files':0,'vertices':0,'triangles':0,'textures':0,'references':0,'broken_references':[]}
    with tempfile.TemporaryDirectory(prefix='meshverify_') as temp:
        work=Path(temp)
        for file in sorted((base/'osgb').rglob('*.osgb')):
            shutil.copy2(file,work/'check.osgb')
            text=Control().run([RUNTIME/'mesh_writer.exe','inspect','check.osgb'],work)
            info=json.loads(text[text.find('{'):])
            result['files']+=1
            for key in ('vertices','triangles','textures'):result[key]+=info[key]
            for ref in info['references']:
                result['references']+=1
                if Path(ref).is_absolute() or not (file.parent/ref).is_file():result['broken_references'].append([str(file),ref])
            if result['files']%20==0:print('Verified',result['files'],flush=True)
    if result['broken_references']:raise ValueError(result['broken_references'])
    if report['input_kind']=='glb' and 'obj_triangles' in report:
        assert result['triangles']==report['obj_triangles'],result
        assert result['vertices']==report['obj_vertices'],result
    # MTL references must point to complete, nonempty files beside the OBJ.
    if (base/'obj/Model.mtl').is_file():
        refs=[line[7:].strip() for line in (base/'obj/Model.mtl').read_text(encoding='utf-8').splitlines() if line.startswith('map_Kd ')]
        for ref in refs:assert (base/'obj'/ref).stat().st_size>0,ref
        result['obj_texture_references']=len(refs)
    write_json(base/'verification.json',result)
    print(json.dumps(result,indent=2))
    return result

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('folder');args=parser.parse_args();verify(args.folder)
