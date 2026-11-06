import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from converter import Control,Cancelled,write_json
from inspection_delivery import publish_report


class InspectionDeliveryTests(unittest.TestCase):
    def fixture(self,root):
        source=root/'source.las';source.write_bytes(b'unchanged source')
        result=root/'computed';result.mkdir();(result/'wall').mkdir()
        (result/'wall/points.bin').write_bytes(bytes(range(256))*9000)
        stat=source.stat();report=dict(state='succeeded',source_size=stat.st_size,source_mtime_ns=stat.st_mtime_ns,output=str(result))
        write_json(result/'report.json',report)
        return source,result,report

    def test_verified_copy_publishes_without_private_share_directory(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp).resolve();source,result,report=self.fixture(root);destination=root/'share/report'
            output=publish_report(result,destination,source,report,Control(lambda *_:None))
            self.assertEqual(output['output'],str(destination))
            self.assertEqual((result/'wall/points.bin').read_bytes(),(destination/'wall/points.bin').read_bytes())
            self.assertFalse(list(destination.parent.glob('inspection-publish-*')))

    def test_transient_copy_failure_retries_without_publishing_partial_report(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp).resolve();source,result,report=self.fixture(root);destination=root/'share/report'
            import inspection_delivery
            original=inspection_delivery._copy_file;failed=False
            def copy(a,b,control):
                nonlocal failed
                self.assertFalse(destination.exists())
                if not failed:
                    failed=True;b.write_bytes(b'partial');raise OSError(59,'network interrupted')
                return original(a,b,control)
            with patch('inspection_delivery._copy_file',side_effect=copy):
                publish_report(result,destination,source,report,Control(lambda *_:None))
            self.assertTrue(failed);self.assertEqual((result/'wall/points.bin').read_bytes(),(destination/'wall/points.bin').read_bytes())

    def test_cancel_and_changed_source_do_not_publish(self):
        for mode in ('cancel','changed'):
            with self.subTest(mode=mode),tempfile.TemporaryDirectory() as temp:
                root=Path(temp).resolve();source,result,report=self.fixture(root);destination=root/'share/report'
                event=threading.Event()
                def progress(*_):
                    if mode=='cancel':event.set()
                    else:source.write_bytes(b'changed')
                with self.assertRaises(Cancelled if mode=='cancel' else ValueError):
                    publish_report(result,destination,source,report,Control(progress,event))
                self.assertFalse(destination.exists());self.assertTrue(result.exists())

    def test_existing_report_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp).resolve();source,result,report=self.fixture(root);destination=root/'report';destination.mkdir()
            (destination/'keep.txt').write_text('keep')
            with self.assertRaises(FileExistsError):publish_report(result,destination,source,report,Control(lambda *_:None))
            self.assertEqual((destination/'keep.txt').read_text(),'keep')

    def test_corrupt_copy_is_rejected_and_local_result_survives(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp).resolve();source,result,report=self.fixture(root);destination=root/'share/report'
            original_open=Path.open
            def corrupt_before_read(path,mode='r',*args,**kwargs):
                if mode=='rb' and path.name=='points.bin' and 'inspection-publish-' in str(path):
                    with original_open(path,'wb') as stream:stream.write(b'corrupted transfer')
                return original_open(path,mode,*args,**kwargs)
            with patch.object(Path,'open',new=corrupt_before_read):
                with self.assertRaisesRegex(OSError,'verification failed'):
                    publish_report(result,destination,source,report,Control(lambda *_:None))
            self.assertFalse(destination.exists())
            self.assertEqual((result/'wall/points.bin').stat().st_size,256*9000)
