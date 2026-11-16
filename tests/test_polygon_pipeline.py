import hashlib,json,os,subprocess,tempfile,unittest
from pathlib import Path
import laspy
import numpy as np
from PIL import Image
from converter import Control,RUNTIME
from point_data import crop_points
from spatial_frame import ClipBox

class PolygonPipelineTests(unittest.TestCase):
    def test_gaussian_ply_keeps_original_parameters_and_custom_fields(self):
        from test_point_data import make_ply
        fields=[(n,'f4') for n in ['x','y','z','f_dc_0','f_dc_1','f_dc_2','opacity','scale_0','scale_1','scale_2','rot_0','rot_1','rot_2','rot_3']]+[('custom_id','i4')]
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);source=root/'splat.ply'
            records,_=make_ply(source,[(.5,2,0,1,2,3,.9,.1,.2,.3,1,0,0,0,42),(2,2,0,4,5,6,.4,.2,.3,.4,1,0,0,0,77)],fields)
            before=source.read_bytes();result=crop_points(source,root/'out',self.selection(),Control(lambda *a:None))
            self.assertEqual(Path(result['output']).read_bytes().split(b'end_header\n',1)[1],records[:1].tobytes())
            self.assertEqual(source.read_bytes(),before)
    def selection(self):return dict(bounds=[0,0,-1,3,3,1],polygon=[[0,0],[3,0],[3,1],[1,1],[1,3],[0,3]])

    def test_las_preserves_all_records_in_concave_selection(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);source=root/'points.las';las=laspy.LasData(laspy.LasHeader(point_format=3,version='1.2'))
            las.x=[.5,2,1,3,.5];las.y=[2,2,2,.5,.5];las.z=[0,0,0,0,2];las.intensity=[2,3,4,5,6];las.red=[1,2,3,4,5];las.write(source)
            original=laspy.read(source);before=source.read_bytes()
            result=crop_points(source,root/'out',self.selection(),Control(lambda *a:None))
            self.assertEqual(laspy.read(result['output']).points.array.tobytes(),original.points[[0,2,3]].array.tobytes())
            self.assertEqual(source.read_bytes(),before)

    def test_native_mesh_polygon_matches_concavity_and_texture(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);selection=self.selection();box=ClipBox(selection)
            (root/'model.obj').write_text('mtllib model.mtl\nv 0 0 0\nv 3 0 0\nv 3 3 0\nv 0 3 0\nvt 0 0\nvt 1 0\nvt 1 1\nvt 0 1\nusemtl yellow\nf 1/1 2/2 3/3\nf 1/1 3/3 4/4\n')
            (root/'model.mtl').write_text('newmtl yellow\nKd 1 1 1\nmap_Kd yellow.png\n')
            Image.new('RGB',(4,4),(255,255,0)).save(root/'yellow.png')
            pose=dict(eye=[1.5,1.5,7],center=[1.5,1.5,0],up=[0,1,0],fovy=45)
            job=dict(source=str(root/'model.obj'),width=128,height=128,fps=30,frames=[pose],progress=str(root/'progress.json'),clip_box=selection)
            (root/'job.json').write_text(json.dumps(job));env=os.environ.copy();env['PATH']=str(RUNTIME)+os.pathsep+env.get('PATH','');env['OSG_LIBRARY_PATH']=str(RUNTIME/'osgPlugins-3.6.5')
            r=subprocess.run([str(RUNTIME/'mesh_render.exe'),'job.json'],cwd=root,env=env,capture_output=True)
            self.assertEqual(r.returncode,0,r.stderr.decode(errors='replace'))
            pixels=np.frombuffer(r.stdout,dtype='u1').reshape(128,128,3)[::-1]  # OpenGL streams bottom-up rows
            yellow=(pixels[:,:,0]>180)&(pixels[:,:,1]>180)&(pixels[:,:,2]<60)
            # Top-right notch is empty while lower/right and upper/left arms remain.
            self.assertFalse(yellow[42,86]);self.assertTrue(yellow[86,86]);self.assertTrue(yellow[42,42])
            self.assertGreater(yellow.sum(),2000);self.assertLess(yellow.sum(),2700)

    def test_native_ear_validation_agrees_with_python(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'polygon.json';path.write_text(json.dumps(self.selection()))
            r=subprocess.run([str(RUNTIME/'mesh_viewer.exe'),'--test-polygon',str(path)],cwd=d,capture_output=True,text=True)
            self.assertEqual(r.returncode,0,r.stderr);self.assertEqual(len(json.loads(r.stdout)),4)
            path.write_text(json.dumps(dict(polygon=[[0,0],[2,2],[0,2],[2,0]])))
            r=subprocess.run([str(RUNTIME/'mesh_viewer.exe'),'--test-polygon',str(path)],cwd=d,capture_output=True,text=True)
            self.assertNotEqual(r.returncode,0)
