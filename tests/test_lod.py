import json
import shutil
import tempfile
import unittest
from pathlib import Path
from converter import convert,Control,RUNTIME
from test_gltf import triangle


class LODRoundTripTests(unittest.TestCase):
    def test_lod_child_pages_keep_coarse_geometry_and_relative_references(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);src=root/'in';(src/'Block_0').mkdir(parents=True)
            for name in ('a','b','c'):triangle(src/'Block_0'/f'{name}.glb')
            bv={'sphere':[0,0,0,10]}
            node={'boundingVolume':bv,'geometricError':10,'content':{'uri':'Block_0/a.glb'},'children':[
                {'boundingVolume':bv,'geometricError':5,'content':{'uri':'Block_0/b.glb'},'children':[
                    {'boundingVolume':bv,'geometricError':0,'content':{'uri':'Block_0/c.glb'}}]}]}
            p=src/'tileset.json';p.write_text(json.dumps({'asset':{'version':'1.1'},'root':node}))
            out=root/'out';convert(p,out,'both',Control(lambda *args:None))
            # The final OBJ contains one triangle, not all three LODs.
            report=json.loads((out/'conversion_report.json').read_text(encoding='utf-8'))
            self.assertEqual(report['obj_triangles'],1)
            for file in (out/'osgb').rglob('*.osgb'):
                shutil.copy2(file,root/'check.osgb')
                info=json.loads(Control().run([RUNTIME/'mesh_writer.exe','inspect','check.osgb'],root))
                self.assertEqual(info['triangles'],1)
                for ref in info['references']:
                    self.assertFalse(Path(ref).is_absolute())
                    self.assertTrue((file.parent/ref).is_file(),(file,ref))
