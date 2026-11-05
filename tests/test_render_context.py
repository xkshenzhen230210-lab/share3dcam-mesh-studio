"""Both production context paths must preserve the same rendered pixels."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
import numpy as np
from converter import RUNTIME

class RenderContextTests(unittest.TestCase):
    def test_window_fallback_preserves_pixels_and_reports_actual_gpu(self):
        with tempfile.TemporaryDirectory() as folder:
            folder=Path(folder)
            records=[[0,0,0,1,.2,.1,.9,.5,.05,.05,1,0,0,0]+[0]*48]
            np.asarray(records,dtype='<f4').tofile(folder/'points.bin')
            (folder/'model.spoints').write_text(json.dumps(dict(format='share3dcam-points',version=1,kind='gaussian',
                data='points.bin',count=1,origin=[0,0,0],bounds=[[-1,-1,-1],[1,1,1]],stride_floats=62,sh_degree=0)))
            pose=dict(eye=[0,-5,0],center=[0,0,0],up=[0,0,1],fovy=45)
            env=os.environ.copy();env['PATH']=str(RUNTIME)+os.pathsep+env.get('PATH','')
            env['OSG_LIBRARY_PATH']=str(RUNTIME/'osgPlugins-3.6.5')
            images=[]
            for mode in ('pbuffer','window'):
                progress=folder/(mode+'.json')
                job=dict(source=str(folder/'model.spoints'),width=128,height=128,fps=30,
                    frames=[pose],context_mode=mode,progress=str(progress))
                (folder/'job.json').write_text(json.dumps(job))
                result=subprocess.run([str(RUNTIME/'mesh_render.exe'),'job.json'],cwd=folder,env=env,
                    capture_output=True,timeout=30,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
                self.assertEqual(result.returncode,0,result.stderr.decode(errors='replace'))
                self.assertEqual(len(result.stdout),128*128*3)
                state=json.loads(progress.read_text())
                self.assertEqual((state['state'],state['frame']),('succeeded',1))
                self.assertTrue(state['graphics']['renderer'])
                self.assertTrue(state['graphics']['version'])
                self.assertGreaterEqual(state['graphics']['max_renderbuffer_size'],128)
                if mode=='window':self.assertEqual(state['graphics']['context_mode'],'window')
                image=np.frombuffer(result.stdout,np.uint8).reshape(128,128,3)
                self.assertGreater(int(image[64,64,0]),100)
                images.append(image)
            np.testing.assert_array_equal(images[0],images[1])
