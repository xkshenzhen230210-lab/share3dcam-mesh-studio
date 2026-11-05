import json
from pathlib import Path
import tempfile
import unittest

from workspace_tools import ClipHistory, available_output, read_recent, remember_model


class WorkspaceToolsTests(unittest.TestCase):
    def test_invalid_clip_edit_keeps_last_accepted_box(self):
        clip = ClipHistory([0, 0, 0, 10, 10, 10])
        self.assertTrue(clip.edit([1, 2, 3, 4, 5, 6]))
        for bounds in ([1, 2, 3, 1, 5, 6], [float('nan'), 0, 0, 10, 10, 10], ['', 0, 0, 10, 10, 10]):
            with self.assertRaises(ValueError):
                clip.edit(bounds)
            self.assertEqual(clip.box, (1., 2., 3., 4., 5., 6.))
        self.assertTrue(clip.undo())
        self.assertEqual(clip.box, (0., 0., 0., 10., 10., 10.))

    def test_clip_undo_groups_slider_updates_in_one_step(self):
        clip = ClipHistory([0, 0, 0, 10, 10, 10])
        clip.edit([1, 0, 0, 10, 10, 10])
        clip.edit([2, 0, 0, 10, 10, 10], record=False)
        clip.edit([3, 0, 0, 10, 10, 10], record=False)
        clip.undo()
        self.assertEqual(clip.box[0], 0.)

    def test_repeat_export_keeps_existing_results(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / 'export'
            self.assertEqual(available_output(dest), dest)
            dest.mkdir()
            self.assertEqual(available_output(dest), dest)
            (dest / 'Model.obj').write_text('existing')
            (dest.with_name('export_02')).mkdir()
            self.assertEqual(available_output(dest), dest.with_name('export_03'))
            self.assertEqual((dest / 'Model.obj').read_text(), 'existing')

    def test_recent_models_move_to_front_and_recover_corrupt_settings(self):
        with tempfile.TemporaryDirectory() as tmp:
            history = Path(tmp) / 'profile' / 'recent.json'
            remember_model(history, Path(tmp) / '模型 A.glb')
            remember_model(history, Path(tmp) / '模型 B.osgb')
            remember_model(history, Path(tmp) / '模型 A.glb')
            self.assertEqual([Path(p).name for p in read_recent(history)], ['模型 A.glb', '模型 B.osgb'])
            history.write_text('{broken', encoding='utf-8')
            self.assertEqual(read_recent(history), [])
            remember_model(history, Path(tmp) / 'new.las')
            self.assertEqual(json.loads(history.read_text(encoding='utf-8')), [str(Path(tmp) / 'new.las')])


if __name__ == '__main__':
    unittest.main()
