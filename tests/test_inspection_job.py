import os
from pathlib import Path
import tempfile
import threading
import unittest

import numpy as np

from auto_wall_panel import zone_camera
from converter import Control, Cancelled
from inspection_job import inspect_isolated
from tests.test_wall_flatness import write_las
from tests.test_wall_segmentation import surface


class InspectionJobTests(unittest.TestCase):
    def test_worker_delivers_complete_report_with_unicode_paths(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);source=root/'原始扫描.las';write_las(source,surface())
            report=inspect_isolated(source,root/'完整报告',dict(tolerance_mm=3),Control(lambda *_:None))
            self.assertEqual(report['state'],'succeeded')
            self.assertEqual(report['tolerance_mm'],3)
            self.assertEqual(report['output'],str((root/'完整报告').resolve()))
            self.assertTrue((root/'完整报告/墙面平整度报告.pdf').is_file())
            self.assertFalse(list(root.glob('.inspection-*')))

    def test_cancel_terminates_worker_without_publishing(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);source=root/'source.las';write_las(source,surface())
            event=threading.Event()
            def progress(*_):event.set()
            with self.assertRaises(Cancelled):
                inspect_isolated(source,root/'canceled',control=Control(progress,event))
            self.assertFalse((root/'canceled').exists())
            self.assertFalse(list(root.glob('.inspection-*')))

    def test_changed_source_is_never_published(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);source=root/'source.las';write_las(source,surface())
            touched=False
            def progress(*_):
                nonlocal touched
                if not touched:
                    stat=source.stat();os.utime(source,ns=(stat.st_atime_ns,stat.st_mtime_ns+1_000_000_000));touched=True
            with self.assertRaisesRegex((RuntimeError,ValueError),'Source changed'):
                inspect_isolated(source,root/'changed',control=Control(progress))
            self.assertTrue(touched)
            self.assertFalse((root/'changed').exists())

    def test_zone_camera_respects_shared_plane_and_source_units(self):
        for unit,factor in [('m',1.),('mm',1000.)]:
            wall=dict(plane_origin=[10*factor,20*factor,0],centroid=[11*factor,20.01*factor,1*factor],
                      normal=[0,1,0],u=[1,0,0],v=[0,0,1],uv_bounds=[[0,0],[4,3]])
            zone=dict(uv_bounds=[[2,1],[4,3]])
            camera=zone_camera(wall,zone,unit,16/9)
            np.testing.assert_allclose(camera['center'],np.array([13,20.01,2])*factor)
            eye=np.array(camera['eye']);center=np.array(camera['center'])
            self.assertGreater(eye[1],center[1])
            self.assertAlmostEqual((eye-center)[0],0)
            self.assertAlmostEqual(np.dot(camera['up'],wall['normal']),0)


if __name__=='__main__':unittest.main()
