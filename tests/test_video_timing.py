import copy
import math
import unittest

from video import camera_at, sample_frames, validate_keyframes
from video_timing import playback_keyframes, rescale_duration


def path():
    return [dict(time=stamp, eye=[x, -10, 0], center=[x, 0, 0], up=[0, 0, 1], fovy=35)
            for stamp, x in ((0, 0), (10, 2), (15, 5), (20, 8))]


class VideoTimingTests(unittest.TestCase):
    def test_duration_preserves_four_camera_poses_and_relative_timing(self):
        keys = path(); original = copy.deepcopy(keys)
        result = rescale_duration(keys, 60)
        self.assertEqual([key['time'] for key in result], [0, 30, 45, 60])
        for before, after in zip(validate_keyframes(keys), result):
            self.assertEqual({k: v for k, v in before.items() if k != 'time'},
                             {k: v for k, v in after.items() if k != 'time'})
        self.assertEqual(keys, original)
        result[0]['eye'][0] = 900
        self.assertEqual(keys, original)

    def test_speed_controls_effective_duration_without_changing_base_keys(self):
        base = rescale_duration(path(), 60)
        for speed, expected in ((.25, 240), (.5, 120), (1, 60), (1.5, 40), (2, 30), (4, 15)):
            with self.subTest(speed=speed):
                actual = playback_keyframes(base, speed)
                self.assertEqual(actual[-1]['time'], expected)
                for name in ('eye', 'center', 'up', 'fovy'):
                    self.assertEqual(actual[-1][name], base[-1][name])
        self.assertEqual(base[-1]['time'], 60)

    def test_preview_and_export_follow_the_same_motion_at_each_speed(self):
        base = rescale_duration(path(), 60)
        for speed in (.5, 1, 2):
            effective = playback_keyframes(base, speed)
            for stamp in (0, 7.5, 20, 35, 60):
                expected = camera_at(base, stamp)
                actual = camera_at(effective, stamp / speed)
                for name in ('eye', 'center', 'up'):
                    for a, b in zip(actual[name], expected[name]): self.assertAlmostEqual(a, b)
                self.assertAlmostEqual(actual['fovy'], expected['fovy'])

    def test_one_minute_at_sixty_fps_has_exactly_3600_frames_and_endpoints(self):
        keys = playback_keyframes(rescale_duration(path(), 60), 1)
        frames = sample_frames(keys, 60)
        self.assertEqual(len(frames), 3600)
        self.assertEqual(frames[0], camera_at(keys, 0))
        self.assertEqual(frames[-1], camera_at(keys, 60))

    def test_invalid_durations_and_speeds_are_rejected(self):
        for seconds in (0, -1, math.nan, math.inf, 1800.1, 'bad', None, True):
            with self.subTest(seconds=seconds), self.assertRaises(ValueError):
                rescale_duration(path(), seconds)
        for speed in (0, -.5, .249, 4.001, math.nan, math.inf, 'bad', None, True):
            with self.subTest(speed=speed), self.assertRaises(ValueError):
                playback_keyframes(path(), speed)
        with self.assertRaises(ValueError): playback_keyframes(rescale_duration(path(), 1800), .5)
        with self.assertRaises(ValueError): rescale_duration([path()[0]], 60)

    def test_valid_bounds_and_numeric_ui_text(self):
        self.assertEqual(rescale_duration(path(), '1800')[-1]['time'], 1800)
        self.assertEqual(playback_keyframes(rescale_duration(path(), 450), '.25')[-1]['time'], 1800)
        self.assertEqual(rescale_duration(path(), .125)[-1]['time'], .125)
