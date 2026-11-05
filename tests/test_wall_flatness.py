import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import laspy
import numpy as np

from converter import Control, Cancelled
from wall_flatness import analyze_wall


def write_las(path, xyz):
    header = laspy.LasHeader(point_format=3, version='1.2')
    header.scales = [.000001] * 3
    header.offsets = (np.min(xyz, axis=0)+np.max(xyz, axis=0))/2
    data = laspy.LasData(header)
    data.x, data.y, data.z = xyz.T
    data.write(path)


def wall():
    x, z = np.meshgrid(np.linspace(-2, 2, 41), np.linspace(0, 3, 31))
    return np.column_stack((x.ravel(), np.zeros(x.size), z.ravel()))


class FlatnessTests(unittest.TestCase):
    def run_case(self, xyz, **kwargs):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        folder = Path(temp.name)
        source = folder/'墙面.las'
        write_las(source, xyz)
        before = hashlib.sha256(source.read_bytes()).hexdigest()
        box = np.r_[xyz.min(axis=0)-.01, xyz.max(axis=0)+.01].tolist()
        result = analyze_wall(source, folder/'result', box, **kwargs)
        self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), before)
        self.assertEqual(result['count'], len(xyz))
        self.assertTrue((folder/'result/report.html').is_file())
        self.assertTrue((folder/'result/summary.csv').read_bytes().startswith(b'\xef\xbb\xbf'))
        return result, folder

    def test_flat_tilted_large_world_coordinates(self):
        xyz = wall()
        xyz[:, 1] = .2*xyz[:, 0] + .1*xyz[:, 2]
        xyz += [500000., 4000000., 100.]
        result, _ = self.run_case(xyz)
        self.assertLess(result['max_abs_mm'], .002)
        self.assertEqual(result['outside_count'], 0)
        np.testing.assert_allclose(result['normal'], np.array([-.2, 1, -.1])/np.sqrt(1.05), atol=1e-6)

    def test_symmetric_bumps_exact_statistics_and_units(self):
        base = wall()
        xyz = np.concatenate([base+[0, -.003, 0], base+[0, .003, 0]])
        for unit, scale in [('m', 1), ('cm', 100), ('mm', 1000)]:
            with self.subTest(unit=unit):
                result, _ = self.run_case(xyz*scale, unit=unit, tolerance_mm=2)
                self.assertAlmostEqual(result['rms_mm'], 3, places=5)
                self.assertAlmostEqual(result['range_mm'], 6, places=5)
                self.assertAlmostEqual(result['max_abs_mm'], 3, places=5)
                self.assertEqual(result['outside_count'], len(xyz))

    def test_sampling_does_not_hide_defects_from_statistics(self):
        xyz = wall()
        xyz[777, 1] = .07
        with patch('wall_flatness.PREVIEW_LIMIT', 20):
            result, folder = self.run_case(xyz)
        self.assertGreater(result['max_abs_mm'], 69)
        self.assertGreater(result['outside_count'], 0)
        doc = json.loads((folder/'result/model.spoints').read_text())
        self.assertLessEqual(doc['count'], 20)
        self.assertEqual(doc['source_count'], len(xyz))

    def test_selection_inclusive_and_unselected_objects_excluded(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            xyz = wall()
            write_las(folder/'source.las', np.concatenate([xyz, xyz+[0, 100, 0]]))
            result = analyze_wall(folder/'source.las', folder/'out', [-2,-.01,0,2,.01,3])
            self.assertEqual(result['count'], len(xyz))
            self.assertLess(result['max_abs_mm'], .001)

    def test_rejects_degenerate_empty_nonplanar_and_invalid_settings(self):
        rng = np.random.default_rng(42)
        for xyz in (np.zeros((50,3)), np.column_stack([np.arange(50),np.zeros((50,2))]), rng.uniform(-1,1,(3000,3))):
            with self.subTest(kind=xyz.shape), self.assertRaises(ValueError):
                self.run_case(xyz)
        for options in ({'tolerance_mm':0}, {'tolerance_mm':float('nan')}, {'unit':'feet'}):
            with self.subTest(options=options), self.assertRaises(ValueError):
                self.run_case(wall(), **options)

    def test_cancel_and_source_change_do_not_publish_success(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            source = folder/'wall.las'
            write_las(source, wall())
            import threading
            event = threading.Event(); event.set()
            with self.assertRaises(Cancelled):
                analyze_wall(source, folder/'cancel', [-3,-1,-1,3,1,4], control=Control(event=event))
            self.assertFalse((folder/'cancel/report.json').exists())
            changed = False
            def mutate(message, percent):
                nonlocal changed
                if not changed and percent >= 45:
                    with source.open('ab') as stream: stream.write(b'x')
                    changed = True
            with self.assertRaisesRegex(ValueError, 'Source changed'):
                analyze_wall(source, folder/'changed', [-3,-1,-1,3,1,4], control=Control(mutate))
            self.assertFalse((folder/'changed/report.json').exists())

    def test_chunked_moments_match_independent_centered_svd(self):
        rng = np.random.default_rng(19)
        xyz = wall()
        xyz[:,1] = .1*xyz[:,0] + rng.normal(0,.002,len(xyz))
        xyz += [500000,4000000,100]
        with patch('point_data.CHUNK_SIZE', 100):
            result, folder = self.run_case(xyz)
        data = laspy.read(folder/'墙面.las')
        source_xyz = np.column_stack([data.x,data.y,data.z])
        centered = source_xyz-source_xyz.mean(axis=0)
        _,_,vectors = np.linalg.svd(centered,full_matrices=False)
        distances = centered@vectors[-1]*1000
        self.assertAlmostEqual(result['rms_mm'],float(np.sqrt(np.mean(distances**2))),places=5)
        self.assertAlmostEqual(result['max_abs_mm'],float(np.max(np.abs(distances))),places=5)

    def test_cancel_during_output_and_existing_folder_safety(self):
        import threading
        with tempfile.TemporaryDirectory() as temp:
            folder=Path(temp);source=folder/'source.las';write_las(source,wall())
            event=threading.Event()
            def progress(text,percent):
                if percent>=90:event.set()
            with self.assertRaises(Cancelled):
                analyze_wall(source,folder/'out',[-3,-1,-1,3,1,4],control=Control(progress,event))
            self.assertFalse(list((folder/'out').iterdir()))
            marker=folder/'out'/'keep.txt';marker.write_text('preserve')
            with self.assertRaises(FileExistsError):
                analyze_wall(source,folder/'out',[-3,-1,-1,3,1,4])
            self.assertEqual(marker.read_text(),'preserve')
            with self.assertRaisesRegex(ValueError,'30'):
                analyze_wall(source,folder/'empty',[10,10,10,11,11,11])


if __name__ == '__main__':
    unittest.main()
