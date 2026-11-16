import json,os,subprocess,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import video_process as pipeline
from converter import Control


class EncoderRecoveryTests(unittest.TestCase):
    def test_probe_uses_a_driver_supported_frame_size(self):
        actual=subprocess.Popen;commands=[]
        def start(command,**kwargs):
            commands.append(command)
            return actual([getattr(sys,'_base_executable',sys.executable),'-c','pass'],**kwargs)
        with tempfile.TemporaryDirectory() as d,patch.object(pipeline.subprocess,'Popen',side_effect=start):
            self.assertEqual(pipeline.select_encoder('ffmpeg.exe',d,Control(lambda *a:None)),'nvenc')
        self.assertIn('color=size=256x256:rate=1',commands[0])

    def test_hardware_probe_timeout_stops_the_owned_probe_process(self):
        actual=subprocess.Popen;children=[]
        def start(command,**kwargs):
            child=actual([getattr(sys,'_base_executable',sys.executable),'-c','import time;time.sleep(30)'],**kwargs);children.append(child);return child
        with tempfile.TemporaryDirectory() as d,patch.object(pipeline.subprocess,'Popen',side_effect=start),patch.object(pipeline,'ENCODER_PROBE_TIMEOUT',.05):
            self.assertEqual(pipeline.select_encoder('ffmpeg.exe',d,Control(lambda *a:None)),'x264')
        self.assertEqual(len(children),1);self.assertIsNotNone(children[0].poll())

    def test_compatible_failure_is_bounded_and_keeps_both_attempts(self):
        with tempfile.TemporaryDirectory() as d:
            folder=Path(d);job=dict(width=3840,height=2160,fps=60,frames=[{},{}],source='source.osgb')
            with patch.object(pipeline,'select_encoder',return_value='nvenc'),patch.object(pipeline,'_attempt',side_effect=pipeline.RenderFailure('crashed','encoding',1,'encoder_crash')) as attempt:
                with self.assertRaises(pipeline.RenderFailure) as caught:
                    pipeline.render_stream('renderer','encoder',job,folder,folder/'video.mp4',{},Control(lambda *a:None),{})
            self.assertEqual(attempt.call_count,2)
            report=json.loads((caught.exception.diagnostics_path/'failure.json').read_text(encoding='utf-8'))
            self.assertEqual(len(report['attempts']),2)

    def test_empty_encoder_access_violation_is_identified_and_retried_compatibly(self):
        actual=subprocess.Popen;commands=[];jobs=[];encodes=0
        python=getattr(sys,'_base_executable',sys.executable)
        with tempfile.TemporaryDirectory() as d:
            folder=Path(d);work=folder/'work';work.mkdir()
            request=dict(source='unchanged.osgb',width=128,height=128,fps=60,frames=[dict(eye=[0,-5,0],center=[0,0,0],up=[0,0,1],fovy=45)]*2)
            def start(command,**kwargs):
                nonlocal encodes
                commands.append(command)
                if Path(command[0]).stem=='mesh_render':
                    job=json.loads(Path(command[1]).read_text(encoding='utf-8'));jobs.append(job)
                    code="import time;time.sleep(10)" if len(jobs)==1 else (
                        "import json,sys;from pathlib import Path;j=json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'));"
                        "Path(j['progress']).write_text(json.dumps(dict(state='succeeded',frame=2,total=2)))")
                    command=[python,'-c',code,str(command[1])]
                else:
                    encodes+=1
                    code=("import ctypes;ctypes.windll.kernel32.ExitProcess(0xC0000005)" if os.name=='nt' else 'import sys;sys.exit(139)') if encodes==1 else (
                        "from pathlib import Path;import sys;Path(sys.argv[1]).write_bytes(b'encoded fixture')")
                    command=[python,'-c',code,str(command[-1])]
                return actual(command,**kwargs)
            with patch.object(pipeline,'select_encoder',return_value='x264',create=True),patch.object(pipeline.subprocess,'Popen',side_effect=start):
                encoded,state,attempts=pipeline.render_stream('mesh_render.exe','ffmpeg.exe',request,work,folder/'out.mp4',os.environ.copy(),Control(lambda *a:None),dict(load=10,context=10,stall=10))
            self.assertEqual(len(attempts),2);self.assertTrue(encoded.is_file())
            self.assertEqual(attempts[0]['error_kind'],'encoder_crash')
            if os.name=='nt':self.assertIn('0xC0000005',attempts[0]['error'])
            self.assertEqual(attempts[1]['encoder'],'x264_compatible')
            self.assertEqual(jobs[0]['frames'],jobs[1]['frames']);self.assertEqual(jobs[0]['width'],jobs[1]['width'])
            encoder_commands=[c for c in commands if Path(c[0]).stem=='ffmpeg']
            self.assertIn('asm=0',encoder_commands[1]);self.assertIn('-cpuflags',encoder_commands[1])

    def test_gpu_encoding_failure_recovers_once_without_changing_render_request(self):
        with tempfile.TemporaryDirectory() as d:
            folder=Path(d);requests=[]
            def attempt(renderer,ffmpeg,request,*args):
                requests.append(request)
                if len(requests)==1:raise pipeline.RenderFailure('NVENC unavailable','encoding',0,'encoder')
                return folder/'encoded.mp4',dict(state='succeeded',frame=2)
            job=dict(width=3840,height=2160,fps=60,frames=[{},{}],source='source.osgb')
            with patch.object(pipeline,'select_encoder',return_value='nvenc',create=True),patch.object(pipeline,'_attempt',side_effect=attempt):
                _,state,attempts=pipeline.render_stream('renderer','encoder',job,folder,folder/'video.mp4',{},Control(lambda *a:None),{})
            self.assertEqual([r['encoder'] for r in requests],['nvenc','x264_compatible'])
            for key in job:self.assertEqual(requests[0][key],requests[1][key])
            self.assertEqual(len(attempts),2)
