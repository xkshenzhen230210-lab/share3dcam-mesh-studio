"""Native OSGB texture-sharing regressions without reducing source quality.

Fixtures are made by the production mesh_writer. Every leaf is independently
serialized with a full 1024x1024 RGBA texture and its own Texture2D. The root
contains PagedLOD references, exercising the renderer's full-detail page loader.

Final progress.memory reports decoded unique-object totals before sharing and
after sharing (before CPU upload buffers are released): image_bytes_before,
image_bytes_after, images_before, images_after, textures_before, textures_after.
These totals are object allocations, not geometry bindings or process RSS.
"""
import json
import os
from pathlib import Path
import struct
import subprocess
import tempfile
import unittest

import numpy as np
from PIL import Image

from converter import RUNTIME


REPEAT = 10497
CLAMP_TO_EDGE = 33071
NEAREST = 9728
LINEAR = 9729
TEXTURE_SIDE = 1024
TEXTURE_BYTES = TEXTURE_SIDE * TEXTURE_SIDE * 4


class RenderMemoryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='share_render_memory_')
        self.addCleanup(self.temporary.cleanup)
        self.folder = Path(self.temporary.name)
        self.env = os.environ.copy()
        self.env['PATH'] = str(RUNTIME) + os.pathsep + self.env.get('PATH', '')
        self.env['OSG_LIBRARY_PATH'] = str(RUNTIME/'osgPlugins-3.6.5')
        self.render_number = 0
        self.pose = dict(eye=[0, -7, 0], center=[0, 0, 0], up=[0, 0, 1], fovy=45)

    def run_native(self, name, arguments, cwd):
        result = subprocess.run([str(RUNTIME/(name+'.exe')), *map(str, arguments)],
                                cwd=cwd, env=self.env, capture_output=True, timeout=45,
                                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        self.assertEqual(result.returncode, 0, result.stderr.decode(errors='replace')[-4000:])
        return result

    @staticmethod
    def patterned_texture():
        # A genuine full-resolution image; high-frequency stripes make hidden
        # downsampling visible when sampled with the explicit UV fixtures.
        y, x = np.indices((TEXTURE_SIDE, TEXTURE_SIDE))
        pixels = np.empty((TEXTURE_SIDE, TEXTURE_SIDE, 4), dtype=np.uint8)
        pixels[:, :, 0] = (x*17+y*3) % 256
        pixels[:, :, 1] = (y*11) % 256
        pixels[:, :, 2] = (x ^ y) % 256
        pixels[:, :, 3] = 255
        return pixels

    def leaf(self, name, pixels, center=0., uv=None, wrap=REPEAT, mag=NEAREST,
             minimum=NEAREST, texture_bytes=None):
        folder = self.folder/name
        folder.mkdir()
        # All independent pages intentionally use the exact same image name.
        texture_name = 'texture.png' if texture_bytes is None else 'texture.dds'
        if texture_bytes is None:
            Image.fromarray(pixels).save(folder/texture_name)
        else:
            (folder/texture_name).write_bytes(texture_bytes)
        positions = np.array([[center-.5, 0, -.8], [center+.5, 0, -.8],
                              [center+.5, 0, .8], [center-.5, 0, .8]], dtype='<f8')
        coordinates = np.array(uv if uv is not None else [[0, 0], [1, 0], [1, 1], [0, 1]], dtype='<f4')
        indices = np.array([0, 1, 2, 0, 2, 3], dtype='<u4')
        (folder/'geometry.bin').write_bytes(positions.tobytes()+coordinates.tobytes()+indices.tobytes())
        primitive = dict(offset=0, vertices=4, indices=6, uv=True, normals=False,
                         color=[1, 1, 1, 1], doubleSided=True, texture=texture_name,
                         wrapS=wrap, wrapT=REPEAT, minFilter=minimum, magFilter=mag)
        (folder/'write.json').write_text(json.dumps(dict(
            buffer='geometry.bin', primitives=[primitive], output='leaf.osgb')))
        self.run_native('mesh_writer', ['write', 'write.json'], folder)
        return folder/'leaf.osgb'

    def paged_root(self, leaves, name='root.osgb'):
        children = [dict(path=leaf.relative_to(self.folder).as_posix(), center=[0, 0, 0], radius=4)
                    for leaf in leaves]
        job = self.folder/(name+'.json')
        job.write_text(json.dumps(dict(output=name, children=children)))
        self.run_native('mesh_writer', ['write', job.name], self.folder)
        root = self.folder/name
        info = json.loads(self.run_native('mesh_writer', ['inspect', root.name], self.folder).stdout)
        self.assertEqual(len(info['references']), len(leaves), 'Fixture must actually contain paged references')
        return root

    def render(self, source, optimize=True):
        self.render_number += 1
        folder = self.folder/f'render_{self.render_number}'
        folder.mkdir()
        job = dict(source=str(source), width=128, height=128, fps=30,
                   frames=[self.pose, self.pose], progress=str(folder/'progress.json'),
                   optimize_memory=optimize)
        (folder/'job.json').write_text(json.dumps(job))
        result = self.run_native('mesh_render', ['job.json'], folder)
        progress = json.loads((folder/'progress.json').read_text())
        self.assertEqual(progress['state'], 'succeeded')
        self.assertEqual(progress['frame'], 2)
        frames = np.frombuffer(result.stdout, dtype=np.uint8).reshape(2, 128, 128, 3)
        np.testing.assert_array_equal(frames[0], frames[1], 'Releasing CPU images must not alter later frames')
        self.assertEqual(list((folder/'texture_cache').glob('**/*')), [],
                         'A completed renderer must leave no mapped pixel files behind')
        return frames[0], progress

    def memory(self, progress):
        self.assertIn('memory', progress, 'Renderer must expose lossless texture-sharing counters')
        memory = progress['memory']
        for key in ('image_bytes_before', 'image_bytes_after', 'images_before',
                    'images_after', 'textures_before', 'textures_after',
                    'mapped_image_bytes', 'image_bytes_after_upload'):
            self.assertIn(key, memory)
            self.assertIsInstance(memory[key], int)
            self.assertGreaterEqual(memory[key], 0)
        return memory

    def assert_matches_separate_pages(self, combined, references):
        background = references[0][0, 0]
        expected = np.broadcast_to(background, combined.shape).copy()
        occupied = np.zeros(combined.shape[:2], dtype=bool)
        for reference in references:
            visible = np.any(reference != background, axis=2)
            self.assertGreater(int(visible.sum()), 100, 'Each fixture page must contribute visible pixels')
            self.assertFalse(np.any(occupied & visible), 'Reference quads must not overlap')
            expected[visible] = reference[visible]
            occupied |= visible
        np.testing.assert_array_equal(combined, expected, 'Sharing must preserve every rendered pixel')

    def test_identical_full_resolution_images_and_textures_share_across_pages(self):
        pixels = self.patterned_texture()
        # 32 independently decoded 4 MiB RGBA textures = 128 MiB before sharing.
        leaves = [self.leaf(f'page_{i:02}', pixels) for i in range(32)]
        reference, _ = self.render(leaves[0])
        combined, progress = self.render(self.paged_root(leaves))
        np.testing.assert_array_equal(combined, reference)
        self.assertGreater(np.unique(reference.reshape(-1, 3), axis=0).shape[0], 100)
        memory = self.memory(progress)
        self.assertEqual(memory['images_before'], 32)
        self.assertEqual(memory['textures_before'], 32)
        self.assertEqual(memory['image_bytes_before'], 32*TEXTURE_BYTES)
        self.assertEqual(memory['images_after'], 1)
        self.assertEqual(memory['textures_after'], 1)
        self.assertEqual(memory['image_bytes_after'], TEXTURE_BYTES)
        self.assertEqual(memory['mapped_image_bytes'], TEXTURE_BYTES)
        self.assertEqual(memory['image_bytes_after_upload'], 0)

    def test_same_image_filename_with_different_pixels_is_not_merged(self):
        red = np.full((TEXTURE_SIDE, TEXTURE_SIDE, 4), [230, 20, 30, 255], dtype=np.uint8)
        green = np.full_like(red, [15, 220, 60, 255])
        leaves = [self.leaf('red_page', red, center=-.7), self.leaf('green_page', green, center=.7)]
        references = [self.render(leaf)[0] for leaf in leaves]
        combined, progress = self.render(self.paged_root(leaves))
        self.assert_matches_separate_pages(combined, references)
        memory = self.memory(progress)
        self.assertEqual(memory['images_before'], 2)
        self.assertEqual(memory['images_after'], 2)
        self.assertEqual(memory['textures_after'], 2)
        self.assertEqual(memory['image_bytes_after'], 2*TEXTURE_BYTES)
        self.assertEqual(memory['mapped_image_bytes'], 2*TEXTURE_BYTES)
        self.assertEqual(memory['image_bytes_after_upload'], 0)

    def test_equal_images_keep_distinct_wrap_and_filter_state(self):
        pixels = np.full((TEXTURE_SIDE, TEXTURE_SIDE, 4), [240, 10, 20, 255], dtype=np.uint8)
        pixels[:, TEXTURE_SIDE//2:] = [10, 230, 40, 255]
        boundary = .5 + .25/TEXTURE_SIDE
        specs = [(-1.8, 1.25, REPEAT, NEAREST), (-.6, 1.25, CLAMP_TO_EDGE, NEAREST),
                 (.6, boundary, REPEAT, LINEAR), (1.8, boundary, REPEAT, NEAREST)]
        leaves = [self.leaf(f'sampler_{i}', pixels, center=x, uv=[[u, .5]]*4, wrap=wrap, mag=mag)
                  for i, (x, u, wrap, mag) in enumerate(specs)]
        references = [self.render(leaf)[0] for leaf in leaves]
        combined, progress = self.render(self.paged_root(leaves))
        self.assert_matches_separate_pages(combined, references)
        # The fixture must distinguish nearest vs linear, not just object IDs.
        colors = []
        for reference in references:
            mask = np.any(reference != reference[0, 0], axis=2)
            colors.append(np.median(reference[mask], axis=0))
        self.assertGreater(colors[0][0], colors[0][1]+100)
        self.assertGreater(colors[1][1], colors[1][0]+100)
        self.assertGreater(np.linalg.norm(colors[2]-colors[3]), 30)
        memory = self.memory(progress)
        self.assertEqual(memory['images_before'], 4)
        self.assertEqual(memory['images_after'], 1)
        self.assertEqual(memory['image_bytes_after'], TEXTURE_BYTES)
        self.assertEqual(memory['textures_before'], 4)
        # Two repeat/nearest objects can share; clamp and linear must remain separate.
        self.assertEqual(memory['textures_after'], 3)
        self.assertEqual(memory['mapped_image_bytes'], TEXTURE_BYTES)
        self.assertEqual(memory['image_bytes_after_upload'], 0)

    def test_mapping_and_upload_release_preserve_unoptimized_pixels(self):
        pixels = self.patterned_texture()
        first = self.leaf('original', pixels, center=-.7)
        second_pixels = pixels.copy()
        second_pixels[:, :, :3] = 255-second_pixels[:, :, :3]
        second = self.leaf('different', second_pixels, center=.7)
        root = self.paged_root([first, second])
        unoptimized, before = self.render(root, optimize=False)
        optimized, after = self.render(root)
        np.testing.assert_array_equal(optimized, unoptimized,
                                      'Disk-backed full-resolution pixels must match the original renderer')
        baseline, actual = self.memory(before), self.memory(after)
        self.assertEqual(baseline['mapped_image_bytes'], 0)
        self.assertEqual(baseline['image_bytes_after_upload'], 2*TEXTURE_BYTES)
        self.assertEqual(actual['mapped_image_bytes'], 2*TEXTURE_BYTES)
        self.assertEqual(actual['image_bytes_after_upload'], 0)

    def test_mapped_files_are_closed_when_renderer_fails_after_loading(self):
        source = self.leaf('failure_source', self.patterned_texture())
        folder = self.folder/'failed_render'
        folder.mkdir()
        # Context-mode validation happens after source loading and mapping but
        # before GL initialization, giving a deterministic exception-cleanup path.
        job = dict(source=str(source), width=128, height=128, fps=30,
                   frames=[self.pose, self.pose], progress=str(folder/'progress.json'),
                   context_mode='invalid-for-cleanup-test')
        (folder/'job.json').write_text(json.dumps(job))
        result = subprocess.run([str(RUNTIME/'mesh_render.exe'), 'job.json'],
                                cwd=folder, env=self.env, capture_output=True, timeout=30,
                                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, b'')
        progress = json.loads((folder/'progress.json').read_text())
        self.assertEqual(progress['state'], 'failed')
        self.assertIn('Invalid graphics context mode', progress['error'])
        self.assertEqual(progress['memory']['mapped_image_bytes'], TEXTURE_BYTES)
        self.assertEqual(list((folder/'texture_cache').glob('**/*')), [],
                         'Exception unwinding must close and delete mapped pixel files')

    def test_full_mipmap_chain_is_preserved_and_distinct_mip_pixels_are_not_merged(self):
        # DDS is only a fixture carrier for precomputed mips. The development
        # SDK supplies its reader; the packaged PNG/JPEG model path is unchanged.
        vendor = Path(__file__).resolve().parents[1]/'vendor/osg'
        plugins = list(vendor.glob('*/bin/osgPlugins-3.6.5/osgdb_dds.dll'))
        if not plugins:
            self.skipTest('DDS fixture creation requires the development OSG DDS plugin')
        self.env['OSG_LIBRARY_PATH'] += os.pathsep + str(plugins[0].parent)

        def dds(mip_color):
            # Uncompressed RGBA DDS, 1024x1024 down to 1x1. Base pixels match;
            # only lower mip levels differ, and minification must display them.
            levels = 11
            header = [124, 0x2100F, 1024, 1024, 4096, 0, levels] + [0]*11
            header += [32, 0x41, 0, 32, 0xFF, 0xFF00, 0xFF0000, 0xFF000000]
            header += [0x401008, 0, 0, 0, 0]
            payload = []
            for level in range(levels):
                side = 1024 >> level
                color = [240, 10, 20, 255] if level == 0 else mip_color
                payload.append(np.full((side, side, 4), color, dtype=np.uint8).tobytes())
            return b'DDS ' + struct.pack('<31I', *header) + b''.join(payload)

        green_dds, blue_dds = dds([10, 230, 40, 255]), dds([10, 30, 240, 255])
        leaves = [self.leaf('green_mips', None, center=-.7, minimum=9984, texture_bytes=green_dds),
                  self.leaf('blue_mips', None, center=.7, minimum=9984, texture_bytes=blue_dds)]
        root = self.paged_root(leaves)
        baseline, _ = self.render(root, optimize=False)
        optimized, progress = self.render(root)
        np.testing.assert_array_equal(optimized, baseline, 'Every precomputed mip must survive disk mapping')
        colors = []
        for leaf in leaves:
            image, _ = self.render(leaf)
            colors.append(np.median(image[np.any(image != image[0, 0], axis=2)], axis=0))
        self.assertGreater(colors[0][1], colors[0][0]+100)
        self.assertGreater(colors[1][2], colors[1][0]+100)
        memory = self.memory(progress)
        self.assertEqual(memory['images_after'], 2, 'Equal base pixels do not imply equal mipmapped images')
        self.assertEqual(memory['textures_after'], 2)
        self.assertEqual(memory['image_bytes_after'], 2*(len(green_dds)-128))
        self.assertEqual(memory['mapped_image_bytes'], 2*(len(green_dds)-128))
        self.assertEqual(memory['image_bytes_after_upload'], 0)


if __name__ == '__main__':
    unittest.main()
