"""Camera keyframes and full-resolution, independently verified MP4 rendering."""
from functools import lru_cache
import json
import math
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

import numpy as np

from converter import Control, RUNTIME
from model_paths import resolve_model
from supervisor import convert_isolated
from video_process import render_stream
from camera_motion import CameraPath
from spatial_frame import ClipBox

RESOLUTIONS={'1080p':(1920,1080),'4K':(3840,2160)}
FRAME_RATES=(24,30,60)
RENDER_LOAD_TIMEOUT=600
RENDER_CONTEXT_TIMEOUT=45
RENDER_STALL_TIMEOUT=180


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


@lru_cache(maxsize=4)
def _compiled_path(signature):
    # Cache immutable values, never mutable lists owned by the keyframe editor.
    keys=[dict(time=k[0],eye=list(k[1:4]),center=list(k[4:7]),up=list(k[7:10]),fovy=k[10]) for k in signature]
    return CameraPath(keys,[_basis(key) for key in keys])


def camera_path(keys):
    """Compile validated keyframes once for shared preview/export motion."""
    signature=tuple((k['time'],*k['eye'],*k['center'],*k['up'],k['fovy']) for k in keys)
    return _compiled_path(signature)


def camera_at(keys,stamp):
    """Continuous motion through intermediate keys; exact key poses and holds."""
    return camera_path(keys).at(stamp)


def sample_frames(keys,fps):
    keys=validate_keyframes(keys)
    if fps not in FRAME_RATES:raise ValueError('帧率请选择 24、30 或 60 / Select 24, 30 or 60 fps')
    count=round(keys[-1]['time']*fps)
    if count<2:raise ValueError('视频至少需要两帧 / Video needs at least two frames')
    # Include both endpoint poses; playback duration is count/fps, rounded to a frame.
    path=camera_path(keys)
    return [path.at(keys[-1]['time']*i/(count-1)) for i in range(count)]


def _tool(name):
    bundled=RUNTIME/(name+'.exe')
    if bundled.is_file():return bundled
    found=shutil.which(name)
    if found:return Path(found)
    raise RuntimeError('缺少视频组件 / Missing video component: '+name)


def render_video(source,output,keys,resolution='1080p',fps=30,control=None,clip_box=None):
    """Prepare original textures, stream native frames, verify, then publish MP4."""
    control=control or Control();control.check();started=time.monotonic()
    output=Path(output).expanduser().resolve()
    if output.exists():raise ValueError('视频文件已存在，请选择新文件名 / Video exists; choose a new filename')
    if output.suffix.lower()!='.mp4':raise ValueError('视频输出须为 .mp4 / Video output must use .mp4')
    if resolution not in RESOLUTIONS:raise ValueError('分辨率请选择 1080p 或 4K / Select 1080p or 4K')
    keys=validate_keyframes(keys);frames=sample_frames(keys,fps);width,height=RESOLUTIONS[resolution]
    if clip_box is not None:
        clip_box=ClipBox(clip_box).tolist()
    source=resolve_model(source);renderer=_tool('mesh_render');ffmpeg=_tool('ffmpeg');ffprobe=_tool('ffprobe')
    output.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='share_video_model_') as model_work, \
         tempfile.TemporaryDirectory(prefix='.share_video_',dir=output.parent) as video_work:
        work=Path(video_work);prepared=source
        from point_data import is_point_source
        if is_point_source(source):
            control.log('准备完整精度点云／高斯 / Preparing full-resolution points and Gaussians',0)
            stage=Control(lambda message,percent:control.log(message,percent*.35),control.event)
            point_source=source
            if clip_box is not None:
                cropped=convert_isolated(source,Path(model_work)/'cropped','source',stage,clip_box=clip_box)
                point_source=Path(cropped['output'])
            convert_isolated(point_source,Path(model_work)/'points','pointcache',stage,preview=False)
            prepared=Path(model_work)/'points/model.spoints'
        elif source.suffix.lower()!='.osgb':
            control.log('准备原始精度模型和贴图 / Preparing original-resolution model and textures',0)
            stage=Control(lambda message,percent:control.log(message,percent*.35),control.event)
            convert_isolated(source,Path(model_work)/'model','osgb',stage,preview=False)
            prepared=Path(model_work)/'model/osgb/Model.osgb'
        control.check();control.log('启动完整精度视频渲染 / Starting full-resolution rendering',35)
        env=os.environ.copy();env['OSG_LIBRARY_PATH']=str(RUNTIME/'osgPlugins-3.6.5')
        env['PATH']=str(RUNTIME)+os.pathsep+env.get('PATH','')
        request=dict(source=str(prepared),original_source=str(source),width=width,height=height,fps=fps,frames=frames,clip_box=clip_box)
        encoded,render_state,attempts=render_stream(renderer,ffmpeg,request,work,output,env,control,
            dict(load=RENDER_LOAD_TIMEOUT,context=RENDER_CONTEXT_TIMEOUT,stall=RENDER_STALL_TIMEOUT))
        control.check()
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
        report.update(graphics=render_state.get('graphics',{}),memory=render_state.get('memory',{}),render_attempts=attempts)
        # Windows rename fails if another process created the destination meanwhile.
        # Explicit recheck also protects POSIX development runs in normal use.
        if output.exists():raise ValueError('视频文件已存在 / Video output already exists')
        encoded.rename(output)
        control.log('视频导出完成 / Video exported · '+str(output),100)
        return report
