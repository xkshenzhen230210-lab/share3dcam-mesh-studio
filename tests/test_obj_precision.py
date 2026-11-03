import tempfile
import unittest
from pathlib import Path
import numpy as np
from gltf import Glb
from clipping import clip_primitive
from converter import convert,Control
from test_gltf import triangle


class PrecisionTests(unittest.TestCase):
    def test_clipped_positions_and_uv_roundtrip_exactly(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);source=root/'input/model.glb';source.parent.mkdir();triangle(source)
            box=[1.123456789012345,-4,1,3,-2,4]
            with Glb(source) as glb:expected=clip_primitive(next(glb.primitives()),box)
            convert(source,root/'out','both',Control(lambda *a:None),clip_box=box)
            lines=(root/'out/obj/Model.obj').read_text().splitlines()
            xyz=np.array([[float(v) for v in line.split()[1:]] for line in lines if line.startswith('v ')])
            uv=np.array([[float(v) for v in line.split()[1:]] for line in lines if line.startswith('vt ')])
            np.testing.assert_array_equal(xyz,expected['positions'])
            np.testing.assert_array_equal(uv,expected['uv'])
