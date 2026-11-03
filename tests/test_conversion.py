import json
import shutil
import tempfile
import struct
import unittest
from pathlib import Path
from converter import convert,Control,RUNTIME
from test_gltf import triangle


class ConversionTests(unittest.TestCase):
    def test_obj_indices_across_multiple_nodes(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);p=root/'input/model.glb';p.parent.mkdir();triangle(p)
            data=p.read_bytes();length=struct.unpack_from('<I',data,12)[0]
            doc=json.loads(data[20:20+length]);doc['nodes'].append({'mesh':0,'translation':[10,0,0]});doc['scenes'][0]['nodes']=[0,1]
            payload=json.dumps(doc).encode();payload+=b' '*((-len(payload))%4);binary=data[20+length:]
            p.write_bytes(struct.pack('<5I',0x46546c67,2,20+len(payload)+len(binary),len(payload),0x4e4f534a)+payload+binary)
            out=root/'out';report=convert(p,out,'obj',Control(lambda *args:None))
            self.assertEqual(report['obj_triangles'],2)
            text=(out/'obj/Model.obj').read_text()
            self.assertIn('f 1/1 2/2 3/3',text);self.assertIn('f 4/4 5/5 6/6',text)
            self.assertFalse((out/'osgb').exists())

    def test_obj_and_osgb_round_trip(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);p=root/'input/model.glb';p.parent.mkdir();triangle(p)
            out=root/'output';report=convert(p,out,'both',Control(lambda *args:None))
            self.assertEqual(report['obj_triangles'],1)
            self.assertEqual(report['obj_vertices'],3)
            obj=(out/'obj/Model.obj').read_text()
            self.assertIn('f 1/1 2/2 3/3',obj)
            leaf=next((out/'osgb/Block_0').glob('*Part*.osgb'))
            shutil.copy2(leaf,root/'check.osgb')
            info=json.loads(Control().run([RUNTIME/'mesh_writer.exe','inspect','check.osgb'],root))
            self.assertEqual(info['triangles'],1)
            self.assertEqual(info['bounds'],[[1,-3,2],[2,-3,3]])

    def test_nonempty_output_is_preserved(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);p=root/'input/model.glb';p.parent.mkdir();triangle(p)
            out=root/'output';out.mkdir();(out/'precious.txt').write_text('keep')
            with self.assertRaises(ValueError):convert(p,out,'obj',Control(lambda *args:None))
            self.assertEqual((out/'precious.txt').read_text(),'keep')

    def test_cancel_does_not_claim_success(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);p=root/'input/model.glb';p.parent.mkdir();triangle(p)
            c=Control(lambda *args:None)
            def stop(message,percent):
                if '[' in message:c.event.set()
            c.callback=stop
            with self.assertRaises(Exception):convert(p,root/'out','obj',c)
            self.assertEqual(json.loads((root/'out/mesh_result.json').read_text(encoding='utf-8'))['state'],'cancelled')
