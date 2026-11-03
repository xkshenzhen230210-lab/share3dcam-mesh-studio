import json
import struct
import tempfile
import unittest
from pathlib import Path
import numpy as np
from gltf import Glb, Y_TO_Z


def triangle(path, matrix=None):
    xyz=np.array([[1,2,3],[2,2,3],[1,3,3]], dtype='<f4').tobytes()
    uv=np.array([[0,0],[1,0],[0,1]],dtype='<f4').tobytes()
    idx=np.array([0,1,2],dtype='<u4').tobytes()
    j={'asset':{'version':'2.0'},'buffers':[{'byteLength':72}],
       'bufferViews':[{'buffer':0,'byteOffset':0,'byteLength':36},
                      {'buffer':0,'byteOffset':36,'byteLength':24},
                      {'buffer':0,'byteOffset':60,'byteLength':12}],
       'accessors':[{'bufferView':0,'componentType':5126,'count':3,'type':'VEC3'},
                    {'bufferView':1,'componentType':5126,'count':3,'type':'VEC2'},
                    {'bufferView':2,'componentType':5125,'count':3,'type':'SCALAR'}],
       'meshes':[{'primitives':[{'attributes':{'POSITION':0,'TEXCOORD_0':1},'indices':2}]}],
       'nodes':[{'mesh':0}], 'scenes':[{'nodes':[0]}], 'scene':0}
    if matrix is not None:j['nodes'][0]['matrix']=matrix.T.reshape(-1).tolist()
    b=json.dumps(j).encode(); b+=b' '*((-len(b))%4)
    path.write_bytes(struct.pack('<5I',0x46546c67,2,28+len(b)+72,len(b),0x4e4f534a)+b+struct.pack('<2I',72,0x004e4942)+xyz+uv+idx)


class GlbTests(unittest.TestCase):
    def test_y_up_and_node_transform_are_applied_in_order(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'x.glb';m=np.eye(4);m[:3,3]=[10,20,30];triangle(p,m)
            with Glb(p) as g:
                part=next(g.primitives())
                np.testing.assert_allclose(part['positions'][0],[11,-33,22])
                np.testing.assert_allclose(part['uv'],[[0,1],[1,1],[0,0]])

    def test_source_z_up_wrapper_cancels_axis_conversion(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'x.glb';triangle(p,np.linalg.inv(Y_TO_Z))
            with Glb(p) as g:
                np.testing.assert_allclose(next(g.primitives())['positions'][0],[1,2,3])

    def test_mirror_reverses_winding(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'x.glb';m=np.diag([-1,1,1,1]);triangle(p,m)
            with Glb(p) as g:np.testing.assert_array_equal(next(g.primitives())['indices'],[[0,2,1]])

    def test_truncated_glb_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'x.glb';triangle(p);p.write_bytes(p.read_bytes()[:-4])
            with self.assertRaises(ValueError):Glb(p)

if __name__=='__main__':unittest.main()
