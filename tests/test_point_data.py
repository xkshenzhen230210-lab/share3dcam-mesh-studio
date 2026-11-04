import json
import struct
import tempfile
import unittest
from unittest import mock
from pathlib import Path

import laspy
import numpy as np
from laspy.vlrs.vlrlist import VLRList

import point_data
from point_data import is_point_source, point_info, prepare_points, crop_points


class Quiet:
    def check(self):
        pass

    def log(self, *args):
        pass


def make_ply(path, values, fields, endian='<', comments=''):
    dtype = np.dtype([(name, endian + code) for name, code in fields])
    names = {'f4': 'float', 'f8': 'double', 'u1': 'uchar', 'u2': 'ushort', 'i4': 'int'}
    header = 'ply\nformat binary_' + ('little' if endian == '<' else 'big') + '_endian 1.0\n'
    header += comments + f'element vertex {len(values)}\n'
    header += ''.join(f'property {names[code]} {name}\n' for name, code in fields) + 'end_header\n'
    array = np.array(values, dtype=dtype)
    path.write_bytes(header.encode('ascii') + array.tobytes())
    return array, header.encode('ascii')


class PointDataTests(unittest.TestCase):
    def test_gaussian_layout_activations_sh_order_and_preview_cap(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fields = [(x, 'f4') for x in ['x', 'y', 'z', 'f_dc_0', 'f_dc_1', 'f_dc_2', 'opacity',
                      'scale_0', 'scale_1', 'scale_2', 'rot_0', 'rot_1', 'rot_2', 'rot_3']]
            fields += [(f'f_rest_{i}', 'f4') for i in range(9)]
            values = [(1, 2, 3, 1, 0, -1, 0, 0, np.log(2), np.log(3), 2, 0, 0, 0, *range(9)),
                      (5, 6, 7, 0, 0, 0, 2, 0, 0, 0, 1, 0, 0, 0, *range(9))]
            make_ply(root/'model.ply', values, fields)
            manifest = prepare_points(root/'model.ply', root/'view', Quiet())
            doc = json.loads(manifest.read_text())
            self.assertEqual(doc['kind'], 'gaussian')
            self.assertEqual(doc['stride_floats'], 62)
            self.assertEqual(doc['sh_degree'], 1)
            self.assertEqual(doc['bounds'], [[1, 2, 3], [5, 6, 7]])
            packed = np.fromfile(manifest.parent/doc['data'], dtype='<f4').reshape(-1, 62)
            np.testing.assert_allclose(packed[0, :3] + doc['origin'], [1, 2, 3])
            np.testing.assert_allclose(packed[0, 6:14], [.5, 1, 2, 3, 1, 0, 0, 0], rtol=1e-6)
            np.testing.assert_array_equal(packed[0, 14:26], [1, 0, -1, 0, 3, 6, 1, 4, 7, 2, 5, 8])
            self.assertTrue(np.all(packed[0, 26:] == 0))

    def test_binary_crop_preserves_all_records_fields_endian_and_header_comments(self):
        for endian in ['<', '>']:
            with self.subTest(endian=endian), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                values = [(500000.0001, 2., 3., 255, 111), (500000.0002, 2., 3., 10, 222), (500001., 2., 3., 50, 333)]
                fields = [('x', 'f8'), ('y', 'f8'), ('z', 'f8'), ('red', 'u1'), ('custom_id', 'i4')]
                records, _ = make_ply(root/'source.ply', values, fields, endian, 'comment original comment\n')
                result = crop_points(root/'source.ply', root/'out', [500000., 1, 2, 500000.00015, 3, 4], Quiet())
                output = Path(result['output'])
                header, raw = output.read_bytes().split(b'end_header\n', 1)
                self.assertEqual(raw, records[:1].tobytes())
                self.assertIn(b'comment original comment', header)
                self.assertEqual(result['quality']['state'], 'passed')
                self.assertEqual(result['count'], 1)

    def test_ascii_crop_keeps_selected_numeric_spelling_and_custom_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            header = b'ply\r\nformat ascii 1.0\r\nelement vertex 3\r\nproperty double x\r\nproperty float y\r\nproperty float z\r\nproperty int label\r\nend_header\r\n'
            rows = [b'1.000000000001 0 0 42\r\n', b'2e0 0.0 0 99\r\n', b'3 0 0 -3\r\n']
            (root/'source.ply').write_bytes(header + b''.join(rows))
            result = crop_points(root/'source.ply', root/'out', [.5, -1, -1, 1.5, 1, 1], Quiet())
            self.assertTrue(Path(result['output']).read_bytes().endswith(rows[0]))
            manifest = prepare_points(root/'source.ply', root/'view', Quiet())
            self.assertEqual(json.loads(manifest.read_text())['count'], 3)

    def test_full_export_is_byte_identical_and_does_not_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            make_ply(root/'source.ply', [(1, 2, 3)], [(x, 'f4') for x in ['x', 'y', 'z']])
            result = crop_points(root/'source.ply', root/'out', None, Quiet())
            self.assertEqual(Path(result['output']).read_bytes(), (root/'source.ply').read_bytes())
            with self.assertRaises(FileExistsError):
                crop_points(root/'source.ply', root/'out', None, Quiet())

    def test_mesh_ply_routes_to_existing_mesh_reader(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'mesh.ply'
            path.write_bytes(b'ply\nformat ascii 1.0\nelement vertex 3\nproperty float x\nproperty float y\nproperty float z\nelement face 1\nproperty list uchar int vertex_indices\nend_header\n0 0 0\n1 0 0\n0 1 0\n3 0 1 2\n')
            self.assertFalse(is_point_source(path))

    def test_truncated_ply_empty_clip_and_cancel_never_publish_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            make_ply(root/'source.ply', [(1, 2, 3)], [(x, 'f4') for x in ['x', 'y', 'z']])
            with self.assertRaises(ValueError):
                crop_points(root/'source.ply', root/'empty', [10, 10, 10, 11, 11, 11], Quiet())
            self.assertFalse(list((root/'empty').glob('*.ply')))
            broken = root/'broken.ply'
            broken.write_bytes((root/'source.ply').read_bytes()[:-1])
            with self.assertRaises(ValueError):
                prepare_points(broken, root/'view', Quiet())
            self.assertFalse(list((root/'view').glob('*.spoints')))
            class Cancel(Quiet):
                def check(self):
                    raise RuntimeError('cancelled')
            with self.assertRaisesRegex(RuntimeError, 'cancelled'):
                prepare_points(root/'source.ply', root/'cancel', Cancel())

    def test_las_crop_preserves_scaled_records_extra_dimensions_vlr_and_evlr(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            header = laspy.LasHeader(point_format=7, version='1.4')
            header.scales = np.array([.0001, .0002, .0003])
            header.offsets = np.array([500000., 4000000., 10.])
            header.add_extra_dim(laspy.ExtraBytesParams(name='custom_score', type='f8'))
            header.vlrs.append(laspy.VLR(user_id='TEST', record_id=42, description='payload', record_data=b'unchanged-vlr'))
            header.evlrs = VLRList([laspy.VLR(user_id='TEST', record_id=43, description='evlr', record_data=b'unchanged-evlr')])
            las = laspy.LasData(header)
            las.x = np.array([500000.0001, 500000.0002, 500002])
            las.y = np.array([4000000., 4000000., 4000000.])
            las.z = np.array([10., 10., 10.])
            las.red = [65535, 1024, 0]
            las.green = [0, 12345, 65535]
            las.blue = [42, 43, 44]
            las.classification = [2, 3, 4]
            las.gps_time = [100.1, 100.2, 100.3]
            las.custom_score = [1.234567890123, 9, -1]
            las.write(root/'source.las')
            # Some upstream writers leave optional Extra Bytes min/max at zero.
            # laspy rewrites those bytes during filtering unless restored.
            with (root/'source.las').open('r+b') as stream:
                stream.seek(94)
                header_size = struct.unpack('<H', stream.read(2))[0]
                stream.seek(header_size + 54 + 64)
                stream.write(bytes(48))
            result = crop_points(root/'source.las', root/'out', [499999, 3999999, 9, 500000.00015, 4000001, 11], Quiet())
            out = laspy.read(result['output'])
            self.assertEqual(out.points.array.tobytes(), las.points.array[:1].tobytes())
            np.testing.assert_array_equal(out.header.scales, header.scales)
            np.testing.assert_array_equal(out.header.offsets, header.offsets)
            self.assertEqual(out.header.vlrs[-1].record_data_bytes(), b'unchanged-vlr')
            self.assertEqual(out.header.evlrs[0].record_data_bytes(), b'unchanged-evlr')
            doc = json.loads(prepare_points(root/'source.las', root/'view', Quiet()).read_text())
            self.assertEqual(doc['stride_floats'], 7)
            self.assertEqual(doc['count'], 3)

    def test_preview_sampling_is_global_bounded_and_full_mode_keeps_all(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            count = 300005
            array = np.zeros(count, dtype=[('x', '<f8'), ('y', '<f8'), ('z', '<f8')])
            array['x'] = np.arange(count) + 1e9
            header = f'ply\nformat binary_little_endian 1.0\nelement vertex {count}\nproperty double x\nproperty double y\nproperty double z\nend_header\n'.encode()
            (root/'source.ply').write_bytes(header + array.tobytes())
            doc = json.loads(prepare_points(root/'source.ply', root/'preview', Quiet(), preview=True).read_text())
            self.assertLessEqual(doc['count'], 300000)
            self.assertTrue(doc['sampled'])
            self.assertEqual(doc['source_count'], count)
            self.assertEqual(doc['bounds'][1][0], 1e9 + count - 1)
            preview_points = np.fromfile(root/'preview'/doc['data'], dtype='<f4').reshape(-1, 7)
            np.testing.assert_array_equal(np.diff(preview_points[:, 0]), 2)
            full = json.loads(prepare_points(root/'source.ply', root/'full', Quiet()).read_text())
            self.assertEqual(full['count'], count)
            self.assertFalse(full['sampled'])

    def test_header_inspection_does_not_read_points(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp)/'points.ply'
            make_ply(source, [(1, 2, 3)], [(x, 'f4') for x in ['x', 'y', 'z']])
            with mock.patch.object(point_data._PlySource, 'chunks', side_effect=AssertionError('payload scanned')):
                info = point_info(source)
            self.assertEqual(info['kind'], 'points')
            self.assertEqual(info['count'], 1)
            self.assertIsNone(info['bounds'])

    def test_background_quality_repairs_damage_and_never_publishes_persistent_damage(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            make_ply(root/'source.ply', [(1, 2, 3)], [(x, 'f4') for x in ['x', 'y', 'z']])
            verify = point_data._verify_crop
            attempts = []
            def damage_once(reader, output, *args):
                attempts.append(output)
                if len(attempts) == 1:
                    raw = bytearray(output.read_bytes())
                    raw[-1] ^= 1
                    output.write_bytes(raw)
                return verify(reader, output, *args)
            with mock.patch.object(point_data, '_verify_crop', side_effect=damage_once):
                result = crop_points(root/'source.ply', root/'repair', [0, 0, 0, 4, 4, 4], Quiet())
            self.assertEqual(result['quality']['repairs'], 1)
            self.assertEqual(result['quality']['state'], 'passed')
            with mock.patch.object(point_data, '_verify_crop', side_effect=point_data.PointQualityError('persistent damage')):
                with self.assertRaises(point_data.PointQualityError):
                    crop_points(root/'source.ply', root/'broken', [0, 0, 0, 4, 4, 4], Quiet())
            self.assertFalse((root/'broken/source.ply').exists())
            self.assertEqual(json.loads((root/'broken/point_result.json').read_text())['state'], 'failed')


if __name__ == '__main__':
    unittest.main()
