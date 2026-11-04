import json
import tempfile
import unittest
from pathlib import Path
from studio import resolve_source


class ModelPathTests(unittest.TestCase):
    def test_export_parent_and_obj_folder_find_same_entry(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);model=root/'obj/Model.obj';model.parent.mkdir();model.write_text('v 0 0 0')
            self.assertEqual(resolve_source(str(root)),model.resolve())
            self.assertEqual(resolve_source(str(model.parent)),model.resolve())

    def test_incomplete_export_is_not_reported_as_missing_entry(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/'obj').mkdir()
            (root/'mesh_progress.json').write_text(json.dumps({'state':'running','progress':31.15}))
            for target in [root,root/'obj']:
                with self.assertRaisesRegex(ValueError,'未完成|中断'):
                    resolve_source(str(target))

    def test_unique_nonstandard_obj_name_is_detected(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);p=root/'building.obj';p.write_text('v 0 0 0')
            self.assertEqual(resolve_source(str(root)),p.resolve())

    def test_failed_export_with_partial_obj_cannot_open(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);p=root/'obj/Model.obj';p.parent.mkdir();p.write_text('partial')
            (root/'mesh_result.json').write_text(json.dumps({'state':'failed'}))
            with self.assertRaisesRegex(ValueError,'失败|未完成'):resolve_source(str(p))
