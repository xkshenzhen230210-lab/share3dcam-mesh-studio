"""Fetch pinned build dependencies; does not install system-wide software."""
from pathlib import Path
import hashlib
import shutil
import subprocess
import urllib.request

ROOT=Path(__file__).parent
VENDOR=ROOT/'vendor';VENDOR.mkdir(exist_ok=True)
URLS={
    'osg.7z':'https://objexx.com/OpenSceneGraph/OpenSceneGraph-3.6.5-VC2022-64-2025-04.7z',
    'ktx-installer.exe':'https://github.com/KhronosGroup/KTX-Software/releases/download/v4.4.2/KTX-Software-4.4.2-Windows-x64.exe',
    'json.hpp':'https://raw.githubusercontent.com/nlohmann/json/v3.12.0/single_include/nlohmann/json.hpp',
}
SHA256={
    'osg.7z':'1e03bc5cd1526bc5c9ae13980fc6d04ec6be196ea62e2cedb42068b96abaef35',
    'ktx-installer.exe':'1f323b0fec19794f5e6c0425a61d4b1da396872a10be862d105f4f4b2d2957fe',
    'json.hpp':'aaf127c04cb31c406e5b04a63f1ae89369fccde6d8fa7cdda1ed4f32dfc5de63',
}

def main():
    for name,url in URLS.items():
        target=VENDOR/name
        if not target.is_file():
            print('Downloading',name,flush=True)
            temp=target.with_suffix(target.suffix+'.download');urllib.request.urlretrieve(url,temp);temp.replace(target)
        with target.open('rb') as downloaded:
            if hashlib.file_digest(downloaded,'sha256').hexdigest()!=SHA256[name]:
                raise RuntimeError('依赖 SHA256 不匹配: '+name)
    candidates=[shutil.which('7z'),r'C:\Program Files\7-Zip\7z.exe',r'C:\Program Files\NVIDIA Corporation\NVIDIA App\7z.exe']
    seven=next((p for p in candidates if p and Path(p).is_file()),None)
    if seven is None:raise RuntimeError('请安装 7-Zip 或将 7z.exe 加入 PATH 后再构建。')
    for archive,folder in [('osg.7z','osg'),('ktx-installer.exe','ktx')]:
        if not (VENDOR/folder).exists():
            subprocess.run([seven,'x',str(VENDOR/archive),'-o'+str(VENDOR/folder),'-y','-bso0','-bsp0'],check=True)
    license_dir=ROOT/'licenses';license_dir.mkdir(exist_ok=True)
    for name,url in {
        'OpenSceneGraph-LICENSE.txt':'https://raw.githubusercontent.com/openscenegraph/OpenSceneGraph/OpenSceneGraph-3.6.5/LICENSE.txt',
        'KTX-Software-LICENSE.md':'https://raw.githubusercontent.com/KhronosGroup/KTX-Software/v4.4.2/LICENSE.md',
        'nlohmann-json-LICENSE.txt':'https://raw.githubusercontent.com/nlohmann/json/v3.12.0/LICENSE.MIT',
    }.items():
        target=license_dir/name
        if not target.exists():urllib.request.urlretrieve(url,target)

if __name__=='__main__':main()
