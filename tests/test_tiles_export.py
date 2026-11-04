import io
import json
import struct
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
from PIL import Image

from clipping import clip_primitive
from converter import Cancelled, Control, RUNTIME, convert, write_json
from formats import Mesh
from gltf import Glb
from mesh_tiles_export import _GlbWriter, export_tiles
from tiles import load_tiles, obj_nodes


def textured_triangle(path, matrix=None):
    """Asymmetric image, UVs, normal and alpha make orientation loss observable."""
    image = Image.new('RGBA', (19, 11), (240, 10, 20, 123))
    image.putpixel((0, 0), (0, 255, 0, 255))
    stream = io.BytesIO(); image.save(stream, format='PNG'); pixels = stream.getvalue()
    arrays = [np.array([[0, 0, 0], [2, 0, 0], [0, 2, 0]], dtype='<f4'),
              np.array([[.125, .25], [.875, .25], [.125, .75]], dtype='<f4'),
              np.array([[0, 0, 1]] * 3, dtype='<f4'),
              np.array([0, 1, 2], dtype='<u4')]
    binary = bytearray(); views = []; accessors = []
    for array, kind in zip(arrays, ('VEC3', 'VEC2', 'VEC3', 'SCALAR')):
        views.append({'buffer': 0, 'byteOffset': len(binary), 'byteLength': array.nbytes})
        accessors.append({'bufferView': len(views)-1, 'componentType': 5125 if kind == 'SCALAR' else 5126,
                          'count': len(array), 'type': kind})
        binary.extend(array.tobytes())
    views.append({'buffer': 0, 'byteOffset': len(binary), 'byteLength': len(pixels)})
    binary.extend(pixels)
    doc = {'asset': {'version': '2.0'}, 'buffers': [{'byteLength': len(binary)}],
           'bufferViews': views, 'accessors': accessors,
           'images': [{'bufferView': 4, 'mimeType': 'image/png'}],
           'textures': [{'source': 0, 'sampler': 0}],
           'samplers': [{'wrapS': 33071, 'wrapT': 10497, 'minFilter': 9729, 'magFilter': 9729}],
           'materials': [{'pbrMetallicRoughness': {'baseColorTexture': {'index': 0},
                                                  'baseColorFactor': [.8, .7, .6, .4],
                                                  'metallicFactor': 0, 'roughnessFactor': .7},
                          'alphaMode': 'MASK', 'alphaCutoff': .3, 'doubleSided': True,
                          'extensions': {'KHR_materials_unlit': {}}}],
           'extensionsUsed': ['KHR_materials_unlit'],
           'meshes': [{'primitives': [{'attributes': {'POSITION': 0, 'TEXCOORD_0': 1, 'NORMAL': 2},
                                       'indices': 3, 'material': 0}]}],
           'nodes': [{'mesh': 0}], 'scenes': [{'nodes': [0]}], 'scene': 0}
    if matrix is not None: doc['nodes'][0]['matrix'] = matrix.T.reshape(-1).tolist()
    body = json.dumps(doc).encode(); body += b' ' * (-len(body) % 4)
    binary.extend(b'\0' * (-len(binary) % 4))
    path.write_bytes(struct.pack('<4sII', b'glTF', 2, 28+len(body)+len(binary)) +
                     struct.pack('<II', len(body), 0x4e4f534a) + body +
                     struct.pack('<II', len(binary), 0x004e4942) + binary)
    return pixels


def read_export(output):
    root = load_tiles(output / '3dtiles' / 'tileset.json')
    parts = []
    for tile in obj_nodes(root):
        with Glb(tile.source) as model:
            parts.extend(model.primitives(tile.transform))
    return root, parts


def edit_glb(path, update):
    with Glb(path) as model:
        doc = json.loads(json.dumps(model.doc))
        binary = bytes(model.mm[model.bin_offset:model.bin_offset+model.bin_length])
    update(doc)
    body = json.dumps(doc).encode(); body += b' ' * (-len(body) % 4)
    path.write_bytes(struct.pack('<4sII', b'glTF', 2, 28+len(body)+len(binary)) +
                     struct.pack('<II', len(body), 0x4e4f534a) + body +
                     struct.pack('<II', len(binary), 0x004e4942) + binary)


def native_scene(path, varying=False):
    colors = '1 0 0 1\n0 1 0 1\n0 0 1 1' if varying else '.2 .3 .4 .5\n.2 .3 .4 .5\n.2 .3 .4 .5'
    path.write_text('''#Ascii Scene
#Version 161
#Generator OpenSceneGraph 3.6.5
osg::MatrixTransform {
  UniqueID 1
  Children 1 {
    osg::Geode {
      UniqueID 2
      Drawables 1 {
        osg::Geometry {
          UniqueID 3
          PrimitiveSetList 1 {
            osg::DrawElementsUInt { UniqueID 4 Mode TRIANGLES vector 3 { 0 1 2 } }
          }
          VertexArray TRUE {
            osg::Vec3Array { UniqueID 5 Binding BIND_PER_VERTEX vector 3 { 0 0 0 1 0 0 0 1 0 } }
          }
          NormalArray TRUE {
            osg::Vec3Array { UniqueID 6 Binding BIND_OVERALL vector 1 { 1 1 1 } }
          }
          ColorArray TRUE {
            osg::Vec4Array { UniqueID 7 Binding BIND_PER_VERTEX vector 3 { COLORS } }
          }
        }
      }
    }
  }
  Matrix { -2 0 0 0 0 3 0 0 0 0 4 0 5 6 7 1 }
}
'''.replace('COLORS', colors), encoding='utf-8')


class TilesExportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source = self.root / 'input'; self.source.mkdir()
        self.model = self.source / '模型.glb'
        self.output = self.root / 'output'
        self.quiet = Control(lambda *args: None)

    def tearDown(self): self.temp.cleanup()

    def test_round_trip_preserves_y_up_uv_normals_alpha_and_original_png(self):
        pixels = textured_triangle(self.model)
        report = convert(self.model, self.output, '3dtiles', self.quiet)
        tree, parts = read_export(self.output)
        with Glb(self.model) as model: expected = next(model.primitives())
        actual = parts[0]
        for key in ('positions', 'indices', 'uv', 'normals'):
            np.testing.assert_allclose(actual[key], expected[key], atol=1e-7)
        self.assertEqual(actual['material'], expected['material'])
        leaf = obj_nodes(tree)[0]
        with Glb(leaf.source) as model:
            data, ext, sampler = model.image(actual['texture'])
            self.assertEqual(data, pixels)
            self.assertEqual(ext, '.png')
            self.assertEqual(sampler['wrapS'], 33071)
            with Image.open(io.BytesIO(data)) as image: self.assertEqual(image.size, (19, 11))
            # Local glTF Y is the source up axis, while tileset space is Z-up.
            positions = model.accessor(model.doc['meshes'][0]['primitives'][0]['attributes']['POSITION'])
            self.assertGreater(np.ptp(positions[:, 1]), 0)
            self.assertEqual(np.ptp(positions[:, 2]), 0)
        self.assertEqual(report['state'], 'succeeded')
        quality = json.loads((self.output / 'quality_report.json').read_text(encoding='utf-8'))
        self.assertEqual(quality['state'], 'passed')
        self.assertEqual(quality['triangles'], 1)
        result = json.loads((self.output / 'mesh_result.json').read_text(encoding='utf-8'))
        self.assertEqual(result['data']['tileset_root'], '3dtiles/tileset.json')

    def test_large_translated_coordinates_keep_local_precision_and_metadata(self):
        matrix = np.eye(4); matrix[:3, 3] = [6378137.123, 4888123.456, 3588888.789]
        textured_triangle(self.model, matrix)
        metadata = b'<ModelMetadata><SRS>LOCAL</SRS></ModelMetadata>'
        (self.source / 'metadata.xml').write_bytes(metadata)
        export_tiles(self.model, self.output, self.quiet)
        _, parts = read_export(self.output)
        with Glb(self.model) as model: expected = next(model.primitives())
        np.testing.assert_allclose(parts[0]['positions'], expected['positions'], rtol=0, atol=1e-8)
        self.assertEqual((self.output / '3dtiles' / 'metadata.xml').read_bytes(), metadata)

    def test_default_gltf_material_keeps_default_pbr_values(self):
        textured_triangle(self.model)
        edit_glb(self.model, lambda doc: doc['meshes'][0]['primitives'][0].pop('material'))
        export_tiles(self.model, self.output, self.quiet)
        _, parts = read_export(self.output)
        pbr = parts[0]['material']['pbrMetallicRoughness']
        self.assertEqual(pbr.get('metallicFactor', 1), 1)
        self.assertEqual(pbr.get('roughnessFactor', 1), 1)

    def test_unsupported_texture_sampler_is_not_written_as_invalid_gltf(self):
        textured_triangle(self.model)
        edit_glb(self.model, lambda doc: doc['samplers'][0].update(wrapS=10496))
        with self.assertRaisesRegex(ValueError, 'wrapS'):
            export_tiles(self.model, self.output, self.quiet)

    def test_nested_tile_transform_mirror_and_texture_transform_are_baked_once(self):
        matrix = np.diag([-2., 3., 1., 1.]); matrix[:3, 3] = [3, 4, 5]
        textured_triangle(self.model, matrix)
        def texture_transform(doc):
            doc['materials'][0]['pbrMetallicRoughness']['baseColorTexture']['extensions'] = {
                'KHR_texture_transform': {'scale': [2, .5], 'offset': [.25, .1], 'rotation': .2}}
        edit_glb(self.model, texture_transform)
        transform = np.eye(4); transform[:3, 3] = [1e6+.25, 2e6+.5, 30.75]
        tile = {'boundingVolume': {'sphere': [0, 0, 0, 30]}, 'geometricError': 0,
                'transform': transform.T.reshape(-1).tolist(), 'content': {'uri': '模型.glb'}}
        source = self.source / 'tileset.json'
        source.write_text(json.dumps({'asset': {'version': '1.1'}, 'root': tile}), encoding='utf-8')
        export_tiles(source, self.output, self.quiet)
        _, parts = read_export(self.output)
        with Glb(self.model) as model: expected = next(model.primitives(transform))
        for key in ('positions', 'indices', 'uv', 'normals'):
            np.testing.assert_allclose(parts[0][key], expected[key], rtol=0, atol=1e-7)

    def test_ktx2_decodes_at_original_size_and_rejects_resized_decoder_output(self):
        png = textured_triangle(self.model)
        (self.source / 'texture.png').write_bytes(png)
        self.quiet.run([RUNTIME / 'ktx.exe', 'create', '--format', 'R8G8B8A8_SRGB', '--encode',
                        'uastc', '--threads', '1', 'texture.png', 'texture.ktx2'], self.source)
        def external_ktx(doc):
            doc['images'][0] = {'uri': 'texture.ktx2', 'mimeType': 'image/ktx2'}
            doc['textures'][0].pop('source')
            doc['textures'][0]['extensions'] = {'KHR_texture_basisu': {'source': 0}}
        edit_glb(self.model, external_ktx)
        export_tiles(self.model, self.output, self.quiet)
        tree, parts = read_export(self.output)
        with Glb(obj_nodes(tree)[0].source) as model:
            data, ext, _ = model.image(parts[0]['texture'])
            self.assertEqual(ext, '.png')
            with Image.open(io.BytesIO(data)) as image: self.assertEqual(image.size, (19, 11))
        def faulty_decode(command, cwd):
            Image.new('RGBA', (2, 2)).save(Path(cwd) / 'texture.png')
        faulty = Control(lambda *args: None); faulty.run = faulty_decode
        with self.assertRaisesRegex(ValueError, '尺寸'):
            export_tiles(self.model, self.root / 'bad_ktx', faulty)

    def test_corrupt_glb_is_rejected_before_success(self):
        textured_triangle(self.model)
        original = _GlbWriter.finish
        def corrupt(writer, path):
            original(writer, path)
            path.write_bytes(path.read_bytes()[:-4])
        with patch.object(_GlbWriter, 'finish', corrupt):
            with self.assertRaises(ValueError): export_tiles(self.model, self.output, self.quiet)
        result = json.loads((self.output / 'mesh_result.json').read_text(encoding='utf-8'))
        self.assertEqual(result['state'], 'failed')
        self.assertEqual(result['code'], 1)

    def test_corrupt_group_bounds_are_rejected_before_success(self):
        textured_triangle(self.model)
        def corrupt(message, percent):
            if percent == 95:
                path = self.output / '3dtiles' / 'tileset.json'
                doc = json.loads(path.read_text(encoding='utf-8'))
                doc['root']['boundingVolume']['box'][3:] = [0.] * 9
                path.write_text(json.dumps(doc), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, '包围体'):
            export_tiles(self.model, self.output, Control(corrupt))
        result = json.loads((self.output / 'mesh_result.json').read_text(encoding='utf-8'))
        self.assertEqual(result['state'], 'failed')

    def test_clip_generates_interpolated_vertices_uv_and_normals(self):
        textured_triangle(self.model)
        box = [.25, -1, .25, 1.25, 1, 1.25]
        with Glb(self.model) as model: expected = clip_primitive(next(model.primitives()), box)
        convert(self.model, self.output, '3dtiles', self.quiet, box)
        _, parts = read_export(self.output)
        for key in ('positions', 'indices', 'uv', 'normals'):
            np.testing.assert_allclose(parts[0][key], expected[key], atol=1e-7)

    def test_replace_uses_final_leaf_while_add_keeps_parent(self):
        for refine, triangles in [('REPLACE', 1), ('ADD', 2)]:
            with self.subTest(refine=refine):
                textured_triangle(self.model)
                child = self.source / '分块'; child.mkdir(exist_ok=True)
                textured_triangle(child / 'fine.glb')
                tile = {'boundingVolume': {'sphere': [0, 0, 0, 20]}, 'geometricError': 10,
                        'refine': refine, 'content': {'uri': '模型.glb'}, 'children': [
                            {'boundingVolume': {'sphere': [0, 0, 0, 20]}, 'geometricError': 0,
                             'content': {'uri': '分块/fine.glb'}}]}
                source = self.source / 'tileset.json'
                source.write_text(json.dumps({'asset': {'version': '1.1'}, 'root': tile}), encoding='utf-8')
                output = self.root / refine
                report = export_tiles(source, output, self.quiet)
                tree, parts = read_export(output)
                self.assertEqual(sum(len(p['indices']) for p in parts), triangles)
                self.assertEqual(report['quality']['triangles'], triangles)
                self.assertTrue((output / '3dtiles' / '分块' / 'fine.glb').is_file())
                self.assertTrue(all(t.error == 0 for t in obj_nodes(tree)))

    def test_source_and_existing_output_are_protected(self):
        textured_triangle(self.model)
        with self.assertRaises(ValueError): export_tiles(self.model, self.source / 'out', self.quiet)
        self.output.mkdir(); sentinel = self.output / 'keep.txt'; sentinel.write_text('keep')
        with self.assertRaises(ValueError): export_tiles(self.model, self.output, self.quiet)
        self.assertEqual(sentinel.read_text(), 'keep')

    def test_empty_clip_and_cancellation_never_publish_success(self):
        textured_triangle(self.model)
        with self.assertRaises(ValueError):
            export_tiles(self.model, self.output, self.quiet, [10, 10, 10, 20, 20, 20])
        result = json.loads((self.output / 'mesh_result.json').read_text(encoding='utf-8'))
        self.assertEqual(result['state'], 'failed')
        event = threading.Event()
        def cancel(message, percent):
            if '[' in message: event.set()
        cancelled = self.root / 'cancelled'
        with self.assertRaises(Cancelled): export_tiles(self.model, cancelled, Control(cancel, event))
        result = json.loads((cancelled / 'mesh_result.json').read_text(encoding='utf-8'))
        self.assertEqual(result['state'], 'cancelled')

    def test_native_obj_and_osgb_prepared_paths_export(self):
        textured_triangle(self.model)
        intermediate = self.root / 'native'
        convert(self.model, intermediate, 'both', self.quiet)
        for fmt in ('obj', 'osgb'):
            with self.subTest(fmt=fmt):
                out = self.root / ('from_' + fmt)
                report = convert(intermediate / fmt / ('Model.' + fmt), out, '3dtiles', self.quiet)
                tree, parts = read_export(out)
                self.assertEqual(report['state'], 'succeeded')
                self.assertEqual(sum(len(p['indices']) for p in parts), 1)
                self.assertTrue(all(p['texture'] is not None for p in parts))
                np.testing.assert_allclose(parts[0]['color'], [.8, .7, .6, .4], atol=1e-6)
                with Glb(self.model) as model: expected = next(model.primitives())
                self.assertIsNotNone(parts[0]['normals'])
                np.testing.assert_allclose(parts[0]['normals'], expected['normals'], atol=1e-6)
                with Glb(self.model) as model:
                    expected_pixels, _, _ = model.image(expected['texture'])
                with Glb(obj_nodes(tree)[0].source) as model:
                    actual_pixels, _, sampler = model.image(parts[0]['texture'])
                with Image.open(io.BytesIO(expected_pixels)) as before, Image.open(io.BytesIO(actual_pixels)) as after:
                    np.testing.assert_array_equal(np.array(after), np.array(before))
                if fmt == 'osgb':
                    self.assertEqual(parts[0]['material']['alphaMode'], 'MASK')
                    self.assertAlmostEqual(parts[0]['material']['alphaCutoff'], .3, places=6)
                    self.assertTrue(parts[0]['material']['doubleSided'])
                    self.assertIn('KHR_materials_unlit', parts[0]['material']['extensions'])
                    self.assertEqual(sampler['wrapS'], 33071)
                else:
                    self.assertEqual(parts[0]['material']['alphaMode'], 'BLEND')

    def test_native_osgb_blend_and_single_sided_state_survive(self):
        textured_triangle(self.model)
        def blend(doc):
            material = doc['materials'][0]
            material.update(alphaMode='BLEND', doubleSided=False)
            material.pop('alphaCutoff')
        edit_glb(self.model, blend)
        intermediate = self.root / 'native'
        convert(self.model, intermediate, 'osgb', self.quiet)
        convert(intermediate / 'osgb' / 'Model.osgb', self.output, '3dtiles', self.quiet)
        _, parts = read_export(self.output)
        self.assertEqual(parts[0]['material']['alphaMode'], 'BLEND')
        self.assertFalse(parts[0]['material']['doubleSided'])
        np.testing.assert_allclose(parts[0]['color'], [.8, .7, .6, .4], atol=1e-6)

    def test_obj_normal_indices_without_texture_coordinates_survive(self):
        obj = self.source / 'model.obj'
        obj.write_text('v 0 0 0\nv 1 0 0\nv 0 1 0\nvn 0 0 1\nf 1//1 2//1 3//1\n')
        convert(obj, self.output, '3dtiles', self.quiet)
        _, parts = read_export(self.output)
        self.assertIsNone(parts[0]['uv'])
        self.assertIsNotNone(parts[0]['normals'])
        np.testing.assert_allclose(parts[0]['normals'], [[0, 0, 1]]*3, atol=1e-7)

    def test_native_nonuniform_mirror_transforms_normals_and_winding(self):
        scene = self.source / 'scene.osgt'; native_scene(scene)
        mesh = self.root / 'prepared'
        write_json(self.root / 'read.json', {'source': str(scene), 'output': str(mesh)})
        self.quiet.run([RUNTIME / 'mesh_reader.exe', 'read.json'], self.root)
        with Mesh(mesh / 'model.mesh') as model: part = next(model.primitives())
        np.testing.assert_allclose(part['positions'], [[5, 6, 7], [5, 9, 7], [3, 6, 7]])
        normal = np.array([-.5, 1/3, .25]); normal /= np.linalg.norm(normal)
        self.assertIsNotNone(part['normals'])
        np.testing.assert_allclose(part['normals'], [normal]*3, atol=1e-7)
        np.testing.assert_allclose(part['color'], [.2, .3, .4, .5], atol=1e-7)

    def test_native_varying_vertex_colors_are_not_silently_discarded(self):
        scene = self.source / 'scene.osgt'; native_scene(scene, varying=True)
        write_json(self.root / 'read.json', {'source': str(scene), 'output': str(self.root / 'prepared')})
        with self.assertRaisesRegex(RuntimeError, 'color'):
            self.quiet.run([RUNTIME / 'mesh_reader.exe', 'read.json'], self.root)


if __name__ == '__main__': unittest.main()
