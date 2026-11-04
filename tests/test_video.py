import math
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from converter import Control, Cancelled
from video import validate_keyframes, camera_at, sample_frames, render_video


def key(time, eye=(0,-10,0), center=(0,0,0), up=(0,0,1)):
    return dict(time=time,eye=list(eye),center=list(center),up=list(up),fovy=35)


class VideoTests(unittest.TestCase):
    def test_endpoints_and_midpoint_of_half_orbit_remain_valid(self):
        keys=validate_keyframes([key(0),key(2,(0,10,0))])
        self.assertEqual(camera_at(keys,0),{k:v for k,v in keys[0].items() if k!='time'})
        self.assertEqual(camera_at(keys,2),{k:v for k,v in keys[1].items() if k!='time'})
        middle=camera_at(keys,1)
        distance=math.sqrt(sum((a-b)**2 for a,b in zip(middle['eye'],middle['center'])))
        self.assertAlmostEqual(distance,10)
        self.assertAlmostEqual(abs(middle['eye'][0]),10)
        self.assertAlmostEqual(sum(middle['up'][i]*(middle['center'][i]-middle['eye'][i]) for i in range(3)),0)

    def test_interpolation_is_deterministic_and_clamps_to_endpoints(self):
        keys=validate_keyframes([key(0),key(1,(10,-10,5))])
        self.assertEqual(camera_at(keys,.3),camera_at(keys,.3))
        self.assertEqual(camera_at(keys,-1),camera_at(keys,0))
        self.assertEqual(camera_at(keys,2),camera_at(keys,1))

    def test_bad_poses_and_timing_are_rejected(self):
        for keys in ([key(0)], [key(1),key(2)], [key(0),key(0)],
                     [key(0),key(float('nan'))], [key(0),key(1801)],
                     [key(0),key(1,eye=(0,0,0))],
                     [key(0),key(1,up=(0,1,0))],
                     [key(0),key(1,eye=(1e308,0,0),center=(-1e308,0,0))],
                     [key(0),key(1,eye=(float('inf'),0,0))]):
            with self.subTest(keys=keys),self.assertRaises(ValueError):validate_keyframes(keys)

    def test_frame_count_duration_and_exact_final_pose(self):
        keys=validate_keyframes([key(0),key(2,(10,-10,5))])
        frames=sample_frames(keys,30)
        self.assertEqual(len(frames),60)
        self.assertEqual(frames[0],camera_at(keys,0))
        for name in ('eye','center','up'):
            for a,b in zip(frames[-1][name],camera_at(keys,2)[name]):self.assertAlmostEqual(a,b)
        with self.assertRaises(ValueError):sample_frames(keys,25)
        with self.assertRaises(ValueError):sample_frames([key(0),key(.001)],30)

    def test_preexisting_video_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as folder:
            output=Path(folder)/'existing.mp4';output.write_bytes(b'keep')
            with self.assertRaises(ValueError):
                render_video('missing.osgb',output,[key(0),key(1)])
            self.assertEqual(output.read_bytes(),b'keep')

    def test_pre_cancelled_render_creates_no_output(self):
        event=threading.Event();event.set()
        with tempfile.TemporaryDirectory() as folder:
            output=Path(folder)/'cancelled.mp4'
            with self.assertRaises(Cancelled):
                render_video('missing.osgb',output,[key(0),key(1)],control=Control(lambda *a:None,event))
            self.assertFalse(output.exists())

    def test_running_render_cancellation_stops_owned_children_and_publishes_nothing(self):
        import video
        actual_popen=subprocess.Popen;children=[]
        def start(command,**kwargs):
            if Path(command[0]).stem=='mesh_render':
                command=[sys.executable,'-c','import time;time.sleep(60)']
            child=actual_popen(command,**kwargs);children.append(child);return child
        with tempfile.TemporaryDirectory() as folder:
            source=Path(folder)/'model.osgb';source.write_bytes(b'fake renderer ignores this fixture')
            output=Path(folder)/'cancelled.mp4';control=Control(lambda *a:None)
            timer=threading.Timer(.5,control.event.set);timer.start()
            try:
                with patch.object(video.subprocess,'Popen',side_effect=start):
                    with self.assertRaises(Cancelled):render_video(source,output,[key(0),key(1)],control=control)
            finally:timer.cancel();timer.join()
            self.assertEqual(len(children),2)
            self.assertTrue(all(child.poll() is not None for child in children))
            self.assertFalse(output.exists())
            self.assertFalse(list(Path(folder).glob('.share_video_*')))

    def test_renderer_crash_cannot_publish_partial_mp4(self):
        import video
        actual_popen=subprocess.Popen
        def start(command,**kwargs):
            if Path(command[0]).stem=='mesh_render':
                command=[sys.executable,'-c',"import sys;sys.stderr.write('simulated renderer failure');sys.exit(17)"]
            return actual_popen(command,**kwargs)
        with tempfile.TemporaryDirectory() as folder:
            source=Path(folder)/'model.osgb';source.write_bytes(b'fake renderer ignores this fixture')
            output=Path(folder)/'failed.mp4'
            with patch.object(video.subprocess,'Popen',side_effect=start):
                with self.assertRaises(RuntimeError):render_video(source,output,[key(0),key(1)],control=Control(lambda *a:None))
            self.assertFalse(output.exists())
            self.assertFalse(list(Path(folder).glob('.share_video_*')))
