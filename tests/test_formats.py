import json
import struct
import tempfile
import unittest
from pathlib import Path
import numpy as np
from PIL import Image
from formats import Mesh
from converter import convert,Control,RUNTIME,write_json

class FormatTests(unittest.TestCase):
    def test_obj_alternating_materials_are_batched_and_negative_indices_preserved(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);p=root/'model.obj'
            p.write_text('v 0 0 0\nv 1 0 0\nv 0 1 0\nvt 0 0\nvt 1 0\nvt 0 1\n'+''.join(f'usemtl mat{i%2}\nf -3/-3 -2/-2 -1/-1\n' for i in range(1000)))
            write_json(root/'job.json',{'source':str(p),'output':str(root/'mesh')})
            Control(lambda *a:None).run([RUNTIME/'mesh_reader.exe','job.json'],root)
            doc=json.loads((root/'mesh/model.mesh').read_text())
            self.assertEqual(len(doc['parts']),2)
            with Mesh(root/'mesh/model.mesh') as mesh:
                parts=list(mesh.primitives());self.assertEqual(sum(len(p['indices']) for p in parts),1000)
                np.testing.assert_allclose(parts[0]['positions'][:3],[[0,0,0],[1,0,0],[0,1,0]])
                np.testing.assert_allclose(parts[0]['uv'][:3],[[0,0],[1,0],[0,1]])
    def test_stl_binary_and_clipped_export(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'input/model.stl';p.parent.mkdir()
            p.write_bytes(bytes(80)+struct.pack('<I12fH',1,0,0,1,-1,0,0,1,0,0,1,1,0,0))
            r=convert(p,Path(d)/'out','both',Control(lambda *a:None),clip_box=[0,-2,-1,2,2,1])
            self.assertEqual(r['obj_triangles'],2);self.assertEqual(r['obj_bounds'][0][0],0)
    def test_textured_ply_preserves_face_uv(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'input/model.ply';p.parent.mkdir();Image.new('RGB',(2,2),(255,0,0)).save(p.parent/'red.png')
            header='ply\nformat binary_little_endian 1.0\ncomment TextureFile red.png\nelement vertex 3\nproperty float x\nproperty float y\nproperty float z\nelement face 1\nproperty list uchar uint vertex_indices\nproperty list uchar float texcoord\nproperty int texnumber\nend_header\n'
            p.write_bytes(header.encode()+struct.pack('<9f',0,0,0,1,0,0,0,1,0)+struct.pack('<B3IB6fi',3,0,1,2,6,0,0,1,0,0,1,0))
            with Mesh(p) as m:
                part=next(m.primitives());np.testing.assert_allclose(part['uv'],[[0,0],[1,0],[0,1]])
            r=convert(p,Path(d)/'out','both',Control(lambda *a:None));self.assertEqual(r['obj_triangles'],1);self.assertEqual(r['obj_materials'],1)
    def test_obj_native_reader_no_axis_rotation_and_osgb_paging(self):
        with tempfile.TemporaryDirectory(prefix='中文模型_') as d:
            p=Path(d)/'input/model.obj';p.parent.mkdir();p.write_text('v 1 2 3\nv 2 2 3\nv 1 3 3\nf 1 2 3\n')
            r=convert(p,Path(d)/'out','both',Control(lambda *a:None));self.assertEqual(r['obj_triangles'],1);self.assertEqual(r['obj_bounds'],[[1,2,3],[2,3,3]])
            r2=convert(Path(d)/'out/osgb/Model.osgb',Path(d)/'roundtrip','obj',Control(lambda *a:None));self.assertEqual(r2['obj_triangles'],1);self.assertEqual(r2['obj_bounds'],r['obj_bounds'])
    def test_empty_clip_fails_without_success_manifest(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'input/model.stl';p.parent.mkdir();p.write_bytes(bytes(80)+struct.pack('<I12fH',1,0,0,1,-1,0,0,1,0,0,1,1,0,0))
            with self.assertRaises(ValueError):convert(p,Path(d)/'out','both',Control(lambda *a:None),clip_box=[10,10,10,11,11,11])
            self.assertEqual(json.loads((Path(d)/'out/mesh_result.json').read_text(encoding='utf-8'))['state'],'failed')
