import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

import numpy as np

from auto_wall_panel import zone_camera
from converter import Control, Cancelled
from inspection_job import inspect_isolated
from tests.test_wall_flatness import write_las
from tests.test_wall_segmentation import surface


class InspectionJobTests(unittest.TestCase):
    def test_failed_report_delivery_keeps_complete_local_result(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary).resolve();source=root/'source.las';write_las(source,surface())
            with patch('inspection_job.local_root',return_value=root/'local'),patch('inspection_job.publish_report',side_effect=PermissionError('share unavailable')):
                report=inspect_isolated(source,root/'share/report',control=Control(lambda *_:None))
            local=Path(report['output'])
            self.assertTrue(local.is_relative_to(root/'local'))
            self.assertEqual(report['delivery'],'local_fallback')
            self.assertEqual(report['requested_output'],str(root/'share/report'))
            self.assertTrue((local/'墙面平整度报告.pdf').is_file())
            self.assertFalse((root/'share/report').exists())

    def test_report_worker_does_not_create_private_temporary_directory_on_output_share(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary).resolve();source=root/'source.las';write_las(source,surface())
            real_temporary_directory=tempfile.TemporaryDirectory
            def share_rejects_private_directory(*args,**kwargs):
                if kwargs.get('dir') and Path(kwargs['dir'])==root:
                    raise PermissionError('Shared drive rejects private temporary-directory ACL')
                return real_temporary_directory(*args,**kwargs)
            with patch('inspection_job.tempfile.TemporaryDirectory',side_effect=share_rejects_private_directory):
                report=inspect_isolated(source,root/'report',control=Control(lambda *_:None))
            self.assertTrue((Path(report['output'])/'墙面平整度报告.pdf').is_file())
            self.assertEqual(Path(report['output']),root/'report')

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
