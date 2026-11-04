import json
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from converter import Control,Cancelled,write_json
from test_gltf import triangle


class SupervisorTests(unittest.TestCase):
    def test_atomic_progress_write_retries_short_windows_read_lock(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'state.json';original=Path.replace;calls=[]
            def locked(temp,target):
                calls.append(target)
                if len(calls)<3:raise PermissionError('simulated read lock')
                return original(temp,target)
            with patch.object(Path,'replace',locked):write_json(path,{'state':'running'})
            self.assertEqual(len(calls),3)
            self.assertEqual(json.loads(path.read_text()),{'state':'running'})

    def test_worker_crash_is_retried_without_losing_parent(self):
        import supervisor
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);source=root/'input/model.glb';source.parent.mkdir();triangle(source)
            command=supervisor.worker_command;calls=[]
            def once(job):
                calls.append(job)
                return [sys.executable,'-c','import os;os._exit(77)'] if len(calls)==1 else command(job)
            with patch.object(supervisor,'worker_command',side_effect=once):
                report=supervisor.convert_isolated(source,root/'out','obj',Control(lambda *a:None))
            self.assertEqual(len(calls),2)
            self.assertEqual(report['state'],'succeeded')
            self.assertEqual(report['worker_attempts'],2)
            self.assertTrue((root/'out/obj/Model.obj').is_file())
            self.assertEqual(json.loads((root/'out/mesh_result.json').read_text(encoding='utf-8'))['state'],'succeeded')

    def test_persistent_worker_crash_has_final_failure_state(self):
        import supervisor
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);source=root/'input/model.glb';source.parent.mkdir();triangle(source)
            with patch.object(supervisor,'worker_command',return_value=[sys.executable,'-c','import os;os._exit(77)']):
                with self.assertRaises(RuntimeError):supervisor.convert_isolated(source,root/'out','obj',Control(lambda *a:None))
            self.assertEqual(json.loads((root/'out/mesh_result.json').read_text(encoding='utf-8'))['state'],'failed')
            self.assertFalse((root/'out/obj/Model.obj').exists())

    def test_existing_output_is_not_modified(self):
        import supervisor
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);source=root/'input/model.glb';source.parent.mkdir();triangle(source)
            output=root/'out';output.mkdir();(output/'keep.txt').write_text('keep')
            with self.assertRaises(ValueError):supervisor.convert_isolated(source,output,'obj',Control(lambda *a:None))
            self.assertEqual((output/'keep.txt').read_text(),'keep')

    def test_cancellation_is_forwarded_to_owned_worker(self):
        import supervisor
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);source=root/'input/model.glb';source.parent.mkdir();triangle(source)
            control=Control(lambda *a:None)
            code="import json,sys,time;from pathlib import Path;p=Path(json.load(open(sys.argv[1],encoding='utf-8'))['cancel'])\nwhile not p.exists():time.sleep(.02)"
            timer=threading.Timer(.3,control.event.set);timer.start()
            try:
                with patch.object(supervisor,'worker_command',side_effect=lambda job:[sys.executable,'-c',code,str(job)]):
                    with self.assertRaises(Cancelled):supervisor.convert_isolated(source,root/'out','obj',control)
            finally:timer.cancel();timer.join()
            self.assertEqual(json.loads((root/'out/mesh_result.json').read_text(encoding='utf-8'))['state'],'cancelled')
