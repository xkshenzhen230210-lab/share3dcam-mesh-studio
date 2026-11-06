"""Isolate native/Python conversion failures from the UI; retry abrupt exits once."""
import faulthandler
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from converter import Cancelled, Control, convert, write_json
from model_paths import resolve_model
from spatial_frame import ClipBox


def worker_command(job):
    command=[sys.executable]
    if not getattr(sys,'frozen',False):command+=['-X','faulthandler',str(Path(__file__).with_name('app.py'))]
    return command+['--worker-job',str(job)]


class FileCancellation:
    def __init__(self,path):self.path=Path(path)
    def is_set(self):return self.path.exists()
    def wait(self,seconds):
        time.sleep(seconds)
        return self.is_set()


def worker_affinity(attempt):
    # Keep the conversion worker on one available logical CPU. The UI is unaffected.
    # This is a stability mitigation, not a diagnosis of the observed runtime crash.
    if os.name!='nt':return
    import ctypes
    from ctypes import wintypes
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.GetCurrentProcess.restype=wintypes.HANDLE
    kernel.GetProcessAffinityMask.argtypes=[wintypes.HANDLE,ctypes.POINTER(ctypes.c_size_t),ctypes.POINTER(ctypes.c_size_t)]
    kernel.SetProcessAffinityMask.argtypes=[wintypes.HANDLE,ctypes.c_size_t]
    process=kernel.GetCurrentProcess();allowed=ctypes.c_size_t();system=ctypes.c_size_t()
    if kernel.GetProcessAffinityMask(process,ctypes.byref(allowed),ctypes.byref(system)):
        bits=[1<<i for i in range(allowed.value.bit_length()) if allowed.value&(1<<i)]
        if bits:kernel.SetProcessAffinityMask(process,bits[(len(bits)//2+2*(attempt-1))%len(bits)])


def worker_main(job_path):
    job_path=Path(job_path);job=json.loads(job_path.read_text(encoding='utf-8'))
    worker_affinity(job['attempt'])
    try:faulthandler.enable(all_threads=True)
    except (OSError,RuntimeError,AttributeError):pass
    event=FileCancellation(job['cancel'])
    control=Control(lambda message,percent:write_json(job['status'],{'message':message,'progress':percent}),event)
    try:
        convert(job['source'],job['output'],job['formats'],control,clip_box=job['clip_box'],preview=job['preview'])
        return 0
    except Exception as error:
        state='cancelled' if isinstance(error,Cancelled) else 'failed'
        write_json(job['error'],{'state':state,'error':str(error)})
        if sys.stderr:print(str(error),file=sys.stderr,flush=True)
        return 1


def convert_isolated(input_path,output_path,formats='both',control=None,clip_box=None,preview=False):
    control=control or Control();control.check()
    source=resolve_model(input_path,allow_glb_collection=True);output=Path(output_path).resolve()
    base=source if source.is_dir() else source.parent
    if output==base or output in base.parents or output.is_relative_to(base):raise ValueError('输出目录必须独立于输入目录')
    if output.exists() and any(output.iterdir()):raise ValueError('输出目录不是空目录，请选择新目录')
    output.mkdir(parents=True,exist_ok=True);tasks=output/'.task';tasks.mkdir()
    request={'source':str(source),'formats':formats,'clip_box':ClipBox(clip_box).tolist() if clip_box is not None else None,'preview':preview}
    write_json(output/'conversion_request.json',request)
    write_json(output/'mesh_result.json',{'state':'running','code':1,'data':{}})
    write_json(output/'conversion_report.json',dict(request,state='running'))
    process=None;started=time.time()
    try:
        for attempt in (1,2):
            control.check();work=tasks/('attempt_'+str(attempt));work.mkdir()
            target=work/'result';cancel=work/'cancel';status=work/'status.json';error_file=work/'error.json'
            job=dict(request,output=str(target),attempt=attempt,cancel=str(cancel),status=str(status),error=str(error_file))
            job_file=work/'job.json';write_json(job_file,job)
            env=os.environ.copy();env.update(PYTHONUTF8='1',PYTHONFAULTHANDLER='1',OPENBLAS_NUM_THREADS='1',OMP_NUM_THREADS='1')
            last=None;cancellation_started=None
            with (work/'worker.log').open('wb') as log:
                process=subprocess.Popen(worker_command(job_file),cwd=work,env=env,stdout=log,stderr=subprocess.STDOUT,
                                         creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
                write_json(output/'mesh_progress.json',{'state':'running','progress':0,'attempt':attempt,'worker_pid':process.pid})
                while process.poll() is None:
                    if control.event.is_set():
                        cancel.touch(exist_ok=True)
                        if cancellation_started is None:cancellation_started=time.monotonic()
                        if time.monotonic()-cancellation_started>10:process.kill();process.wait()
                    elif status.is_file():
                        try:progress=json.loads(status.read_text(encoding='utf-8'))
                        except (OSError,ValueError):progress=None
                        if progress and progress!=last:
                            last=progress
                            # The parent publishes 100% only after installing completed files.
                            percent=min(float(progress['progress']),99)
                            write_json(output/'mesh_progress.json',{'state':'running','progress':percent,'attempt':attempt,'worker_pid':process.pid})
                            control.log(progress['message'],percent)
                    time.sleep(.1)
            control.check()
            if process.returncode==0:
                report=json.loads((target/'conversion_report.json').read_text(encoding='utf-8'))
                result=json.loads((target/'mesh_result.json').read_text(encoding='utf-8'))
                if report.get('state')!='succeeded' or result.get('state')!='succeeded':
                    raise RuntimeError('后台进程未完成结果检查 / Worker did not complete output checks')
                if formats in ('obj','both') and not preview and report.get('quality',{}).get('state')!='passed':
                    raise RuntimeError('后台检查未通过 / Background checks did not pass')
                # Staged absolute paths must refer to the installed result after publication.
                def rebase(value):
                    if isinstance(value,dict):return {k:rebase(v) for k,v in value.items()}
                    if isinstance(value,list):return [rebase(v) for v in value]
                    if isinstance(value,str) and value.startswith(str(target)+os.sep):return str(output)+value[len(str(target)):]
                    return value
                report=rebase(report);result=rebase(result)
                for item in target.iterdir():
                    if item.name not in ('mesh_result.json','mesh_progress.json','conversion_report.json'):
                        item.replace(output/item.name)
                if (output/'point_result.json').is_file():
                    point_report=json.loads((output/'point_result.json').read_text(encoding='utf-8'))
                    write_json(output/'point_result.json',rebase(point_report))
                report.update(worker_attempts=attempt,seconds=round(time.time()-started,2))
                write_json(output/'conversion_report.json',report)
                write_json(output/'mesh_result.json',result)
                write_json(output/'mesh_progress.json',{'state':'succeeded','progress':100,'attempt':attempt})
                control.log('导出完成，检查通过 / Export complete, checks passed' if not preview and formats in ('obj','both') else '转换完成 / Conversion complete',100)
                return report
            if error_file.is_file():
                failure=json.loads(error_file.read_text(encoding='utf-8'))
                if failure['state']=='cancelled':raise Cancelled(failure['error'])
                raise RuntimeError(failure['error'])
            if attempt==1:
                control.log('后台任务中断，正在自动恢复 / Recovering interrupted export…',0)
            else:raise RuntimeError(f'后台进程异常退出，自动恢复未完成 / Worker exited unexpectedly ({process.returncode}); recovery failed')
        raise RuntimeError('后台任务未完成 / Worker incomplete')
    except Exception as error:
        if process and process.poll() is None:
            # Stop only the owned worker; its cancellation marker lets native children exit normally.
            cancel.touch(exist_ok=True)
            try:process.wait(timeout=10)
            except subprocess.TimeoutExpired:process.kill();process.wait()
        state='cancelled' if isinstance(error,Cancelled) else 'failed'
        write_json(output/'conversion_report.json',dict(request,state=state,error=str(error)))
        write_json(output/'mesh_result.json',{'state':state,'code':1,'error_reason':str(error),'data':{}})
        write_json(output/'mesh_progress.json',{'state':state,'progress':0})
        raise
