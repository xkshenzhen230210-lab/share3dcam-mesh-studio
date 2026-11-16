import json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np
from converter import Control
from point_data import prepare_points
from test_point_data import make_ply


class GaussianPreviewTests(unittest.TestCase):
    def test_preview_keeps_every_gaussian_and_its_original_opacity(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);source=root/'scene.ply'
            fields=[(n,'f4') for n in ['x','y','z','f_dc_0','f_dc_1','f_dc_2','opacity','scale_0','scale_1','scale_2','rot_0','rot_1','rot_2','rot_3']]
            records,_=make_ply(source,[(i*.001,0,0,0,0,0,-1,-2,-2,-2,1,0,0,0) for i in range(13)],fields)
            before=source.read_bytes()
            with patch('point_data.PREVIEW_LIMIT',4):
                path=prepare_points(source,root/'cache',Control(lambda *a:None),preview=True)
            doc=json.loads(path.read_text(encoding='utf-8'))
            self.assertEqual(doc['count'],len(records),'Dropping Gaussians changes accumulated opacity')
            self.assertEqual(doc['sample_stride'],1);self.assertFalse(doc['sampled'])
            packed=np.fromfile(path.parent/doc['data'],dtype='<f4').reshape(-1,doc['stride_floats'])
            np.testing.assert_allclose(packed[:,6],1/(1+np.exp(1)),atol=1e-7)
            self.assertEqual(source.read_bytes(),before)

    def test_sh0_cache_avoids_unused_spherical_harmonic_storage(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);fields=[(n,'f4') for n in ['x','y','z','f_dc_0','f_dc_1','f_dc_2','opacity','scale_0','scale_1','scale_2','rot_0','rot_1','rot_2','rot_3']]
            make_ply(root/'scene.ply',[(0,0,0,0,0,0,-1,-2,-2,-2,1,0,0,0)],fields)
            doc=json.loads(prepare_points(root/'scene.ply',root/'cache',Control(lambda *a:None)).read_text(encoding='utf-8'))
            self.assertEqual(doc['stride_floats'],14)
