"""Full Gaussian contributors stay intact while camera-independent work is reused."""
import json,os,subprocess,tempfile,unittest
from pathlib import Path
import numpy as np
from converter import RUNTIME


class GaussianResourceTests(unittest.TestCase):
    def render(self,degree,frames):
        with tempfile.TemporaryDirectory() as d:
            folder=Path(d);values=np.zeros((2,62),dtype='<f4')
            values[:,:14]=[[0,-.2,0,1,0,0,.8,.4,.1,.1,1,0,0,0],[0,.2,0,0,0,1,.8,.4,.1,.1,1,0,0,0]]
            values[:,14:17]=[.2,.3,.4];values[:,17:20]=[.6,.7,.8];values.tofile(folder/'points.bin')
            (folder/'model.spoints').write_text(json.dumps(dict(format='share3dcam-points',version=1,kind='gaussian',data='points.bin',count=2,
                origin=[0,0,0],bounds=[[-1,-1,-1],[1,1,1]],stride_floats=62,sh_degree=degree)))
            (folder/'job.json').write_text(json.dumps(dict(source=str(folder/'model.spoints'),width=128,height=128,fps=30,
                frames=frames,progress=str(folder/'progress.json'))))
            env=os.environ.copy();env['PATH']=str(RUNTIME)+os.pathsep+env.get('PATH','');env['OSG_LIBRARY_PATH']=str(RUNTIME/'osgPlugins-3.6.5')
            r=subprocess.run([str(RUNTIME/'mesh_render.exe'),'job.json'],cwd=folder,env=env,capture_output=True,timeout=30)
            self.assertEqual(r.returncode,0,r.stderr.decode(errors='replace'))
            self.assertEqual(len(r.stdout),len(frames)*128*128*3)
            return json.loads((folder/'progress.json').read_text())['memory']['point_render']

    @staticmethod
    def frames(ortho=False):
        frames=[dict(eye=[x,-5,0],center=[x,0,0],up=[0,0,1],fovy=45) for x in (0,.1,.2,.2)]
        frames.append(dict(eye=[1,-5,0],center=[0,0,0],up=[0,0,1],fovy=45))
        if ortho:
            for frame in frames:frame['orthographic_height']=4
        return frames

    def test_translation_keeps_exact_depth_order_without_repeating_sort(self):
        work=self.render(0,self.frames())
        self.assertEqual(work['count'],2);self.assertEqual(work['sort_updates'],2)
        self.assertEqual(work['sh_updates'],0)

    def test_perspective_sh_still_updates_when_eye_translates(self):
        work=self.render(1,self.frames())
        self.assertEqual(work['sort_updates'],2);self.assertEqual(work['sh_updates'],4)

    def test_parallel_sh_reuses_color_but_recomputes_after_turning(self):
        work=self.render(1,self.frames(True))
        self.assertEqual(work['sort_updates'],2);self.assertEqual(work['sh_updates'],2)

    def test_sh_storage_keeps_only_the_coefficients_used_by_its_degree(self):
        for degree in (1,2,3):
            with self.subTest(degree=degree):
                work=self.render(degree,self.frames())
                self.assertEqual(work['sh_storage_bytes'],2*(degree+1)**2*3*4)
