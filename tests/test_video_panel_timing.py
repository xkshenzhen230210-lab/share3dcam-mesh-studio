import json
import tempfile
import tkinter as tk
import unittest
from pathlib import Path
from unittest.mock import patch

from video import camera_at
from video_panel import VideoPanel


def path():
    return [dict(time=stamp, eye=[x, -10, 0], center=[x, 0, 0], up=[0, 0, 1], fovy=35)
            for stamp, x in ((0, 0), (10, 2), (15, 5), (20, 8))]


class VideoPanelTimingTests(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk(); self.root.withdraw()
        self.work = tempfile.TemporaryDirectory(); self.folder = Path(self.work.name)
        self.cameras = []; self.exports = []
        self.panel = VideoPanel(self.root, lambda callback: callback(path()[0]),
                                self.cameras.append, lambda: self.folder / 'Model.glb',
                                lambda *args: self.exports.append(args))
        self.panel.keys = path(); self.panel.refresh()

    def tearDown(self):
        self.panel.stop(); self.root.destroy(); self.work.cleanup()

    def test_render_applies_typed_duration_without_set_and_uses_requested_format(self):
        self.panel.duration.set('60'); self.panel.resolution.set('4K'); self.panel.fps.set('60')
        output = str(self.folder / 'minute.mp4')
        with patch('video_panel.filedialog.asksaveasfilename', return_value=output): self.panel.render()
        filename, keys, resolution, fps = self.exports[0]
        self.assertEqual(filename, output)
        self.assertEqual([k['time'] for k in keys], [0, 30, 45, 60])
        self.assertEqual((resolution, fps), ('4K', 60))
        self.assertEqual(self.panel.duration.get(), '60')
        self.assertIn('60.00 s', self.panel.final_duration.get())

    def test_preview_and_export_at_double_speed_share_the_thirty_second_timeline(self):
        self.panel.duration.set('60'); self.panel.commit_duration()
        self.panel.speed.set('2x'); self.panel.speed_changed()
        effective = self.panel.playback_keys()
        self.assertEqual([k['time'] for k in effective], [0, 15, 22.5, 30])
        self.panel.position.set(10); self.panel.play()
        shown = self.cameras[-1]; position = self.panel.position.get(); self.panel.stop()
        self.assertEqual(shown, camera_at(effective, position))
        with patch('video_panel.filedialog.asksaveasfilename', return_value=str(self.folder / 'fast.mp4')):
            self.panel.render()
        self.assertEqual(self.exports[0][1], effective)
        self.assertEqual(self.panel.keys[-1]['time'], 60)

    def test_speed_changes_update_final_duration_clock_and_seek_range(self):
        self.panel.duration.set('60'); self.panel.commit_duration()
        for speed, duration in (('0.5x', 120), ('1x', 60), ('4x', 15)):
            with self.subTest(speed=speed):
                self.panel.speed.set(speed); self.panel.speed_changed()
                self.assertEqual(self.panel.output_seconds(), duration)
                self.assertIn(f'{duration:.2f} s', self.panel.final_duration.get())
                self.assertEqual(self.panel.clock.cget('text'), f'0.00 / {duration:.2f} s')
                self.assertEqual(float(self.panel.scale.cget('to')), duration)

    def test_speed_change_applies_visible_typed_duration_before_updating_final(self):
        self.panel.duration.set('60')
        self.panel.speed.set('2x'); self.panel.speed_changed()
        self.assertEqual(self.panel.keys[-1]['time'], 60)
        self.assertEqual(self.panel.output_seconds(), 30)
        self.assertIn('30.00 s', self.panel.final_duration.get())
        self.assertEqual(self.panel.clock.cget('text'), '0.00 / 30.00 s')
        self.assertEqual(float(self.panel.scale.cget('to')), 30)

    def test_version_two_save_load_preserves_duration_speed_and_export_settings(self):
        filename = str(self.folder / 'animation.json')
        self.panel.duration.set('60'); self.panel.speed.set('0.5x'); self.panel.speed_changed()
        self.panel.resolution.set('4K'); self.panel.fps.set('60')
        with patch('video_panel.filedialog.asksaveasfilename', return_value=filename): self.panel.save()
        saved = json.loads(Path(filename).read_text(encoding='utf-8'))
        self.assertEqual(saved['version'], 2)
        self.assertEqual((saved['speed'], saved['resolution'], saved['fps']), (.5, '4K', 60))
        self.assertEqual([k['time'] for k in saved['keyframes']], [0, 30, 45, 60])
        self.panel.reset(); self.panel.resolution.set('1080p'); self.panel.fps.set('24')
        with patch('video_panel.filedialog.askopenfilename', return_value=filename): self.panel.load()
        self.assertEqual(self.panel.keys, saved['keyframes'])
        self.assertEqual((self.panel.duration.get(), self.panel.speed.get()), ('60', '0.5x'))
        self.assertEqual((self.panel.resolution.get(), self.panel.fps.get()), ('4K', '60'))
        self.assertEqual(self.panel.playback_keys()[-1]['time'], 120)

    def test_version_one_animation_remains_loadable_at_normal_speed(self):
        filename = self.folder / 'legacy.json'
        filename.write_text(json.dumps(dict(version=1, source='Model.glb', keyframes=path())), encoding='utf-8')
        self.panel.speed.set('2x'); self.panel.speed_changed()
        with patch('video_panel.filedialog.askopenfilename', return_value=str(filename)): self.panel.load()
        self.assertEqual(self.panel.duration.get(), '20')
        self.assertEqual(self.panel.speed.get(), '1x')
        self.assertEqual([k['time'] for k in self.panel.playback_keys()], [0, 10, 15, 20])

    def test_invalid_effective_duration_does_not_mutate_keyframes(self):
        before = path(); self.panel.speed.set('0.25x'); self.panel.speed_changed()
        self.panel.duration.set('500')
        with self.assertRaises(ValueError): self.panel.commit_duration()
        self.assertEqual(self.panel.keys, before)
