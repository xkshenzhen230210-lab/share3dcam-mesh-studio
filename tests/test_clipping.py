import unittest
import numpy as np
from clipping import clip_primitive

class ClipTests(unittest.TestCase):
    def part(self):
        return {'positions':np.array([[-1.,0,0],[1.,0,0],[1.,1,0]]),'indices':np.array([[0,1,2]],dtype=np.uint32),
                'uv':np.array([[0.,0],[1.,0],[1.,1]]),'normals':None,'color':[1,1,1,1]}
    def test_crossing_triangle_is_split_and_uv_interpolated(self):
        p=clip_primitive(self.part(),[0,-2,-1,2,2,1])
        self.assertEqual(len(p['indices']),2)
        self.assertTrue((p['positions'][:,0]>=0).all())
        boundary=p['positions'][:,0]==0
        np.testing.assert_allclose(p['uv'][boundary,0],.5)
    def test_outside_removed(self):
        p=clip_primitive(self.part(),[3,3,3,4,4,4]);self.assertEqual(len(p['indices']),0)
    def test_inside_unchanged(self):
        p=self.part();self.assertIs(clip_primitive(p,[-2,-2,-2,2,2,2]),p)
    def test_invalid_box_rejected(self):
        with self.assertRaises(ValueError):clip_primitive(self.part(),[2,0,0,1,1,1])
