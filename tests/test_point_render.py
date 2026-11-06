"""Pixel evidence for native anisotropic splats, ordering and clipping."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
import numpy as np
from converter import RUNTIME


class PointRenderTests(unittest.TestCase):
    def render(self, records, clip=None, failure=False):
        with tempfile.TemporaryDirectory() as folder:
            folder=Path(folder)
            np.asarray(records,dtype='<f4').tofile(folder/'points.bin')
            (folder/'model.spoints').write_text(json.dumps(dict(format='share3dcam-points',version=1,kind='gaussian',
                data='points.bin',count=len(records),origin=[0,0,0],bounds=[[-1,-1,-1],[1,1,1]],stride_floats=62,sh_degree=0)))
            pose=dict(eye=[0,-5,0],center=[0,0,0],up=[0,0,1],fovy=45)
            job=dict(source=str(folder/'model.spoints'),width=128,height=128,fps=30,frames=[pose],progress=str(folder/'progress.json'),clip_box=clip)
            (folder/'job.json').write_text(json.dumps(job))
            env=os.environ.copy();env['PATH']=str(RUNTIME)+os.pathsep+env.get('PATH','')
            env['OSG_LIBRARY_PATH']=str(RUNTIME/'osgPlugins-3.6.5')
            result=subprocess.run([str(RUNTIME/'mesh_render.exe'),'job.json'],cwd=folder,env=env,capture_output=True)
            if failure:
                self.assertNotEqual(result.returncode,0)
                self.assertEqual(result.stdout,b'')
                return result.stderr.decode(errors='replace')
            self.assertEqual(result.returncode,0,result.stderr.decode(errors='replace')[-3000:])
            return np.frombuffer(result.stdout,dtype=np.uint8).reshape(128,128,3)

    def test_hdr_color_is_blended_before_final_output_clamp(self):
        a=self.record([1,0,0]);a[6]=.2
        b=self.record([2,0,0]);b[6]=.2
        red_a=int(self.render([a])[64,64,0]);red_b=int(self.render([b])[64,64,0])
        self.assertGreater(red_b,red_a+35)

    def test_covariance_overflow_fails_before_output(self):
        record=self.record([1,0,0]);record[7:10]=[1e20]*3
        self.assertIn('covariance',self.render([record],failure=True))

    @staticmethod
    def record(color, y=0, rotation=(1,0,0,0)):
        return [0,y,0,*color,.9,.5,.05,.05,*rotation]+[0]*48

    def test_anisotropic_scale_and_rotation(self):
        image=self.render([self.record([1,0,0])]);mask=image[:,:,0]>80
        rows,cols=np.where(mask);self.assertGreater(np.ptp(cols),3*np.ptp(rows))
        image=self.render([self.record([1,0,0],rotation=(2**-.5,0,2**-.5,0))]);rows,cols=np.where(image[:,:,0]>80)
        self.assertGreater(np.ptp(rows),3*np.ptp(cols))

    def test_depth_order_and_center_clipping(self):
        # Deliberately input near red before far blue; rendering must reorder.
        image=self.render([self.record([1,0,0],-.2),self.record([0,0,1],.2)])
        center=image[64,64];self.assertGreater(int(center[0]),3*int(center[2]))
        empty=self.render([self.record([1,0,0])],[.1,-1,-1,1,1,1])
        self.assertLess(empty[:,:,0].max(),30)

    def test_rotated_box_keeps_centers_in_the_same_frame_as_source_crop(self):
        selection=dict(bounds=[.1,-1,-1,1,1,1],origin=[0,0,0],yaw_degrees=45)
        image=self.render([self.record([1,0,0]),self.record([0,0,1],.5)],selection)
        self.assertGreater(int(image[:,:,2].max()),100)
        self.assertLess(int(image[:,:,0].max()),30)

    def test_navigation_camera_basis(self):
        result=subprocess.run([str(RUNTIME/'mesh_viewer.exe'),'--test-navigation'],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)
        data=json.loads(result.stdout)
        np.testing.assert_allclose(data['forward'],[0,2,0])
        np.testing.assert_allclose(data['right'],[2,0,0])
        np.testing.assert_allclose(data['up'],[0,0,2])
        np.testing.assert_allclose(data['down'],[0,0,-2])
        self.assertAlmostEqual(np.linalg.norm(data['diagonal']),2)

    def render_camera_frames(self, records, poses, degree=0):
        """Exercise multiple poses in one renderer, including its update path."""
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            np.asarray(records, dtype='<f4').tofile(folder/'points.bin')
            (folder/'model.spoints').write_text(json.dumps(dict(
                format='share3dcam-points', version=1, kind='gaussian', data='points.bin',
                count=len(records), origin=[0, 0, 0], bounds=[[-5, -5, -5], [5, 5, 5]],
                stride_floats=62, sh_degree=degree)))
            (folder/'job.json').write_text(json.dumps(dict(
                source=str(folder/'model.spoints'), width=128, height=128, fps=30,
                frames=poses, progress=str(folder/'progress.json'))))
            env = os.environ.copy()
            env['PATH'] = str(RUNTIME) + os.pathsep + env.get('PATH', '')
            env['OSG_LIBRARY_PATH'] = str(RUNTIME/'osgPlugins-3.6.5')
            result = subprocess.run([str(RUNTIME/'mesh_render.exe'), 'job.json'],
                                    cwd=folder, env=env, capture_output=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr.decode(errors='replace')[-3000:])
            progress = json.loads((folder/'progress.json').read_text())
            self.assertEqual(progress['state'], 'succeeded')
            self.assertEqual(progress['frame'], len(poses))
            return np.frombuffer(result.stdout, dtype=np.uint8).reshape(len(poses), 128, 128, 3)

    def test_sh1_color_changes_with_view_direction(self):
        record = self.record([.5, .5, .5])
        record[7:10] = [.2, .2, .2]
        # The first non-DC SH basis is -C1*y; its red coefficient is one.
        record[14 + 3] = 1
        poses = [dict(eye=eye, center=[0, 0, 0], up=[0, 0, 1], fovy=45)
                 for eye in ([0, -5, 0], [0, 5, 0], [0, -5, 0])]
        images = self.render_camera_frames([record], poses, degree=1)
        dark, bright, returned = images[:, 64, 64].astype(int)
        self.assertGreater(bright[0]-dark[0], 180)
        np.testing.assert_allclose(dark[1:], bright[1:], atol=2)
        np.testing.assert_array_equal(dark, returned)

    def test_gaussian_outside_screen_center_still_contributes_visible_tail(self):
        record = self.record([1, 0, 0])
        # The right edge at depth five and fov45 is x=2.071. Center x=2.2
        # is outside, but sigma x=.5 leaves a substantial visible footprint.
        record[0] = 2.2
        pose = dict(eye=[0, -5, 0], center=[0, 0, 0], up=[0, 0, 1], fovy=45)
        image = self.render_camera_frames([record], [pose])[0]
        visible = image[:, -16:, 0] > 80
        self.assertGreater(int(visible.sum()), 20)
        self.assertLess(int(image[:, :32, 0].max()), 30)


if __name__=='__main__':unittest.main()
