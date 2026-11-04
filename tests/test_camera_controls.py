"""Black-box contract for predictable world-up mouse camera controls.

mesh_viewer --test-mouse-controls runs without creating a window. Every case
starts at eye=(0,-5,0), center=(0,0,0), up=(0,0,1), fovy=35. Its JSON contains
look/orbit/pitch/pan/split/whole/wheel poses, each with eye/center/up vectors.
The reported poses must come from the same controls used by the viewer.
"""
import json
import math
import os
from pathlib import Path
import subprocess
import unittest

import numpy as np

from converter import RUNTIME


class CameraControlsTests(unittest.TestCase):
    INITIAL_EYE = np.array([0., -5., 0.])
    INITIAL_CENTER = np.zeros(3)
    WORLD_UP = np.array([0., 0., 1.])

    @classmethod
    def setUpClass(cls):
        env = os.environ.copy()
        env['PATH'] = str(RUNTIME) + os.pathsep + env.get('PATH', '')
        result = subprocess.run([str(RUNTIME/'mesh_viewer.exe'), '--test-mouse-controls'],
                                cwd=Path(__file__).resolve().parents[1], env=env,
                                capture_output=True, text=True, encoding='utf-8',
                                errors='replace', timeout=20,
                                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        if result.returncode:
            raise AssertionError(f'Mouse-control self-test failed ({result.returncode}): {result.stderr}')
        try:
            cls.poses = json.loads(result.stdout)
        except (ValueError, TypeError) as exc:
            raise AssertionError(f'Mouse-control self-test did not return JSON: {result.stdout!r}') from exc

    def pose(self, name):
        self.assertIn(name, self.poses)
        result = {}
        for field in ('eye', 'center', 'up'):
            vector = np.asarray(self.poses[name][field], dtype=np.float64)
            self.assertEqual(vector.shape, (3,), f'{name}.{field}')
            self.assertTrue(np.isfinite(vector).all(), f'{name}.{field}')
            result[field] = vector
        return result

    @staticmethod
    def forward(pose):
        direction = pose['center'] - pose['eye']
        return direction / np.linalg.norm(direction)

    def test_look_eye_unchanged(self):
        # RMB: right 100px, vertical 0px, viewport height 600px.
        look = self.pose('look')
        np.testing.assert_allclose(look['eye'], self.INITIAL_EYE, atol=1e-9, rtol=0)
        self.assertGreater(np.linalg.norm(look['center']-self.INITIAL_CENTER), .01)

    def test_orbit_center_unchanged(self):
        # LMB: right 100px and down 60px, preserving the orbit target.
        orbit = self.pose('orbit')
        np.testing.assert_allclose(orbit['center'], self.INITIAL_CENTER, atol=1e-9, rtol=0)
        self.assertGreater(np.linalg.norm(orbit['eye']-self.INITIAL_EYE), .01)

    def test_orbit_distance_preserved(self):
        orbit = self.pose('orbit')
        self.assertAlmostEqual(np.linalg.norm(orbit['eye']-orbit['center']), 5., places=8)

    def test_look_right_x_positive(self):
        direction = self.forward(self.pose('look'))
        self.assertGreater(direction[0], .01, 'Dragging right must look toward world +X')
        self.assertAlmostEqual(direction[2], 0., places=8)

    def test_pitch_limited(self):
        # An extreme upward mouse drag must stop at +85 degrees, not flip.
        pitch = self.pose('pitch')
        elevation = math.degrees(math.asin(float(np.clip(self.forward(pitch)[2], -1., 1.))))
        self.assertGreaterEqual(elevation, 84.9)
        self.assertLessEqual(elevation, 85.000001)
        np.testing.assert_allclose(pitch['eye'], self.INITIAL_EYE, atol=1e-9, rtol=0)

    def test_no_roll_up_dot_z_positive(self):
        for name in ('look', 'orbit', 'pitch', 'pan', 'split', 'whole', 'wheel'):
            with self.subTest(pose=name):
                pose = self.pose(name)
                direction = self.forward(pose)
                up = pose['up'] / np.linalg.norm(pose['up'])
                self.assertGreater(float(np.dot(up, self.WORLD_UP)), 0)
                self.assertAlmostEqual(float(np.dot(up, direction)), 0., places=8)
                right = np.cross(direction, up)
                self.assertAlmostEqual(float(np.dot(right, self.WORLD_UP)), 0., places=8)

    def test_pan_distance_preserved(self):
        # MMB 50px/30px moves eye and center together without changing aim.
        pan = self.pose('pan')
        np.testing.assert_allclose(pan['eye']-self.INITIAL_EYE,
                                   pan['center']-self.INITIAL_CENTER, atol=1e-9, rtol=0)
        self.assertAlmostEqual(np.linalg.norm(pan['center']-pan['eye']), 5., places=8)
        self.assertGreater(np.linalg.norm(pan['eye']-self.INITIAL_EYE), .01)

    def test_subdivision_equivalent(self):
        # Two RMB updates of 50px/20px equal one update of 100px/40px.
        split, whole = self.pose('split'), self.pose('whole')
        for field in ('eye', 'center', 'up'):
            np.testing.assert_allclose(split[field], whole[field], atol=1e-8, rtol=0,
                                       err_msg=f'Event subdivision changed {field}')
        self.assertGreater(np.linalg.norm(whole['center']-self.INITIAL_CENTER), .01)

    def test_wheel_forward_closer(self):
        wheel = self.pose('wheel')
        distance = np.linalg.norm(wheel['center']-wheel['eye'])
        self.assertGreater(distance, 0.)
        self.assertLess(distance, 5.)
        self.assertGreater(wheel['eye'][1], self.INITIAL_EYE[1])
        np.testing.assert_allclose(wheel['center'], self.INITIAL_CENTER, atol=1e-9, rtol=0)
        np.testing.assert_allclose(self.forward(wheel), [0, 1, 0], atol=1e-9, rtol=0)

    def test_sensitivity_scales_yaw_and_pitch_angles(self):
        def angles(name):
            forward = self.forward(self.pose(name))
            return np.degrees([math.atan2(forward[0], forward[1]),
                               math.asin(float(np.clip(forward[2], -1., 1.)))])
        base = angles('whole')
        self.assertGreater(np.linalg.norm(base), 1.)
        np.testing.assert_allclose(angles('sensitivity_half'), base*.5, atol=1e-8, rtol=0)
        np.testing.assert_allclose(angles('sensitivity_double'), base*2., atol=1e-8, rtol=0)

    def test_mouse_distance_scales_with_viewport_height(self):
        # The same fraction of the screen must produce the same orientation.
        for first, second in [('whole', 'height_double'), ('sensitivity_half', 'height_tall')]:
            with self.subTest(first=first, second=second):
                a, b = self.pose(first), self.pose(second)
                for field in ('eye', 'center', 'up'):
                    np.testing.assert_allclose(a[field], b[field], atol=1e-8, rtol=0)

    def test_downward_pitch_limit_stays_upright(self):
        pose = self.pose('pitch_down')
        direction = self.forward(pose)
        elevation = math.degrees(math.asin(float(np.clip(direction[2], -1., 1.))))
        self.assertGreaterEqual(elevation, -85.000001)
        self.assertLessEqual(elevation, -84.9)
        self.assertGreater(pose['up'][2], 0.)
        np.testing.assert_allclose(pose['eye'], self.INITIAL_EYE, atol=1e-9, rtol=0)

    def test_extreme_zoom_has_finite_nonzero_distance_limits(self):
        for name, expected in [('wheel_near', 1e-5), ('wheel_far', 1e12)]:
            with self.subTest(pose=name):
                pose = self.pose(name)
                distance = np.linalg.norm(pose['center']-pose['eye'])
                self.assertAlmostEqual(distance/expected, 1., places=8)
                np.testing.assert_allclose(pose['center'], self.INITIAL_CENTER, atol=1e-9, rtol=0)
                np.testing.assert_allclose(self.forward(pose), [0, 1, 0], atol=1e-9, rtol=0)

    def test_legacy_keyframe_roll_is_preserved_until_mouse_rotation(self):
        # Existing projects may intentionally contain roll. Loading a pose is
        # distinct from the new world-up mouse rotation policy.
        pose = self.pose('legacy_rolled')
        np.testing.assert_allclose(pose['eye'], self.INITIAL_EYE, atol=1e-9, rtol=0)
        np.testing.assert_allclose(pose['center'], self.INITIAL_CENTER, atol=1e-9, rtol=0)
        np.testing.assert_allclose(pose['up'], [math.sqrt(.5), 0, math.sqrt(.5)], atol=1e-8, rtol=0)


if __name__ == '__main__':
    unittest.main()
