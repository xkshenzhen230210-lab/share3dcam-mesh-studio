import hashlib
from pathlib import Path
import tempfile
import threading
import unittest
import numpy as np

from auto_wall import measure_scan
from converter import Control, Cancelled
from tests.test_wall_flatness import write_las
from tests.test_wall_segmentation import surface


class AutoWallTests(unittest.TestCase):
    def test_tolerance_changes_judgement_without_changing_membership_or_reference(self):
        with tempfile.TemporaryDirectory() as tmp:
            source=Path(tmp)/'survey.las';xyz=surface()
            xyz[:,1]=.003*np.cos(xyz[:,0]*4);write_las(source,xyz)
            low,_=measure_scan(source,tolerance_mm=1,control=Control(lambda *_:None))
            high,_=measure_scan(source,tolerance_mm=5,control=Control(lambda *_:None))
            self.assertEqual(low['assigned_count'],high['assigned_count'])
            for a,b in zip(low['walls'],high['walls']):
                np.testing.assert_array_equal(a['normal'],b['normal'])
                np.testing.assert_array_equal(a['centroid'],b['centroid'])
                self.assertEqual(a['max_abs_mm'],b['max_abs_mm'])
                self.assertGreater(a['outside_count'],b['outside_count'])
                self.assertEqual(b['outside_count'],0)

    def test_full_point_statistics_reconcile_and_match_independent_plane(self):
        with tempfile.TemporaryDirectory() as tmp:
            source=Path(tmp)/'survey.las';xyz=surface()
            xyz[:,1]=.001*np.sin(xyz[:,0]*4)
            xyz[1000:1050,1]+=.02
            xyz=np.vstack([xyz,surface(y=4)])
            write_las(source,xyz)
            before=hashlib.sha256(source.read_bytes()).hexdigest()
            report,assets=measure_scan(source,tolerance_mm=5,zone_size_m=1)
            self.assertEqual(len(report['walls']),2)
            self.assertEqual(report['assigned_count']+report['unassigned_count'],len(xyz))
            self.assertEqual(sum(w['count'] for w in report['walls']),report['assigned_count'])
            self.assertEqual(sum(z['count'] for w in report['walls'] for z in w['zones']),report['assigned_count'])
            self.assertGreater(sum(w['outside_count'] for w in report['walls']),0)
            for wall in report['walls']:
                selected=xyz[np.abs(xyz[:,1]-wall['centroid'][1])<.2]
                center=selected.mean(axis=0);_,_,vt=np.linalg.svd(selected-center,full_matrices=False)
                d=(selected-center)@vt[-1]*1000
                self.assertAlmostEqual(wall['rms_mm'],np.sqrt(np.mean(d*d)),places=3)
                self.assertAlmostEqual(wall['max_abs_mm'],max(abs(d)),places=3)
            self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(),before)
            self.assertEqual(len(assets['sample']),len(xyz))

    def test_units_translation_no_wall_and_cancel(self):
        with tempfile.TemporaryDirectory() as tmp:
            source=Path(tmp)/'survey.las';xyz=surface()
            xyz[:,1]=.002*np.sin(xyz[:,0]*4)
            write_las(source,(xyz+[500000,4000000,100])*1000)
            report,_=measure_scan(source,unit='mm')
            self.assertEqual(len(report['walls']),1)
            self.assertLess(report['walls'][0]['rms_mm'],2.1)
            event=threading.Event();event.set()
            with self.assertRaises(Cancelled):measure_scan(source,control=Control(event=event))
            write_las(source,surface()[:,[0,2,1]])
            report,_=measure_scan(source)
            self.assertEqual(report['walls'],[])
            self.assertEqual(report['unassigned_count'],report['source_count'])
            for opts in ({'unit':'bad'},{'tolerance_mm':0},{'zone_size_m':float('nan')}):
                with self.assertRaises(ValueError):measure_scan(source,**opts)


if __name__=='__main__':unittest.main()
