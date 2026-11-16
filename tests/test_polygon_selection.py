import unittest
import numpy as np
from spatial_frame import ClipBox
from clipping import clip_primitive
from polygon_selection import validate_polygon,triangulate


class PolygonTests(unittest.TestCase):
    def test_internal_diagonal_does_not_duplicate_vertical_faces(self):
        box=ClipBox(dict(bounds=[0,0,-1,2,2,2],polygon=[[0,0],[2,0],[2,2],[0,2]]))
        p=np.array([[0.,2,0],[2,0,0],[1,1,1]])
        part=dict(positions=p,uv=None,normals=None,indices=np.array([[0,1,2]]))
        result=clip_primitive(part,box)
        self.assertEqual(len(result['indices']),1)
    def volume(self):
        return ClipBox(dict(bounds=[0,0,-1,3,3,1],origin=[500000,3000000,20],yaw_degrees=35,
                            polygon=[[0,0],[3,0],[3,1],[1,1],[1,3],[0,3]]))

    def test_concave_polygon_boundary_and_frame(self):
        box=self.volume()
        np.testing.assert_array_equal(box.contains(box.world([[.5,2,0],[2,2,0],[1,2,0],[3,.5,0],[.5,.5,2]])),[True,False,True,True,False])
        self.assertEqual(ClipBox(box.tolist()).tolist(),box.tolist())

    def test_mesh_clips_notch_and_preserves_area_and_uv(self):
        box=self.volume();xy=np.array([[0.,0],[3,0],[3,3],[0,3]])
        xyz=box.world(np.c_[xy,np.zeros(4)])
        part=dict(positions=xyz,uv=xy/3,normals=None,indices=np.array([[0,1,2],[0,2,3]]))
        result=clip_primitive(part,box);triangles=result['positions'][result['indices']]
        area=np.linalg.norm(np.cross(triangles[:,1]-triangles[:,0],triangles[:,2]-triangles[:,0]),axis=1).sum()/2
        self.assertAlmostEqual(area,5,places=7)
        np.testing.assert_allclose(box.local(result['positions'])[:,:2],result['uv']*3,atol=1e-8)
        self.assertTrue(box.contains(triangles.mean(axis=1)).all())

    def test_invalid_polygon_rejected_and_clockwise_collinear_accepted(self):
        for p in ([[0,0],[2,2],[0,2],[2,0]],[[0,0],[1,0],[2,0]],[[0,0],[1,0],[1,0],[0,1]]):
            with self.assertRaises(ValueError):validate_polygon(p)
        p=validate_polygon([[0,0],[0,2],[2,2],[2,0],[1,0]])
        self.assertEqual(len(triangulate(p)),2)
