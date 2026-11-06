import json
import subprocess
import tempfile
import unittest
from pathlib import Path

import laspy
import numpy as np

from clipping import clip_primitive
from converter import Control, RUNTIME, convert
from point_data import crop_points, prepare_points
from spatial_frame import ClipBox, footprint_hull
from wall_flatness import analyze_wall


class AlignmentTests(unittest.TestCase):
    def volume(self, angle=35, origin=(500000, 3000000, 20)):
        return ClipBox(dict(bounds=[0, -2, -1, 2, 2, 1], origin=origin, yaw_degrees=angle))

    def test_rotated_triangle_keeps_world_positions_and_interpolated_uv(self):
        volume=self.volume();local=np.array([[-1.,0,0],[1.,0,0],[1.,1,0]])
        part=dict(positions=volume.world(local), indices=np.array([[0,1,2]]),
                  uv=np.array([[0.,0],[1.,0],[1.,1]]),normals=None)
        result=clip_primitive(part,volume)
        self.assertEqual(len(result['indices']),2)
        np.testing.assert_allclose(volume.local(result['positions'])[:,0],(result['uv'][:,0]-.5)*2,atol=1e-8)
        self.assertGreaterEqual(volume.local(result['positions'])[:,0].min(),-1e-8)
        self.assertGreater(result['positions'][:,1].min(),2999990)

    def test_full_inside_vertices_stay_exact_and_broad_phase_contains_all_corners(self):
        volume=self.volume();p=volume.world([[.1,0,0],[1,0,0],[1,1,0]])
        part=dict(positions=p,indices=np.array([[0,1,2]]),uv=None,normals=None)
        self.assertIs(clip_primitive(part,volume),part)
        broad=ClipBox(volume.world_bounds())
        self.assertTrue(broad.contains(volume.world([[x,y,z] for x in (0,2) for y in (-2,2) for z in (-1,1)])).all())

    def test_las_oriented_crop_preserves_original_record_bytes(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);source=root/'source.las';volume=self.volume()
            las=laspy.LasData(laspy.LasHeader(point_format=3,version='1.2'))
            las.header.scales=np.array([1e-5]*3);las.header.offsets=volume.origin
            xyz=volume.world([[.5,0,0],[1,1,0],[-.5,0,0],[1,3,0]])
            las.x,las.y,las.z=xyz.T;las.red=np.array([12,23,34,45],dtype='u2');las.intensity=np.arange(4,dtype='u2')
            las.write(source);before=source.read_bytes();original=laspy.read(source)
            result=crop_points(source,root/'out',volume,Control(lambda *a:None))
            actual=laspy.read(result['output'])
            self.assertEqual(actual.points.array.tobytes(),original.points[:2].array.tobytes())
            self.assertEqual(source.read_bytes(),before)
            manifest=json.loads(prepare_points(source,root/'cache',Control(lambda *a:None)).read_text())
            hull=np.array(manifest['footprint']);self.assertEqual(len(hull),4)

    def test_native_alignment_for_rotated_rectangles_and_large_coordinates(self):
        for angle in (-78,-35,0,23,89):
            volume=self.volume(angle)
            corners=volume.world([[x,y,z] for x in (-5,5) for y in (-2,2) for z in (0,3)])
            with tempfile.TemporaryDirectory() as d:
                path=Path(d)/'shape.json';path.write_text(json.dumps(corners.tolist()))
                result=subprocess.run([str(RUNTIME/'mesh_viewer.exe'),'--test-alignment',str(path)],capture_output=True,text=True)
                self.assertEqual(result.returncode,0,result.stderr)
                value=json.loads(result.stdout)
                self.assertAlmostEqual(value['frame']['yaw_degrees'],angle,places=6)
                extent=np.array(value['bounds'][3:])-value['bounds'][:3]
                np.testing.assert_allclose(extent,[10,4,3],atol=1e-6)

    def test_native_obj_broad_phase_and_precise_oriented_cut(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);source=root/'in/model.obj';source.parent.mkdir();volume=self.volume()
            points=volume.world([[-1,0,0],[1,0,0],[1,1,0]])
            source.write_text(''.join('v '+' '.join(map(str,p))+'\n' for p in points)+'f 1 2 3\n')
            report=convert(source,root/'out','obj',Control(lambda *a:None),clip_box=volume)
            self.assertEqual(report['obj_triangles'],2)
            vertices=np.array([[float(x) for x in line.split()[1:]] for line in (root/'out/obj/Model.obj').read_text().splitlines() if line.startswith('v ')])
            self.assertGreaterEqual(volume.local(vertices)[:,0].min(),-1e-7)

    def test_invalid_frames_and_degenerate_hulls(self):
        for origin,yaw in (([0,0],0),([0,0,float('nan')],0),([0,0,0],float('inf'))):
            with self.assertRaises(ValueError):ClipBox(dict(bounds=[0,0,0,1,1,1],origin=origin,yaw_degrees=yaw))
        np.testing.assert_array_equal(footprint_hull([[1,1],[2,2],[3,3]]),[[1,1],[3,3]])

    def test_selected_wall_analysis_uses_rotated_volume(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);source=root/'wall.las';volume=self.volume()
            local=np.array([[x,y,z] for x in np.linspace(.1,1.9,15) for z in np.linspace(-.9,.9,15) for y in (0,3)])
            las=laspy.LasData(laspy.LasHeader(point_format=3,version='1.2'))
            las.header.scales=np.array([1e-6]*3);las.header.offsets=volume.origin
            las.x,las.y,las.z=volume.world(local).T;las.write(source)
            report=analyze_wall(source,root/'report',volume,control=Control(lambda *a:None))
            self.assertEqual(report['count'],225)
            self.assertEqual(report['clip_box'],volume.tolist())
