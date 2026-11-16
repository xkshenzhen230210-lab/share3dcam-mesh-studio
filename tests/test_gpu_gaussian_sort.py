import json,os,subprocess,tempfile,unittest
from pathlib import Path
import numpy as np
from converter import RUNTIME


class GpuGaussianSortTests(unittest.TestCase):
    def test_gpu_indices_and_blended_pixels_match_cpu_with_ties_and_changed_views(self):
        self.exercise(0,70003)

    def test_higher_sh_degrees_preserve_the_same_gpu_order_and_colors(self):
        for degree in (1,2,3):
            with self.subTest(degree=degree):self.exercise(degree,1031)

    def test_subnormal_coordinates_use_exact_cpu_fallback(self):
        self.exercise(0,1000001,tiny=True)

    def exercise(self,degree,count,tiny=False):
        rng=np.random.default_rng(43);records=np.zeros((count,62 if degree else 14),dtype='<f4')
        records[:,:3]=rng.uniform(-.8,.8,(len(records),3));records[:,1]=np.round(records[:,1],2);records[:400,1]=0;records[:,3:6]=rng.uniform(0,1,(len(records),3))
        records[:,6]=.2;records[:,7:10]=.04;records[:,10]=1
        records[0,:3]=0;records[1,:3]=-0.
        if tiny:records[2,0]=np.nextafter(np.float32(0),np.float32(1))
        if degree:records[:,14:]=rng.uniform(-.3,.3,(len(records),48))
        poses=[dict(eye=e,center=[0,0,0],up=[0,0,1],fovy=45) for e in ([0,-5,0],[5,0,0],[0,5,0],[1.3,-5,.8],[-2,-3,-4],[0,-5,0])]
        with tempfile.TemporaryDirectory() as d:
            folder=Path(d);records.tofile(folder/'points.bin')
            (folder/'model.spoints').write_text(json.dumps(dict(format='share3dcam-points',version=1,kind='gaussian',data='points.bin',count=len(records),origin=[0,0,0],bounds=[[-1,-1,-1],[1,1,1]],stride_floats=records.shape[1],sh_degree=degree)))
            env=os.environ.copy();env['PATH']=str(RUNTIME)+os.pathsep+env.get('PATH','');env['OSG_LIBRARY_PATH']=str(RUNTIME/'osgPlugins-3.6.5')
            images=[]
            for mode in ('disabled','auto' if tiny else 'required'):
                job=dict(source=str(folder/'model.spoints'),width=128,height=128,fps=30,frames=poses,progress=str(folder/'progress.json'),gpu_sort=mode,verify_gpu_sort=True)
                (folder/'job.json').write_text(json.dumps(job))
                r=subprocess.run([str(RUNTIME/'mesh_render.exe'),'job.json'],cwd=folder,env=env,capture_output=True,timeout=30)
                message=r.stderr.decode(errors='replace')
                if r.returncode and mode=='required' and ('Compute/subgroup support unavailable' in message or 'GPU sort buffer/subgroup limits' in message):self.skipTest('Optional GPU sort unavailable on this GPU')
                self.assertEqual(r.returncode,0,message);images.append(r.stdout)
                state=json.loads((folder/'progress.json').read_text())
                if tiny and mode=='auto':self.assertEqual(state['memory']['point_render']['sort_backend'],'cpu')
                if mode=='required':
                    self.assertEqual(state['memory']['point_render']['sort_backend'],'gpu')
                    self.assertEqual(state['memory']['point_render']['gpu_verified_updates'],len(poses))
            self.assertEqual(images[0],images[1])
