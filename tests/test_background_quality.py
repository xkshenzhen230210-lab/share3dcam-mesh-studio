import json
import struct
import tempfile
import unittest
from pathlib import Path
from converter import Control, convert
from test_gltf import triangle
from PIL import Image
from io import StringIO
import numpy as np
from quality import compare_records, QualityError


def textured_triangle(path):
    triangle(path);data=path.read_bytes();size=struct.unpack_from('<I',data,12)[0]
    doc=json.loads(data[20:20+size]);doc['images']=[{'uri':'red.png'}];doc['textures']=[{'source':0}]
    doc['materials']=[{'pbrMetallicRoughness':{'baseColorTexture':{'index':0}}}]
    doc['meshes'][0]['primitives'][0]['material']=0
    payload=json.dumps(doc).encode();payload+=b' '*((-len(payload))%4);binary=data[20+size:]
    path.write_bytes(struct.pack('<5I',0x46546c67,2,20+len(payload)+len(binary),len(payload),0x4e4f534a)+payload+binary)
    Image.new('RGB',(2,2),'red').save(path.parent/'red.png')


class FaultControl(Control):
    def __init__(self, permanent=False):
        super().__init__(lambda *a: None)
        self.permanent=permanent
        self.writes=0

    def run(self, command, cwd):
        result=super().run(command,cwd)
        if 'write' in command and (Path(cwd)/'part.obj').is_file():
            self.writes+=1
            if self.permanent or self.writes==1:
                p=Path(cwd)/'part.obj'
                p.write_text(p.read_text().replace('f 1/1','f 99/1'),encoding='utf-8')
        return result


class BackgroundQualityTests(unittest.TestCase):
    def test_invalid_record_boundaries_and_normal_index_syntax_are_rejected(self):
        control=Control(lambda *a: None)
        with self.assertRaises(QualityError):
            compare_records(StringIO('v 1 2\nv 3 4 5 6\n'),'v',np.array([[1.,2,3],[4,5,6]]),control)
        with self.assertRaises(QualityError):
            compare_records(StringIO('f 1/1/ 2/2/ 3/3/\n'),'f',np.array([[1,1,2,2,3,3]],dtype=np.int64),control,2,2)

    def test_corrupt_native_output_is_regenerated_automatically(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);source=root/'input/model.glb';source.parent.mkdir();triangle(source)
            control=FaultControl()
            report=convert(source,root/'out','obj',control)
            self.assertEqual(control.writes,2)
            self.assertEqual(report['quality']['state'],'passed')
            self.assertGreaterEqual(report['quality']['repairs'],1)
            self.assertNotIn('99/',(root/'out/obj/Model.obj').read_text())

    def test_persistent_damage_never_reports_success(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);source=root/'input/model.glb';source.parent.mkdir();triangle(source)
            with self.assertRaises(Exception):convert(source,root/'out','obj',FaultControl(True))
            result=json.loads((root/'out/mesh_result.json').read_text(encoding='utf-8'))
            self.assertEqual(result['state'],'failed')
            self.assertEqual(result['data'],{})

    def test_missing_material_and_texture_are_restored_in_background(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);source=root/'input/model.glb';source.parent.mkdir();textured_triangle(source)
            damaged=False
            def corrupt(message,percent):
                nonlocal damaged
                if '后台检查' in message and not damaged:
                    damaged=True
                    (root/'out/obj/Model.mtl').write_text('broken')
                    for p in (root/'out/obj').glob('tex_*'):p.write_bytes(b'broken')
            report=convert(source,root/'out','obj',Control(corrupt))
            self.assertTrue(damaged)
            self.assertEqual(report['quality']['state'],'passed')
            self.assertGreaterEqual(report['quality']['repairs'],2)

    def test_cancellation_during_quality_check_never_reports_success(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);source=root/'input/model.glb';source.parent.mkdir();triangle(source)
            control=Control(lambda *a: None)
            def cancel(message,percent):
                if '后台检查' in message:control.event.set()
            control.callback=cancel
            with self.assertRaises(Exception):convert(source,root/'out','obj',control)
            result=json.loads((root/'out/mesh_result.json').read_text(encoding='utf-8'))
            self.assertEqual(result['state'],'cancelled')

