"""Exercise the actual viewer protocol: stationary scenes must stop drawing."""
import json,os,subprocess,tempfile,time,tkinter as tk,unittest
from pathlib import Path
from converter import RUNTIME,write_json,Control
import numpy as np
from PIL import Image


class ViewerResourceTests(unittest.TestCase):
    def test_idle_settles_and_camera_clip_snapshot_resize_wake_it(self):
        self.exercise('gaussian')

    def test_paged_mesh_loads_and_prepares_materials_without_camera_motion(self):
        self.exercise('mesh')

    def test_gpu_viewer_idles_and_wakes_for_clipping_resize_and_snapshot(self):
        self.exercise('gaussian_gpu')

    def exercise(self,kind):
        with tempfile.TemporaryDirectory() as d:
            folder=Path(d);root=tk.Tk();root.geometry('360x260+40+40');root.update()
            values=np.array([[0,0,0,1,0,0,.9,.4,.1,.1,1,0,0,0]],dtype='<f4');values.tofile(folder/'points.bin')
            write_json(folder/'model.spoints',dict(format='share3dcam-points',version=1,kind='gaussian',data='points.bin',count=1,
                       origin=[0,0,0],bounds=[[-1,-1,-1],[1,1,1]],stride_floats=14,sh_degree=0))
            source=folder/'model.spoints'
            if kind=='mesh':
                Image.new('RGB',(2,2),'red').save(folder/'red.png')
                xyz=np.array([[-.5,0,-.5],[.5,0,-.5],[0,0,.5]],dtype='<f8')
                uv=np.array([[0,0],[1,0],[.5,1]],dtype='<f4');indices=np.array([0,1,2],dtype='<u4')
                (folder/'geometry.bin').write_bytes(xyz.tobytes()+uv.tobytes()+indices.tobytes())
                primitive=dict(offset=0,vertices=3,indices=3,uv=True,normals=False,color=[1,1,1,1],doubleSided=True,texture='red.png')
                write_json(folder/'write.json',dict(buffer='geometry.bin',primitives=[primitive],output='leaf.osgb'))
                control=Control(lambda *a:None);control.run([RUNTIME/'mesh_writer.exe','write','write.json'],folder)
                write_json(folder/'write.json',dict(output='root.osgb',children=[dict(path='leaf.osgb',center=[0,0,0],radius=2)]))
                control.run([RUNTIME/'mesh_writer.exe','write','write.json'],folder);source=folder/'root.osgb'
            write_json(folder/'job.json',dict(source=str(source),parent=root.winfo_id(),gpu_sort='required' if kind=='gaussian_gpu' else 'auto'))
            env=os.environ.copy();env['PATH']=str(RUNTIME)+os.pathsep+env.get('PATH','')
            env['OSG_LIBRARY_PATH']=str(RUNTIME/'osgPlugins-3.6.5')
            p=subprocess.Popen([str(RUNTIME/'mesh_viewer.exe'),'job.json'],cwd=folder,env=env,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,
                               creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            def until(predicate,timeout=12):
                deadline=time.monotonic()+timeout;state={}
                while time.monotonic()<deadline:
                    root.update()
                    if p.poll() is not None:
                        message=p.stderr.read().decode(errors='replace')
                        if kind=='gaussian_gpu' and ('Compute/subgroup support unavailable' in message or 'GPU sort buffer/subgroup limits' in message):self.skipTest('Optional GPU sort unavailable on this GPU')
                        self.fail(message)
                    try:state=json.loads((folder/'state.json').read_text())
                    except (OSError,ValueError):pass
                    if predicate(state):return state
                    time.sleep(.02)
                self.fail('Viewer timeout: '+str(state))
            def settle():
                previous=None;steady=time.monotonic()
                def quiet(state):
                    nonlocal previous,steady
                    current=state.get('rendered_frames')
                    if current is None:return False
                    if current!=previous:previous=current;steady=time.monotonic()
                    return time.monotonic()-steady>.6
                return until(quiet)
            try:
                until(lambda s:s.get('ready'));a=settle()
                self.assertGreaterEqual(a['rendered_frames'],1)
                if kind=='mesh':self.assertEqual(a['loaded_mesh_drawables'],1)
                camera=dict(eye=[0,-5,0],center=[0,0,0],up=[0,0,1],fovy=45)
                write_json(folder/'command.json',dict(seq=1,camera=camera))
                b=until(lambda s:s.get('applied_seq')==1 and s.get('rendered_frames',0)>a['rendered_frames']);settle()
                write_json(folder/'snapshot_request.json',dict(id='first',after_seq=1))
                until(lambda s:(folder/'snapshot_result.json').exists());first=(folder/'snapshot.png').read_bytes()
                pixels=np.array(Image.open(folder/'snapshot.png'))
                self.assertGreater(np.count_nonzero(pixels[:,:,0]>100),100)
                write_json(folder/'command.json',dict(seq=2,enabled=True,box=[.1,-1,-1,1,1,1]))
                until(lambda s:s.get('applied_seq')==2)
                write_json(folder/'snapshot_request.json',dict(id='clipped',after_seq=2))
                until(lambda s:json.loads((folder/'snapshot_result.json').read_text()).get('id')=='clipped')
                self.assertNotEqual(first,(folder/'snapshot.png').read_bytes())
                c=settle();root.geometry('400x280+40+40');root.update()
                until(lambda s:s.get('rendered_frames',0)>c['rendered_frames']);settle()
                root.withdraw();root.update();hidden=settle()
                root.deiconify();root.update()
                until(lambda s:s.get('rendered_frames',0)>hidden['rendered_frames']);settle()
            finally:
                write_json(folder/'command.json',dict(seq=99,quit=True));
                try:p.wait(timeout=5)
                except subprocess.TimeoutExpired:p.kill();p.wait()
                p.stderr.close();root.destroy()
