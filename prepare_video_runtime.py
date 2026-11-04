"""Bundle the installed FFmpeg command-line tools with their distribution notice."""
from pathlib import Path
import shutil
import subprocess


def prepare():
    root=Path(__file__).parent;runtime=root/'runtime';notice=root/'licenses/FFmpeg'
    runtime.mkdir(exist_ok=True);notice.mkdir(parents=True,exist_ok=True)
    executable=shutil.which('ffmpeg')
    if not executable:raise RuntimeError('Install FFmpeg with ffprobe before packaging video export')
    folder=Path(executable).resolve().parent;distribution=folder.parent
    for name in ('ffmpeg.exe','ffprobe.exe'):
        source=folder/name
        if not source.is_file():raise RuntimeError('Missing '+str(source))
        shutil.copy2(source,runtime/name)
    for name in ('LICENSE','README.txt'):
        source=distribution/name
        if not source.is_file():raise RuntimeError('FFmpeg distribution notice missing: '+str(source))
        shutil.copy2(source,notice/name)
    version=subprocess.run([str(folder/'ffmpeg.exe'),'-version'],capture_output=True,text=True,check=True)
    (notice/'build-info.txt').write_text(version.stdout,encoding='utf-8')
    (notice/'integration.txt').write_text(
        'SHARE3DCAM Mesh Studio invokes the unmodified FFmpeg and ffprobe executables as separate processes.\n'
        'FFmpeg project: https://ffmpeg.org/\n'
        'Official command documentation: https://ffmpeg.org/ffmpeg.html\n'
        'Raw RGB input: https://ffmpeg.org/ffmpeg-formats.html#rawvideo\n'
        'Vertical flip: https://ffmpeg.org/ffmpeg-filters.html#vflip\n'
        'Build distributor: https://www.gyan.dev/ffmpeg/builds/\n'
        'Version, source commit, license and build configuration are preserved in README.txt and build-info.txt.\n'
        'These executables are distributed under the license in LICENSE; they remain replaceable by compatible builds.\n',encoding='utf-8')
    print('FFmpeg runtime and notices ready')


if __name__=='__main__':prepare()
