import json
from pathlib import Path
import tempfile
import unittest
from converter import convert,Control
from supervisor import convert_isolated


class PointPipelineTests(unittest.TestCase):
    def test_isolated_original_crop_is_published_with_valid_paths(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);src=root/'input/cloud.ply';src.parent.mkdir()
            src.write_bytes(b'ply\nformat ascii 1.0\nelement vertex 2\nproperty float x\nproperty float y\nproperty float z\nend_header\n0 0 0\n10 10 10\n')
            report=convert_isolated(src,root/'cropped','source',Control(lambda *a:None),clip_box=[-1,-1,-1,1,1,1])
            self.assertEqual(report['count'],1)
            self.assertEqual(report['quality']['state'],'passed')
            output=Path(report['output']);self.assertTrue(output.is_file())
            self.assertEqual(output.parent,(root/'cropped').resolve())
            details=json.loads((root/'cropped/point_result.json').read_text(encoding='utf-8'))
            self.assertEqual(Path(details['output']),output)

    def test_point_cache_and_mesh_format_guard(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);src=root/'input/cloud.ply';src.parent.mkdir()
            src.write_bytes(b'ply\nformat ascii 1.0\nelement vertex 1\nproperty float x\nproperty float y\nproperty float z\nend_header\n1 2 3\n')
            report=convert(src,root/'preview','pointcache',Control(lambda *a:None),preview=True)
            self.assertEqual(report['state'],'succeeded')
            self.assertTrue((root/'preview/model.spoints').exists())
            with self.assertRaisesRegex(ValueError,'Source|原格式'):
                convert(src,root/'obj','obj',Control(lambda *a:None))
