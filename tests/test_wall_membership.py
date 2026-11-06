"""Regression coverage for nearby surfaces contaminating a wall's full-point fit."""
from pathlib import Path
import tempfile
import unittest

import numpy as np

from auto_wall import measure_scan
from tests.test_wall_flatness import write_las
from wall_segmentation import assign_points, detect_walls


def wall_and_nearby_surfaces():
    """A connected 20 mm wall bump, a floor, a return, and a detached fixture.

    The floor and return include points closer to the reference plane than the
    true bump. A distance cutoff cannot distinguish these surface memberships.
    The detached fixture is parallel but too small to be a separate wall.
    """
    x, z = np.meshgrid(np.linspace(0, 3, 121), np.linspace(0, 2.8, 113))
    radius = np.hypot(x - 1.5, z - 1.4)
    height = .020 * np.cos(np.minimum(radius / .35, 1) * np.pi / 2) ** 2
    wall = np.column_stack((x.ravel(), height.ravel(), z.ravel()))
    bump = height.ravel() > .010

    x, y = np.meshgrid(np.linspace(0, 3, 121), np.linspace(.010, .140, 14))
    floor = np.column_stack((x.ravel(), y.ravel(), np.zeros(x.size)))

    y, z = np.meshgrid(np.linspace(.010, .140, 14), np.linspace(.4, 2.4, 81))
    corner = np.column_stack((np.full(y.size, -.015), y.ravel(), z.ravel()))

    x, z = np.meshgrid(np.linspace(.6, .9, 13), np.linspace(1, 1.3, 13))
    fixture = np.column_stack((x.ravel(), np.full(x.size, .090), z.ravel()))
    return wall, bump, {'floor': floor, 'corner return': corner, 'fixture': fixture}


def main_wall_index(walls):
    """Identify the known broad wall by orientation and position, not numbering."""
    matches = [i for i, wall in enumerate(walls)
               if abs(wall['normal'][1]) > .99
               and abs(wall['centroid'][1]) < .04]
    if len(matches) != 1:
        raise AssertionError(f'Expected one main wall, found {len(matches)}')
    return matches[0]


class WallMembershipTests(unittest.TestCase):
    def test_nearby_floor_corner_and_fixture_are_not_wall_members(self):
        wall, _, neighbours = wall_and_nearby_surfaces()
        xyz = np.vstack([wall, *neighbours.values()])
        walls, _ = detect_walls(xyz)
        main = main_wall_index(walls)
        labels, _ = assign_points(xyz, walls)

        offset = len(wall)
        for name, points in neighbours.items():
            with self.subTest(surface=name):
                accepted = np.count_nonzero(labels[offset:offset + len(points)] == main)
                self.assertLessEqual(
                    accepted / len(points), .01,
                    f'{name}: {accepted}/{len(points)} non-wall points entered the wall')
            offset += len(points)

    def test_connected_twenty_mm_bump_survives_surface_segmentation(self):
        wall, bump, neighbours = wall_and_nearby_surfaces()
        xyz = np.vstack([wall, *neighbours.values()])
        walls, _ = detect_walls(xyz)
        main = main_wall_index(walls)
        labels, _ = assign_points(xyz, walls)

        interior = ((wall[:, 0] > .10) & (wall[:, 0] < 2.9)
                    & (wall[:, 2] > .10) & (wall[:, 2] < 2.7))
        self.assertGreaterEqual(np.mean(labels[:len(wall)][interior] == main), .99)
        self.assertTrue(np.all(labels[:len(wall)][bump] == main),
                        'True connected wall defects must not be clipped to improve RMS')

    def test_translation_and_source_normals_do_not_join_a_parallel_fixture(self):
        wall, bump, neighbours = wall_and_nearby_surfaces()
        narrow = ((abs(wall[:, 0] - 2.4) < .03) & (abs(wall[:, 2] - 1.2) < .03))
        wall[narrow, 1] = .020
        xyz = np.vstack([wall, *neighbours.values()])
        normals = np.tile([0., 1., 0.], (len(xyz), 1))
        start = len(wall)
        normals[start:start + len(neighbours['floor'])] = [0., 0., 1.]
        start += len(neighbours['floor'])
        normals[start:start + len(neighbours['corner return'])] = [1., 0., 0.]

        for offset in ([.031, -.127, .083], [500000., 4000000., 100.]):
            with self.subTest(offset=offset):
                translated = xyz + offset
                walls, _ = detect_walls(translated[::2])
                matches = [i for i, candidate in enumerate(walls)
                           if abs(candidate['normal'][1]) > .99
                           and abs(candidate['centroid'][1] - offset[1]) < .04]
                self.assertEqual(len(matches), 1)
                labels, _ = assign_points(translated, walls, normals=normals)
                self.assertTrue(np.all(labels[:len(wall)][bump | narrow] == matches[0]))
                self.assertLessEqual(np.mean(labels[len(wall):] == matches[0]), .01)

    def test_unsampled_parallel_fixture_does_not_attach_across_empty_depth(self):
        wall, bump, neighbours = wall_and_nearby_surfaces()
        # A bounded detection sample may miss the fixture entirely. Its source
        # normals are wall-parallel, so orientation alone is insufficient.
        walls, _ = detect_walls(wall[::2])
        main = main_wall_index(walls)
        fixture = neighbours['fixture']
        query = np.vstack((wall[bump], fixture))
        normals = np.tile([0., 1., 0.], (len(query), 1))
        labels, _ = assign_points(query, walls, normals=normals)
        self.assertTrue(np.all(labels[:np.count_nonzero(bump)] == main))
        self.assertTrue(np.all(labels[np.count_nonzero(bump):] == -1))

    def test_full_las_statistics_match_the_wall_including_its_bump(self):
        wall, bump, neighbours = wall_and_nearby_surfaces()
        xyz = np.vstack([wall, *neighbours.values()])

        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / 'wall-with-adjacent-surfaces.las'
            write_las(source, xyz)
            report, assets = measure_scan(source, tolerance_mm=5, zone_size_m=1)
            main = main_wall_index(report['walls'])
            measured = report['walls'][main]

        # Boundary seams may be ambiguous. The oracle includes every retained
        # known wall point, but never the floor, return, or detached fixture.
        # The separate recall/bump assertions prevent empty or clipped solutions.
        retained_wall = wall[assets['labels'][:len(wall)] == main]
        centered = retained_wall - retained_wall.mean(axis=0)
        _, _, vectors = np.linalg.svd(centered, full_matrices=False)
        distances_mm = centered @ vectors[-1] * 1000
        expected_rms = np.sqrt(np.mean(distances_mm ** 2))
        expected_max = np.max(np.abs(distances_mm))
        expected_outside = np.count_nonzero(np.abs(distances_mm) > 5)

        with self.subTest(metric='RMS of true wall including bump'):
            self.assertAlmostEqual(measured['rms_mm'], expected_rms, delta=.03)
        with self.subTest(metric='maximum defect'):
            self.assertAlmostEqual(measured['max_abs_mm'], expected_max, delta=.10)
        with self.subTest(metric='outside-tolerance wall points'):
            self.assertAlmostEqual(measured['outside_count'], expected_outside,
                                   delta=max(2, expected_outside * .02))
        with self.subTest(metric='retained bump membership'):
            self.assertEqual(report['sample_stride'], 1)
            self.assertTrue(np.all(assets['labels'][:len(wall)][bump] == main))
        with self.subTest(metric='zone counts use the same full wall population'):
            self.assertEqual(sum(zone['count'] for zone in measured['zones']), measured['count'])
            self.assertGreaterEqual(measured['count'], len(retained_wall))
            self.assertLessEqual(measured['count'], 1.01 * len(retained_wall))


if __name__ == '__main__':
    unittest.main()
