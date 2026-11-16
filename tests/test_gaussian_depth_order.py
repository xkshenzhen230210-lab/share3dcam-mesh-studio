import json,subprocess,tempfile,unittest
from pathlib import Path
import numpy as np
from converter import RUNTIME


class GaussianDepthOrderTests(unittest.TestCase):
    def test_exact_back_to_front_order_with_ties_and_negative_depths(self):
        rng=np.random.default_rng(42);points=rng.normal(size=(12000,3)).astype('f4');points[:1000]=[0,0,0]
        points[1000:2000]=[0,4,0];points[2000:3000]=[0,-4,0];points[3000]=[0,-0.,0]
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'positions.json';path.write_text(json.dumps(dict(positions=points.tolist(),direction=[0,1,0])))
            r=subprocess.run([str(RUNTIME/'mesh_viewer.exe'),'--test-depth-sort',str(path)],capture_output=True,text=True,cwd=d)
            self.assertEqual(r.returncode,0,r.stderr);actual=json.loads(r.stdout)
            self.assertTrue(actual['matches_reference'])
            expected=np.lexsort((np.arange(len(points)),-points[:,1])).tolist()
            self.assertEqual(actual['indices'],expected)
