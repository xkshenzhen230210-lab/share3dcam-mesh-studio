"""Bounded native rendering, context recovery and persistent diagnostics."""
import json
import os
import platform
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from converter import Cancelled, write_json

STAGES = {
 'starting': '启动渲染进程 / Starting renderer',
 'loading': '加载完整模型及贴图 / Loading model',
 'materials': '准备模型材质 / Preparing materials',
 'context': '初始化显卡上下文 / Graphics context',
 'initializing': '启动离屏渲染 / Initializing renderer',
 'capabilities': '检查显卡能力 / GPU capabilities',
 'first_frame': '生成首帧 / First frame',
 'rendering': '渲染视频 / Rendering video',
 'encoding': '写入视频编码器 / Encoding video',
 'closing': '释放渲染资源 / Closing renderer',
 'succeeded': '完成视频编码 / Finalizing encoding',
}
CONTEXT_STAGES = {'context','initializing','capabilities','first_frame'}
ENCODER_PROBE_TIMEOUT=12

class RenderFailure(RuntimeError):
    def __init__(self, message, stage, frame=0, kind='runtime'):
        super().__init__(message)
        self.stage, self.frame, self.diagnostics_path = stage, frame, None
        self.kind=kind

def stop(process):
    if process is not None and process.poll() is None:
        process.terminate()
        try: process.wait(timeout=3)
        except subprocess.TimeoutExpired: process.kill(); process.wait(timeout=3)

def tail(path):
    try:
        with path.open('rb') as stream:
            stream.seek(max(0,path.stat().st_size-3000))
            return stream.read().decode('utf-8',errors='replace')
    except OSError: return ''

def _encoder_options(mode):
    if mode=='nvenc':
        return ['-c:v','h264_nvenc','-preset','p7','-tune','hq','-rc','constqp','-qp','16']
    return ['-c:v','libx264','-preset','medium','-crf','18']+(
        ['-x264-params','asm=0','-threads','1'] if mode=='x264_compatible' else ['-threads','2'])

def select_encoder(ffmpeg,work,control):
    # Probe real hardware initialization, not merely a compiled-in encoder name.
    process=None
    try:
        command=[str(ffmpeg),'-hide_banner','-nostdin','-v','error','-cpuflags','0',
            '-f','lavfi','-i','color=size=256x256:rate=1','-frames:v','1',
            *_encoder_options('nvenc'),'-pix_fmt','yuv420p','-filter_threads','1','-f','null','-']
        with tempfile.TemporaryFile() as log:
            process=subprocess.Popen(command,cwd=work,stdout=log,stderr=subprocess.STDOUT,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            started=time.monotonic()
            while process.poll() is None:
                control.check()
                if time.monotonic()-started>ENCODER_PROBE_TIMEOUT:
                    try:write_json(Path(work)/'encoder_probe.json',dict(mode='x264',reason='probe_timeout'))
                    except OSError:pass
                    return 'x264'
                control.event.wait(.05)
            mode='nvenc' if process.returncode==0 else 'x264';log.seek(0)
            try:write_json(Path(work)/'encoder_probe.json',dict(mode=mode,exit_code=process.returncode,log=log.read().decode('utf-8',errors='replace')[-2000:]))
            except OSError:pass
            return mode
    except Cancelled:raise
    except OSError:return 'x264'
    finally:stop(process)

def _attempt(renderer,ffmpeg,request,work,env,control,timeouts):
    job,progress=work/'job.json',work/'progress.json'
    encoded,render_log,encode_log=work/'video.mp4',work/'render.log',work/'encode.log'
    write_json(job,dict(request,progress=str(progress)))
    width,height,fps,total=request['width'],request['height'],request['fps'],len(request['frames'])
    encoder=request.get('encoder','x264')
    if encoder not in ('nvenc','x264','x264_compatible'):raise ValueError('Invalid encoder mode')
    command=[str(ffmpeg),'-hide_banner','-nostdin','-v','error',
        *(['-cpuflags','0'] if encoder!='x264' else []),'-f','rawvideo',
        '-pixel_format','rgb24','-video_size',f'{width}x{height}','-framerate',str(fps),
        '-i','pipe:0','-an','-vf','vflip',*_encoder_options(encoder),
        '-pix_fmt','yuv420p','-filter_threads','1',
        '-movflags','+faststart','-n',str(encoded)]
    write_json(work/'encoder.json',dict(mode=encoder,command=command))
    render=encode=None;current={'state':'starting','frame':0};previous=None
    last_change=last_notice=time.monotonic();flags=getattr(subprocess,'CREATE_NO_WINDOW',0)
    def encoding_failure(frame):
        code=encode.returncode;hexcode=f'0x{code&0xffffffff:08X}'
        crash=code<0 or code&0xC0000000==0xC0000000 or code in (139,)
        error=RenderFailure(f'视频编码失败 / Encoding failed ({code}, {hexcode}): '+tail(encode_log),
            'encoding',frame,'encoder_crash' if crash else 'encoder')
        error.process_exit_codes=dict(renderer=render.poll(),encoder=code)
        return error
    with render_log.open('wb') as rlog,encode_log.open('wb') as elog:
        try:
            render=subprocess.Popen([str(renderer),str(job)],cwd=work,env=env,stdout=subprocess.PIPE,stderr=rlog,creationflags=flags)
            try: encode=subprocess.Popen(command,cwd=work,env=env,stdin=render.stdout,stdout=elog,stderr=subprocess.STDOUT,creationflags=flags)
            finally: render.stdout.close()
            while True:
                control.check()
                try:
                    value=json.loads(progress.read_text(encoding='utf-8'));frame=int(value.get('frame',0))
                    if isinstance(value.get('state'),str) and 0<=frame<=total: current=value
                except (OSError,ValueError,TypeError,AttributeError): pass
                stage,frame=current.get('phase',current['state']),int(current.get('frame',0))
                encode_failed=encode.poll() is not None and encode.returncode
                if encode_failed and ((render.poll() is None and current['state']!='failed') or
                                      'pipe closed' in current.get('error','').lower()):
                    raise encoding_failure(frame)
                # The encoder also exits when the renderer dies before its first
                # bytes. Keep the native phase as the primary failure in that race.
                if render.poll() is not None and render.returncode:
                    raise RenderFailure('模型渲染失败 / Rendering failed: '+tail(render_log),stage,frame,current.get('error_kind','runtime'))
                if current['state']=='failed': raise RenderFailure(str(current.get('error','Native renderer failed')),stage,frame,current.get('error_kind','runtime'))
                if encode_failed:raise encoding_failure(frame)
                if render.poll() is not None and encode.poll() is not None: break
                if render.poll() is not None: stage='encoding'
                signature=(stage,frame,current.get('pages'));now=time.monotonic();changed=signature!=previous
                if changed: previous,last_change=signature,now
                if changed or now-last_notice>=5:
                    elapsed=int(now-last_change)
                    pages=f' · {current["pages"]} pages' if stage=='loading' and 'pages' in current else ''
                    control.log(f'{STAGES.get(stage,stage)} ({stage}) · {frame}/{total}{pages} · {elapsed}s',35+55*frame/total)
                    last_notice=now
                timeout=timeouts['load'] if stage in ('loading','materials') else (
                    timeouts['context'] if stage in CONTEXT_STAGES-{'first_frame'} or stage=='starting' else timeouts['stall'])
                if now-last_change>timeout:
                    raise RenderFailure(f'{STAGES.get(stage,stage)} ({stage}) 超过 {timeout:g} 秒未推进 / No progress; render stopped',stage,frame)
                control.event.wait(.1)
        finally:
            codes=dict(renderer=render.poll() if render else None,encoder=encode.poll() if encode else None)
            stop(render);stop(encode)
            try:write_json(work/'processes.json',dict(exit_codes=codes,renderer_pid=render.pid if render else None,encoder_pid=encode.pid if encode else None))
            except OSError:pass # Optional diagnostics must not replace the original failure/cancellation.
    # The final progress rename can occur between the loop's read and poll.
    # Both children are finished now, so read their committed result afresh.
    try: current=json.loads(progress.read_text(encoding='utf-8'))
    except (OSError,ValueError):
        raise RenderFailure('渲染结果不完整 / Incomplete render result','closing') from None
    if current.get('state')!='succeeded' or current.get('frame')!=total:
        raise RenderFailure('视频帧未完整生成 / Not all video frames were rendered',current.get('state','unknown'),current.get('frame',0))
    current['encoder']=encoder;current['encoding_quality']='QP 16 (NVENC HQ)' if encoder=='nvenc' else 'CRF 18'
    return encoded,current

def render_stream(renderer,ffmpeg,request,work,output,env,control,timeouts):
    attempts=[]
    try:
        selected=select_encoder(ffmpeg,work,control)
        control.log('使用显卡高质量编码 / GPU high-quality encoding' if selected=='nvenc' else '使用高质量软件编码 / Software high-quality encoding',35)
        for encoder in (selected,'x264_compatible'):
            recover=False
            for context_index,mode in enumerate(('pbuffer','window')):
                control.check();index=len(attempts)+1;folder=work/f'attempt_{index}';folder.mkdir()
                try:
                    encoded,state=_attempt(renderer,ffmpeg,dict(request,context_mode=mode,encoder=encoder),folder,env,control,timeouts)
                    attempts.append(dict(attempt=index,context_mode=mode,encoder=encoder,state='succeeded',graphics=state.get('graphics',{})))
                    return encoded,state,attempts
                except RenderFailure as error:
                    attempts.append(dict(attempt=index,context_mode=mode,encoder=encoder,state='failed',stage=error.stage,error_kind=error.kind,error=str(error),process_exit_codes=getattr(error,'process_exit_codes',{})))
                    if encoder!='x264_compatible' and (error.kind=='encoder_crash' or (encoder=='nvenc' and error.kind=='encoder')):
                        control.log('编码器异常，自动切换兼容编码 / Retrying compatible encoder with unchanged frames',35)
                        recover=True;break
                    if context_index==0 and error.stage in CONTEXT_STAGES and error.frame==0 and error.kind not in ('system_memory','gpu_memory'):
                        control.log('自动切换兼容显卡上下文重试 / Retrying compatible graphics context',35)
                        continue
                    raise
            if not recover:break
    except Cancelled: raise
    except Exception as error:
        stage=getattr(error,'stage','starting')
        failure=error if isinstance(error,RenderFailure) else RenderFailure(str(error),stage)
        try:
            diagnostic=Path(tempfile.mkdtemp(prefix=output.stem+'_render_diagnostics_',dir=output.parent))
            probe=work/'encoder_probe.json'
            if probe.is_file():shutil.copy2(probe,diagnostic/probe.name)
            for folder in work.glob('attempt_*'):
                target=diagnostic/folder.name;target.mkdir()
                for name in ('job.json','progress.json','render.log','encode.log','encoder.json','processes.json'):
                    path=folder/name
                    if path.is_file(): shutil.copy2(path,target/name)
            write_json(diagnostic/'failure.json',dict(state='failed',stage=stage,error_kind=failure.kind,error=str(error),attempts=attempts,
                width=request['width'],height=request['height'],fps=request['fps'],frames=len(request['frames']),
                source=request.get('original_source',request['source']),platform=platform.platform(),processors=os.cpu_count()))
            failure.diagnostics_path=diagnostic
            failure.args=(f'{error}\n诊断日志 / Diagnostic logs: {diagnostic}',)
        except OSError: failure.args=(f'{error}\n诊断日志无法保存 / Could not save diagnostics',)
        if failure is error: raise
        raise failure from error
