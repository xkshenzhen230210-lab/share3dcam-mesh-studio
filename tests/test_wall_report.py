import csv
import hashlib
import json
from pathlib import Path
import tempfile
import threading
import unittest
import numpy as np

from auto_wall import analyze_building
from converter import Control,Cancelled
from tests.test_wall_segmentation import surface
from tests.test_wall_flatness import write_las


class WallReportTests(unittest.TestCase):
    def test_complete_report_matches_metrics_and_preserves_source(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);source=root/'扫描.las';xyz=surface()
            xyz[:,1]=.002*np.sin(xyz[:,0]*4);write_las(source,xyz)
            before=hashlib.sha256(source.read_bytes()).hexdigest()
            r=analyze_building(source,root/'report',metadata={'project':'溪瑞苑 <A&B>'},control=Control(lambda *_:None))
            self.assertEqual(r['state'],'succeeded')
            self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(),before)
            self.assertEqual(json.loads((root/'report/report.json').read_text(encoding='utf-8'))['zone_count'],r['zone_count'])
            with (root/'report/分区统计.csv').open(encoding='utf-8-sig',newline='') as f:rows=list(csv.reader(f))
            self.assertEqual(len(rows)-1,r['zone_count'])
            self.assertEqual(sum(int(row[2]) for row in rows[1:]),r['assigned_count'])
            self.assertIn('溪瑞苑 &lt;A&amp;B&gt;',(root/'report/report.html').read_text(encoding='utf-8'))
            self.assertTrue((root/'report/墙面平整度报告.pdf').read_bytes().startswith(b'%PDF-'))
            self.assertTrue((root/'report/figures/W001.png').is_file())
            cache=json.loads((root/'report/W001/model.spoints').read_text(encoding='utf-8'))
            self.assertEqual(cache['source_count'],r['walls'][0]['count'])
            original=json.loads((root/'report/W001/original/model.spoints').read_text(encoding='utf-8'))
            self.assertEqual(original['source_count'],cache['source_count'])
            colors=np.fromfile(root/'report/W001/points.bin',dtype='<f4').reshape(-1,7)
            raw=np.fromfile(root/'report/W001/original/points.bin',dtype='<f4').reshape(-1,7)
            np.testing.assert_array_equal(colors[:,:3],raw[:,:3])
            self.assertFalse(np.array_equal(colors[:,3:6],raw[:,3:6]))

    def test_cancel_during_report_never_publishes_and_existing_output_is_kept(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);source=root/'source.las';write_las(source,surface())
            event=threading.Event()
            def progress(text,pct):
                if pct>=90:event.set()
            with self.assertRaises(Cancelled):analyze_building(source,root/'canceled',control=Control(progress,event))
            self.assertFalse((root/'canceled').exists())
            target=root/'existing';target.mkdir();(target/'keep.txt').write_text('keep')
            with self.assertRaises(FileExistsError):analyze_building(source,target)
            self.assertEqual((target/'keep.txt').read_text(),'keep')


if __name__=='__main__':unittest.main()
