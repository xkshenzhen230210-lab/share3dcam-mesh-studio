import unittest
import numpy as np

from wall_segmentation import detect_walls, assign_points


def surface(x0=0., x1=3., y=0., step=.035):
    x,z=np.meshgrid(np.arange(x0,x1+step/2,step),np.arange(0,2.8,step))
    return np.column_stack((x.ravel(),np.full(x.size,y),z.ravel()))


class SegmentationTests(unittest.TestCase):
    def test_separates_disconnected_coplanar_surfaces_and_floor(self):
        a,b=surface(),surface(5,8)
        x,y=np.meshgrid(np.arange(0,8,.07),np.arange(0,4,.07))
        floor=np.column_stack((x.ravel(),y.ravel(),np.zeros(x.size)))
        xyz=np.vstack((a,b,floor))
        walls,limited=detect_walls(xyz)
        self.assertEqual(len(walls),2)
        self.assertFalse(limited)
        labels=assign_points(xyz,walls)[0]
        self.assertGreater(np.mean(labels[:len(a)]>=0),.98)
        self.assertGreater(np.mean(labels[len(a):len(a)+len(b)]>=0),.98)
        self.assertNotEqual(np.bincount(labels[:len(a)]+1).argmax(),np.bincount(labels[len(a):len(a)+len(b)]+1).argmax())
        self.assertGreater(np.mean(labels[len(a)+len(b):]<0),.9)

    def test_parallel_faces_remain_distinct_and_ambiguous_points_unassigned(self):
        a,b=surface(y=0),surface(y=.24)
        walls,_=detect_walls(np.vstack((a,b)))
        self.assertEqual(len(walls),2)
        labels,_=assign_points(np.vstack((a,b)),walls)
        self.assertTrue(np.all(labels>=0))
        labels,ambiguous=assign_points(np.array([[1.5,.12,1.5]]),walls)
        self.assertEqual(labels[0],-1)
        self.assertTrue(ambiguous[0])

    def test_preserves_bump_points_independent_of_acceptance_tolerance(self):
        xyz=surface();xyz[1000:1100,1]=.03
        walls,_=detect_walls(xyz)
        self.assertEqual(len(walls),1)
        labels,_=assign_points(xyz,walls)
        self.assertTrue(np.all(labels[1000:1100]>=0))

    def test_floor_only_and_sparse_data_have_no_walls(self):
        plane=surface()[:,[0,2,1]]
        self.assertEqual(detect_walls(plane)[0],[])
        self.assertEqual(detect_walls(np.array([[0,0,0],[1,1,1]]))[0],[])


if __name__=='__main__': unittest.main()
