"""Camera keyframes and full-resolution, independently verified MP4 rendering."""
import bisect
import json
import math
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

import numpy as np

from converter import Control, RUNTIME, write_json
from model_paths import resolve_model
from supervisor import convert_isolated

RESOLUTIONS={'1080p':(1920,1080),'4K':(3840,2160)}
FRAME_RATES=(24,30,60)


def _vector(value):
    try:result=np.asarray(value,dtype=np.float64)
    except (ValueError,TypeError):raise ValueError('相机坐标无效 / Invalid camera coordinates') from None
    if result.shape!=(3,) or not np.isfinite(result).all():
        raise ValueError('相机坐标须为三个有限数值 / Camera requires three finite coordinates')
    return result


def _basis(pose):
    with np.errstate(over='ignore',invalid='ignore'):
        back=np.asarray(pose['eye'],dtype=np.float64)-pose['center']
    distance=math.hypot(*back)
    if not math.isfinite(distance) or distance<=1e-9:
        raise ValueError('相机与目标点间距无效 / Invalid camera-to-target distance')
    up=np.asarray(pose['up'],dtype=np.float64);up_length=math.hypot(*up)
    if not math.isfinite(up_length) or up_length<=1e-12:
        raise ValueError('相机朝上方向无效 / Invalid camera up direction')
    back/=distance;right=np.cross(up/up_length,back);length=float(np.linalg.norm(right))
    if length<=1e-9:raise ValueError('相机朝上方向无效 / Invalid camera up direction')
    right/=length;up=np.cross(back,right)
    return np.column_stack((right,up,back)),distance


def validate_keyframes(keys):
    """Return finite, orthonormal cameras with a strictly increasing timeline."""
    if not isinstance(keys,(list,tuple)) or not 2<=len(keys)<=1000:
        raise ValueError('请设置 2–1000 个关键帧 / Set 2–1000 keyframes')
    result=[]
    for key in keys:
        try:
            stamp=float(key['time']);fovy=float(key.get('fovy',35))
            pose={name:_vector(key[name]).tolist() for name in ('eye','center','up')}
        except (KeyError,TypeError,AttributeError):
            raise ValueError('关键帧数据不完整 / Incomplete keyframe') from None
        if not math.isfinite(stamp) or stamp<0 or stamp>1800:
            raise ValueError('时间须在 0–1800 秒内 / Time must be within 0–1800 seconds')
        if not math.isfinite(fovy) or not 5<=fovy<=120:
            raise ValueError('视角须在 5–120 度内 / Field of view must be 5–120 degrees')
        if not result and stamp!=0:
            raise ValueError('首个关键帧时间须为 0 / First keyframe must start at 0')
        if result and stamp<=result[-1]['time']:
            raise ValueError('关键帧时间须依次增加 / Keyframe times must strictly increase')
        basis,_=_basis(pose);pose['up']=basis[:,1].tolist()
        result.append(dict(time=stamp,**pose,fovy=fovy))
    return result


def _quaternion(matrix):
    """Right-handed camera rotation matrix -> unit quaternion (w, x, y, z)."""
    m=matrix;trace=float(np.trace(m))
    if trace>0:
        s=math.sqrt(trace+1)*2
        q=np.array([s/4,(m[2,1]-m[1,2])/s,(m[0,2]-m[2,0])/s,(m[1,0]-m[0,1])/s])
    else:
        i=int(np.argmax(np.diag(m)));j=(i+1)%3;k=(i+2)%3
        s=math.sqrt(max(0,1+m[i,i]-m[j,j]-m[k,k]))*2
        q=np.zeros(4);q[0]=(m[k,j]-m[j,k])/s;q[i+1]=s/4
        q[j+1]=(m[j,i]+m[i,j])/s;q[k+1]=(m[k,i]+m[i,k])/s
    return q/np.linalg.norm(q)


def _rotation(q):
    w,x,y,z=q
    return np.array([[1-2*(y*y+z*z),2*(x*y-z*w),2*(x*z+y*w)],
                     [2*(x*y+z*w),1-2*(x*x+z*z),2*(y*z-x*w)],
                     [2*(x*z-y*w),2*(y*z+x*w),1-2*(x*x+y*y)]])


def camera_at(keys,stamp):
    """Smooth stop/start between keys; quaternion slerp avoids orbit collapse.

    Keys are expected to have passed validate_keyframes. The end positions are
    returned exactly. Interpolation preserves camera distance and roll.
    """
    stamp=float(stamp)
    if not math.isfinite(stamp):raise ValueError('时间无效 / Invalid time')
    def pose(key):return {name:list(key[name]) if name!='fovy' else key[name]
                          for name in ('eye','center','up','fovy')}
    if stamp<=keys[0]['time']:return pose(keys[0])
    if stamp>=keys[-1]['time']:return pose(keys[-1])
    i=bisect.bisect_right([key['time'] for key in keys],stamp)-1
    a,b=keys[i:i+2]
    if stamp==a['time']:return pose(a)
    t=(stamp-a['time'])/(b['time']-a['time']);t=t*t*(3-2*t)
    ra,da=_basis(a);rb,db=_basis(b);qa,qb=_quaternion(ra),_quaternion(rb)
    dot=float(np.dot(qa,qb))
    if dot<0:qb=-qb;dot=-dot
    dot=min(1,max(-1,dot))
    if dot>.9995:q=qa*(1-t)+qb*t;q/=np.linalg.norm(q)
    else:
        angle=math.acos(dot);q=(math.sin((1-t)*angle)*qa+math.sin(t*angle)*qb)/math.sin(angle)
    rotation=_rotation(q);center=np.asarray(a['center'])*(1-t)+np.asarray(b['center'])*t
    eye=center+rotation[:,2]*(da*(1-t)+db*t)
    return dict(eye=eye.tolist(),center=center.tolist(),up=rotation[:,1].tolist(),fovy=a['fovy']*(1-t)+b['fovy']*t)


def sample_frames(keys,fps):
    keys=validate_keyframes(keys)
    if fps not in FRAME_RATES:raise ValueError('帧率请选择 24、30 或 60 / Select 24, 30 or 60 fps')
    count=round(keys[-1]['time']*fps)
    if count<2:raise ValueError('视频至少需要两帧 / Video needs at least two frames')
    # Include both endpoint poses; playback duration is count/fps, rounded to a frame.
    return [camera_at(keys,keys[-1]['time']*i/(count-1)) for i in range(count)]


def _tool(name):
    bundled=RUNTIME/(name+'.exe')
    if bundled.is_file():return bundled
    found=shutil.which(name)
    if found:return Path(found)
    raise RuntimeError('缺少视频组件 / Missing video component: '+name)


def _stop(process):
    if process is not None and process.poll() is None:
        process.terminate()
        try:process.wait(timeout=3)
        except subprocess.TimeoutExpired:process.kill();process.wait()


def _tail(path):
    try:
        with path.open('rb') as stream:
            stream.seek(max(0,path.stat().st_size-3000))
            return stream.read().decode('utf-8',errors='replace')
    except OSError:return ''


def render_video(source,output,keys,resolution='1080p',fps=30,control=None,clip_box=None):
    """Prepare original textures, stream native frames, verify, then publish MP4."""
    control=control or Control();control.check();started=time.monotonic()
    output=Path(output).expanduser().resolve()
    if output.exists():raise ValueError('视频文件已存在，请选择新文件名 / Video exists; choose a new filename')
    if output.suffix.lower()!='.mp4':raise ValueError('视频输出须为 .mp4 / Video output must use .mp4')
    if resolution not in RESOLUTIONS:raise ValueError('分辨率请选择 1080p 或 4K / Select 1080p or 4K')
    keys=validate_keyframes(keys);frames=sample_frames(keys,fps);width,height=RESOLUTIONS[resolution]
    if clip_box is not None:
        try:clip_box=[float(x) for x in clip_box]
        except (ValueError,TypeError):raise ValueError('剪切盒无效 / Invalid clipping box') from None
        if len(clip_box)!=6 or not all(math.isfinite(x) for x in clip_box) or any(clip_box[i]>=clip_box[i+3] for i in range(3)):
            raise ValueError('剪切盒无效 / Invalid clipping box')
    source=resolve_model(source);renderer=_tool('mesh_render');ffmpeg=_tool('ffmpeg');ffprobe=_tool('ffprobe')
    output.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='share_video_model_') as model_work, \
         tempfile.TemporaryDirectory(prefix='.share_video_',dir=output.parent) as video_work:
        work=Path(video_work);prepared=source
        if source.suffix.lower()!='.osgb':
            control.log('准备原始精度模型和贴图 / Preparing original-resolution model and textures',0)
            stage=Control(lambda message,percent:control.log(message,percent*.35),control.event)
            convert_isolated(source,Path(model_work)/'model','osgb',stage,preview=False)
            prepared=Path(model_work)/'model/osgb/Model.osgb'
        control.check();control.log('逐帧渲染视频 / Rendering video frames',35)
        job=work/'job.json';progress=work/'progress.json';encoded=work/'video.mp4'
        write_json(job,dict(source=str(prepared),width=width,height=height,fps=fps,frames=frames,
                            clip_box=clip_box,progress=str(progress)))
        render_log=work/'render.log';encode_log=work/'encode.log'
        env=os.environ.copy();env['OSG_LIBRARY_PATH']=str(RUNTIME/'osgPlugins-3.6.5')
        env['PATH']=str(RUNTIME)+os.pathsep+env.get('PATH','')
        flags=getattr(subprocess,'CREATE_NO_WINDOW',0);render=None;encode=None;last=-1
        command=[str(ffmpeg),'-hide_banner','-nostdin','-v','error','-f','rawvideo',
                 '-pixel_format','rgb24','-video_size',f'{width}x{height}','-framerate',str(fps),
                 '-i','pipe:0','-an','-vf','vflip','-c:v','libx264','-preset','medium',
                 '-crf','18','-pix_fmt','yuv420p','-threads','2','-filter_threads','1',
                 '-movflags','+faststart','-n',str(encoded)]
        with render_log.open('wb') as rlog,encode_log.open('wb') as elog:
            try:
                render=subprocess.Popen([str(renderer),str(job)],cwd=work,env=env,stdout=subprocess.PIPE,stderr=rlog,creationflags=flags)
                encode=subprocess.Popen(command,cwd=work,env=env,stdin=render.stdout,stdout=elog,stderr=subprocess.STDOUT,creationflags=flags)
                render.stdout.close()
                while render.poll() is None or encode.poll() is None:
                    control.check()
                    if encode.poll() is not None and encode.returncode:
                        raise RuntimeError('视频编码失败 / Encoding failed: '+_tail(encode_log))
                    if render.poll() is not None and render.returncode:
                        raise RuntimeError('模型渲染失败 / Rendering failed: '+_tail(render_log))
                    try:
                        current=json.loads(progress.read_text(encoding='utf-8'));frame=int(current.get('frame',0))
                        if frame!=last:
                            last=frame;control.log(f'渲染视频 / Rendering video · {frame}/{len(frames)}',35+55*min(1,frame/len(frames)))
                    except (OSError,ValueError):pass
                    control.event.wait(.1)
                if render.returncode:raise RuntimeError('模型渲染失败 / Rendering failed: '+_tail(render_log))
                if encode.returncode:raise RuntimeError('视频编码失败 / Encoding failed: '+_tail(encode_log))
            finally:_stop(render);_stop(encode)
        control.check()
        try:render_state=json.loads(progress.read_text(encoding='utf-8'))
        except (OSError,ValueError):raise RuntimeError('渲染结果不完整 / Incomplete render result') from None
        if render_state.get('state')!='succeeded' or render_state.get('frame')!=len(frames):
            raise RuntimeError('视频帧未完整生成 / Not all video frames were rendered')
        control.log('正在自动检查视频 / Checking video automatically',92)
        probe=control.run([ffprobe,'-v','error','-select_streams','v:0','-count_frames',
                           '-show_entries','stream=codec_name,width,height,nb_read_frames,r_frame_rate,duration',
                           '-of','json',encoded],work)
        try:
            stream=json.loads(probe)['streams'][0];count=int(stream['nb_read_frames'])
            rate=stream['r_frame_rate'].split('/');actual_fps=float(rate[0])/float(rate[1])
            duration=float(stream['duration'])
            passed=(stream['codec_name']=='h264' and stream['width']==width and stream['height']==height
                    and count==len(frames) and abs(actual_fps-fps)<1e-6 and abs(duration-count/fps)<=1/fps)
        except (ValueError,KeyError,IndexError,ZeroDivisionError,TypeError):passed=False
        if not passed:raise RuntimeError('视频完整性检查未通过 / Video integrity check failed')
        control.log('正在检查视频解码 / Checking video decoding',96)
        control.run([ffmpeg,'-hide_banner','-nostdin','-v','error','-xerror','-err_detect','explode',
                     '-threads','2','-i',encoded,'-map','0:v:0','-an','-threads','2',
                     '-f','null','-'],work)
        control.check()
        report=dict(state='succeeded',source=str(source),output=str(output),resolution=resolution,
                    width=width,height=height,fps=fps,frames=count,duration=duration,
                    codec='h264',quality='CRF 18',textures='original',clip_box=clip_box,
                    seconds=round(time.monotonic()-started,2),checks='passed',keyframes=keys)
        # Windows rename fails if another process created the destination meanwhile.
        # Explicit recheck also protects POSIX development runs in normal use.
        if output.exists():raise ValueError('视频文件已存在 / Video output already exists')
        encoded.rename(output)
        control.log('视频导出完成 / Video exported · '+str(output),100)
        return report
