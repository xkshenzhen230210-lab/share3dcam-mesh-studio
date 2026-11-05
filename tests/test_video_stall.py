"""Reproduce missing render watchdogs, independently of any particular GPU.

The deliberately stalled child represents an unknown native stall; these tests
do not diagnose why a user's other computer stopped before its first frame.
"""
import json
import subprocess
import sys
import tempfile
import threading
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

import video
from converter import Control

# Avoid the Windows virtualenv launcher's extra interpreter child in fake native
# workers; termination must release these fixture logs before directory cleanup.
WORKER_PYTHON=getattr(sys,'_base_executable',sys.executable)


def keys():
    return [dict(time=stamp,eye=[0,-10,2],center=[0,0,0],up=[0,0,1],fovy=35)
            for stamp in (0,2/30)]


class VideoStallTests(unittest.TestCase):
    def assert_stall_is_diagnosed(self,stage,timeout_name):
        original_popen=subprocess.Popen;children=[];jobs=[];messages=[]
        control=Control(lambda message,percent:messages.append(message));caught=None
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);source=root/'model.osgb';source.write_bytes(b'fake renderer fixture')
            output=root/'must-not-publish.mp4'

            def start(command,**kwargs):
                if Path(command[0]).stem=='mesh_render':
                    job=json.loads(Path(command[1]).read_text(encoding='utf-8'));jobs.append(job)
                    Path(job['progress']).write_text(json.dumps(dict(state=stage,frame=0,total=2)),encoding='utf-8')
                    command=[WORKER_PYTHON,'-c','import time;time.sleep(60)']
                child=original_popen(command,**kwargs);children.append(child);return child

            # This guard only prevents old/broken code from sleeping indefinitely;
            # it is not a startup-performance SLA. Allow Windows child startup and
            # scheduler contention while keeping the tested watchdog at 0.15 s.
            guard=threading.Timer(2,control.event.set)
            with ExitStack() as stack:
                for name in ('RENDER_LOAD_TIMEOUT','RENDER_CONTEXT_TIMEOUT','RENDER_STALL_TIMEOUT'):
                    stack.enter_context(patch.object(video,name,.15 if name==timeout_name else 60,create=True))
                stack.enter_context(patch.object(video.subprocess,'Popen',side_effect=start))
                guard.start()
                try:
                    video.render_video(source,output,keys(),control=control)
                except Exception as error:caught=error
                finally:guard.cancel();guard.join()

            self.assertTrue(children,'test must actually launch child processes')
            self.assertTrue(all(child.poll() is not None for child in children),'owned children must be stopped')
            self.assertFalse(output.exists(),'a stalled render must never publish MP4')
            self.assertIsInstance(caught,RuntimeError,'watchdog must fail before the external safety cancellation')
            self.assertIn(stage,str(caught).lower(),'failure must identify its native stage')
            diagnostics=Path(caught.diagnostics_path)
            self.assertTrue(diagnostics.is_dir(),'diagnostics must survive temporary render cleanup')
            self.assertIn(str(diagnostics),str(caught),'failure must identify its diagnostic location')
            failure=json.loads((diagnostics/'failure.json').read_text(encoding='utf-8'))
            self.assertEqual(failure['stage'],stage)
            self.assertTrue(list(diagnostics.rglob('render.log')))
            self.assertTrue(list(diagnostics.rglob('encode.log')))
            self.assertTrue(any(stage in message.lower() for message in messages),
                            'status must distinguish loading/context from rendering 0/N')
            if stage!='context':self.assertEqual(len(jobs),1,'non-context stalls must not retry the renderer')

    def test_first_frame_stall_has_bounded_failure_and_persistent_diagnostics(self):
        self.assert_stall_is_diagnosed('rendering','RENDER_STALL_TIMEOUT')

    def test_model_load_stall_identifies_loading_and_stops_children(self):
        self.assert_stall_is_diagnosed('loading','RENDER_LOAD_TIMEOUT')

    def test_opengl_context_stall_identifies_context_and_stops_children(self):
        self.assert_stall_is_diagnosed('context','RENDER_CONTEXT_TIMEOUT')

    def assert_memory_failure_stops_without_context_retry(self,error_kind,exit_before_poll):
        original_popen=subprocess.Popen;children=[];jobs=[];caught=None
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);source=root/'model.osgb';source.write_bytes(b'fake renderer fixture')
            output=root/'memory-failed.mp4';control=Control(lambda *args:None)

            def start(command,**kwargs):
                native=Path(command[0]).stem=='mesh_render'
                if native:
                    job=json.loads(Path(command[1]).read_text(encoding='utf-8'));jobs.append(job)
                    Path(job['progress']).write_text(json.dumps(dict(
                        state='failed',phase='first_frame',frame=0,total=2,
                        error='Native memory allocation failed',error_kind=error_kind)),encoding='utf-8')
                    code='import sys;sys.exit(17)' if exit_before_poll else 'import time;time.sleep(60)'
                    command=[WORKER_PYTHON,'-c',code]
                child=original_popen(command,**kwargs);children.append(child)
                if native and exit_before_poll:child.wait(timeout=3)
                return child

            guard=threading.Timer(2,control.event.set);guard.start()
            try:
                with patch.object(video.subprocess,'Popen',side_effect=start):
                    video.render_video(source,output,keys(),control=control)
            except Exception as error:caught=error
            finally:
                guard.cancel();guard.join()
                for child in children:
                    if child.poll() is None:child.terminate();child.wait(timeout=3)
            self.assertIsInstance(caught,RuntimeError)
            self.assertTrue(children)
            self.assertTrue(all(child.poll() is not None for child in children))
            self.assertFalse(output.exists(),'out-of-memory must not publish MP4')
            self.assertEqual(len(jobs),1,'changing contexts cannot recover exhausted RAM or VRAM')
            self.assertEqual(caught.kind,error_kind)
            diagnostics=Path(caught.diagnostics_path)
            self.assertTrue(diagnostics.is_dir())
            failure=json.loads((diagnostics/'failure.json').read_text(encoding='utf-8'))
            self.assertEqual(failure['stage'],'first_frame')
            self.assertEqual(failure['error_kind'],error_kind)
            self.assertEqual(len(failure['attempts']),1)
            self.assertTrue(list(diagnostics.rglob('render.log')))
            self.assertTrue(list(diagnostics.rglob('encode.log')))

    def test_system_memory_failure_exited_worker_does_not_retry_context(self):
        self.assert_memory_failure_stops_without_context_retry('system_memory',exit_before_poll=True)

    def test_gpu_memory_failure_live_worker_does_not_retry_context(self):
        self.assert_memory_failure_stops_without_context_retry('gpu_memory',exit_before_poll=False)

    def test_context_failure_retries_window_once_without_reducing_output_quality(self):
        original_popen=subprocess.Popen;children=[];jobs=[]
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);source=root/'model.osgb';source.write_bytes(b'fake renderer fixture')
            output=root/'recovered.mp4';control=Control(lambda *args:None)

            def start(command,**kwargs):
                if Path(command[0]).stem=='mesh_render':
                    job_path=Path(command[1]);job=json.loads(job_path.read_text(encoding='utf-8'));jobs.append(job)
                    if len(jobs)==1:
                        # Persist context phase before an abrupt native failure.
                        Path(job['progress']).write_text(json.dumps(dict(state='context',frame=0,total=2)),encoding='utf-8')
                        command=[WORKER_PYTHON,'-c',"import sys;sys.stderr.write('Cannot create offscreen OpenGL context');sys.exit(17)"]
                    else:
                        code=("import json,sys;from pathlib import Path;"
                              "job=json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'));"
                              "count=len(job['frames']);"
                              "sys.stdout.buffer.write(bytes([24,72,120])*(job['width']*job['height']*count));"
                              "sys.stdout.buffer.flush();"
                              "Path(job['progress']).write_text(json.dumps(dict(state='succeeded',frame=count,total=count)),encoding='utf-8')")
                        command=[WORKER_PYTHON,'-c',code,str(job_path)]
                child=original_popen(command,**kwargs);children.append(child);return child

            guard=threading.Timer(10,control.event.set);guard.start()
            try:
                with patch.object(video.subprocess,'Popen',side_effect=start):
                    report=video.render_video(source,output,keys(),resolution='1080p',fps=30,control=control)
            finally:guard.cancel();guard.join()
            self.assertEqual(report['state'],'succeeded')
            self.assertEqual(report['checks'],'passed')
            self.assertTrue(output.is_file())
            self.assertEqual(len(jobs),2,'context failure must trigger exactly one alternate-context attempt')
            self.assertEqual(jobs[1]['context_mode'],'window')
            for name in ('source','width','height','fps','frames','clip_box'):
                self.assertEqual(jobs[0][name],jobs[1][name],f'retry must preserve {name}')
            self.assertEqual((report['width'],report['height'],report['fps'],report['frames']),(1920,1080,30,2))
            self.assertTrue(all(child.poll() is not None for child in children))

    def test_completed_processes_reload_final_state_after_stale_closing_snapshot(self):
        original_popen=subprocess.Popen;original_read=Path.read_text
        children=[];progress_paths=set();stale_reads=[]
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);source=root/'model.osgb';source.write_bytes(b'fake renderer fixture')
            output=root/'complete.mp4'

            def start(command,**kwargs):
                name=Path(command[0]).stem
                if name=='mesh_render':
                    job_path=Path(command[1]);job=json.loads(original_read(job_path,encoding='utf-8'))
                    progress_paths.add(Path(job['progress']))
                    code=("import json,sys;from pathlib import Path;"
                          "job=json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'));"
                          "count=len(job['frames']);"
                          "sys.stdout.buffer.write(bytes([24,72,120])*(job['width']*job['height']*count));"
                          "sys.stdout.buffer.flush();"
                          "Path(job['progress']).write_text(json.dumps(dict(state='succeeded',frame=count,total=count)),encoding='utf-8')")
                    command=[WORKER_PYTHON,'-c',code,str(job_path)]
                child=original_popen(command,**kwargs);children.append(child)
                if name=='ffmpeg':
                    # Complete both real processes before the parent first polls.
                    # The only simulated race is the stale file-read snapshot below.
                    for process in children:process.wait(timeout=5)
                return child

            def read(path,*args,**kwargs):
                text=original_read(path,*args,**kwargs)
                if path in progress_paths and not stale_reads:
                    state=json.loads(text)
                    self.assertEqual(state['state'],'succeeded','actual disk result must already be complete')
                    self.assertTrue(all(child.poll() is not None for child in children))
                    stale_reads.append(path);state['state']='closing';return json.dumps(state)
                return text

            try:
                with patch.object(video.subprocess,'Popen',side_effect=start),patch.object(Path,'read_text',read):
                    report=video.render_video(source,output,keys(),control=Control(lambda *args:None))
            finally:
                for child in children:
                    if child.poll() is None:child.terminate();child.wait(timeout=3)
            self.assertEqual(len(stale_reads),1,'inject exactly one stale closing snapshot')
            self.assertEqual(report['state'],'succeeded')
            self.assertEqual(report['checks'],'passed')
            self.assertEqual(report['frames'],2)
            self.assertTrue(output.is_file())
            self.assertEqual(len(progress_paths),1,'a completed render must not retry')
            self.assertTrue(all(child.poll() is not None for child in children))
