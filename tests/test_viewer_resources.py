"""Exercise the actual viewer protocol: stationary scenes must stop drawing."""
import json,os,subprocess,tempfile,time,tkinter as tk,unittest
from pathlib import Path
from converter import RUNTIME,write_json
import numpy as np


class ViewerResourceTests(unittest.TestCase):
    def test_idle_settles_and_camera_clip_snapshot_resize_wake_it(self):
        with tempfile.TemporaryDirectory() as d:
            folder=Path(d);root=tk.Tk();root.geometry('360x260+40+40');root.update()
            values=np.array([[0,0,0,1,0,0,.9,.4,.1,.1,1,0,0,0]],dtype='<f4');values.tofile(folder/'points.bin')
            write_json(folder/'model.spoints',dict(format='share3dcam-points',version=1,kind='gaussian',data='points.bin',count=1,
                       origin=[0,0,0],bounds=[[-1,-1,-1],[1,1,1]],stride_floats=14,sh_degree=0))
            write_json(folder/'job.json',dict(source=str(folder/'model.spoints'),parent=root.winfo_id()))
            env=os.environ.copy();env['PATH']=str(RUNTIME)+os.pathsep+env.get('PATH','')
            env['OSG_LIBRARY_PATH']=str(RUNTIME/'osgPlugins-3.6.5')
            p=subprocess.Popen([str(RUNTIME/'mesh_viewer.exe'),'job.json'],cwd=folder,env=env,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,
                               creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            def until(predicate,timeout=12):
                deadline=time.monotonic()+timeout;state={}
                while time.monotonic()<deadline:
                    root.update()
                    if p.poll() is not None:self.fail(p.stderr.read().decode(errors='replace'))
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
                camera=dict(eye=[0,-5,0],center=[0,0,0],up=[0,0,1],fovy=45)
                write_json(folder/'command.json',dict(seq=1,camera=camera))
                b=until(lambda s:s.get('applied_seq')==1 and s.get('rendered_frames',0)>a['rendered_frames']);settle()
                write_json(folder/'snapshot_request.json',dict(id='first',after_seq=1))
                until(lambda s:(folder/'snapshot_result.json').exists());first=(folder/'snapshot.png').read_bytes()
                write_json(folder/'command.json',dict(seq=2,enabled=True,box=[.1,-1,-1,1,1,1]))
                until(lambda s:s.get('applied_seq')==2)
                write_json(folder/'snapshot_request.json',dict(id='clipped',after_seq=2))
                until(lambda s:json.loads((folder/'snapshot_result.json').read_text()).get('id')=='clipped')
                self.assertNotEqual(first,(folder/'snapshot.png').read_bytes())
                c=settle();root.geometry('400x280+40+40');root.update()
                until(lambda s:s.get('rendered_frames',0)>c['rendered_frames']);settle()
            finally:
                write_json(folder/'command.json',dict(seq=99,quit=True));
                try:p.wait(timeout=5)
                except subprocess.TimeoutExpired:p.kill();p.wait()
                p.stderr.close();root.destroy()
