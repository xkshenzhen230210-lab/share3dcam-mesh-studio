import json
import tempfile
import unittest
from pathlib import Path
from tiles import load_tiles, obj_nodes


class TileTests(unittest.TestCase):
    def fixture(self, root, node):
        (root/'a.glb').touch();(root/'b.glb').touch()
        p=root/'tileset.json';p.write_text(json.dumps({'asset':{'version':'1.1'},'root':node}));return p

    def test_replace_selects_only_finest(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);p=self.fixture(root,{'content':{'uri':'a.glb'},'children':[{'content':{'uri':'b.glb'}}]})
            tree=load_tiles(p)
            self.assertEqual([x.source.name for x in obj_nodes(tree)],['b.glb'])

    def test_add_preserves_parent(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);p=self.fixture(root,{'refine':'ADD','content':{'uri':'a.glb'},'children':[{'content':{'uri':'b.glb'}}]})
            self.assertEqual(len(obj_nodes(load_tiles(p))),2)

    def test_external_tileset_transform_is_composed(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);t=[1,0,0,0,0,1,0,0,0,0,1,0,10,0,0,1]
            p=self.fixture(root,{'transform':t,'content':{'uri':'external.json'}})
            (root/'external.json').write_text(json.dumps({'root':{'transform':t,'content':{'uri':'a.glb'}}}))
            self.assertEqual(obj_nodes(load_tiles(p))[0].transform[0,3],20)

    def test_missing_content_fails(self):
        with tempfile.TemporaryDirectory() as d:
            p=self.fixture(Path(d),{'content':{'uri':'missing.glb'}})
            with self.assertRaises(FileNotFoundError):load_tiles(p)

    def test_cycle_fails(self):
        with tempfile.TemporaryDirectory() as d:
            p=self.fixture(Path(d),{'content':{'uri':'tileset.json'}})
            with self.assertRaises(ValueError):load_tiles(p)
