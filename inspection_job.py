"""Isolated, cancelable report worker with bounded CPU use and atomic delivery."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import traceback
from datetime import datetime
from uuid import uuid4

from converter import Control,write_json
from inspection_delivery import publish_report,source_unchanged


def local_root():
    return Path(os.environ.get('LOCALAPPDATA',tempfile.gettempdir()))/'SHARE3DCAM/MeshStudio/inspection'


def _limit_worker_cpu():
    # Keep interactive viewing responsive and avoid nested numeric thread pools.
    # This changes only the child process, never system or user settings.
    if os.name!='nt':return None
    import ctypes
    process_mask=ctypes.c_size_t();system_mask=ctypes.c_size_t()
    kernel=ctypes.windll.kernel32;handle=ctypes.c_void_p(-1)
    if not kernel.GetProcessAffinityMask(handle,ctypes.byref(process_mask),ctypes.byref(system_mask)):
        raise OSError('Cannot query inspection worker CPU affinity')
    cpu=process_mask.value.bit_length()-1
    if cpu<0 or not kernel.SetProcessAffinityMask(handle,ctypes.c_size_t(1<<cpu)):
        raise OSError('Cannot limit inspection worker CPU affinity')
    return cpu


def worker_main(job_path):
    job_path=Path(job_path).resolve();status=job_path.parent/'status.json'
    try:
        job=json.loads(job_path.read_text(encoding='utf-8'))
        cpu=_limit_worker_cpu()
        print(f'Inspection worker CPU: {cpu}',flush=True)
        from auto_wall import analyze_building
        def progress(message,percent):write_json(status,dict(state='running',message=message,percent=percent))
        report=analyze_building(job['source'],job['output'],control=Control(progress),**job['settings'])
        write_json(status,dict(state='succeeded',output=report['output'],percent=100))
        return 0
    except BaseException as error:
        traceback.print_exc()
        write_json(status,dict(state='failed',message=str(error),percent=0))
        return 1


def inspect_isolated(source,output,settings=None,control=None):
    control=control or Control();control.check()
    destination=Path(output).expanduser().resolve();source=Path(source).expanduser().resolve()
    try:exists=destination.exists()
    except OSError:exists=False  # Retry delivery after local computation.
    if exists:raise FileExistsError('报告目录已存在 / Report destination exists')
    cache=local_root();cache.mkdir(parents=True,exist_ok=True);cache=cache.resolve()
    with tempfile.TemporaryDirectory(prefix='.inspection-job-',dir=cache,ignore_cleanup_errors=True) as temporary:
        work=Path(temporary).resolve()
        if work.parent!=cache or not work.name.startswith('.inspection-job-'):raise ValueError('Invalid worker directory')
        job=work/'job.json';write_json(job,dict(source=str(source),output=str(work/'result'),settings=settings or {}))
        command=[sys.executable,'--inspection-job',str(job)] if getattr(sys,'frozen',False) else [sys.executable,str(Path(__file__).with_name('app.py')),'--inspection-job',str(job)]
        environment=os.environ.copy();environment.update(OPENBLAS_NUM_THREADS='1',OMP_NUM_THREADS='1',MKL_NUM_THREADS='1',PYTHONIOENCODING='utf-8')
        process=None;last=None
        try:
            with (work/'worker.log').open('wb') as log:
                process=subprocess.Popen(command,cwd=work,env=environment,stdout=log,stderr=subprocess.STDOUT,
                                         creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
                while process.poll() is None:
                    control.check()
                    try:
                        text=(work/'status.json').read_text(encoding='utf-8')
                        if text!=last:
                            progress=json.loads(text);control.log(progress.get('message','正在生成报告 / Preparing report'),min(99,progress.get('percent',0)));last=text
                    except (OSError,ValueError):pass
                    time.sleep(.1)
            control.check()
            state=json.loads((work/'status.json').read_text(encoding='utf-8')) if (work/'status.json').is_file() else {}
            if process.returncode!=0 or state.get('state')!='succeeded':
                details=(work/'worker.log').read_text(encoding='utf-8',errors='replace')[-4000:]
                raise RuntimeError('自动分析未完成 / Automatic inspection failed: '+state.get('message',f'worker exit {process.returncode}')+'\n'+details)
            result=work/'result';report=json.loads((result/'report.json').read_text(encoding='utf-8'))
            shutil.copyfile(work/'worker.log',result/'worker.log')
            control.check();source_unchanged(source,report)
            try:
                report=publish_report(result,destination,source,report,control)
            except FileExistsError:raise
            except OSError as error:
                # Keep the successfully computed result if the selected share
                # cannot accept it. The UI must use and show this actual path.
                control.check();source_unchanged(source,report)
                saved=cache/('saved-'+datetime.now().strftime('%Y%m%d-%H%M%S')+'-'+uuid4().hex[:8])
                report.update(output=str(saved),delivery='local_fallback',requested_output=str(destination),delivery_error=str(error))
                write_json(result/'report.json',report);result.rename(saved)
                control.log('共享目录保存失败，完整报告已保存在本机 / Report saved locally: '+str(saved),100)
                return report
            control.log('完整报告已生成 / Complete report ready',100)
            return report
        finally:
            if process and process.poll() is None:
                process.terminate()
                try:process.wait(timeout=5)
                except subprocess.TimeoutExpired:process.kill();process.wait(timeout=5)
