from pathlib import Path
import shutil

root=Path(__file__).parent
osg=root/'vendor/osg/OpenSceneGraph-3.6.5-VC2022-64-2025-04/bin'
dest=root/'runtime';dest.mkdir(exist_ok=True)
for name in ['osg.dll','osgDB.dll','osgUtil.dll','osgGA.dll','osgViewer.dll','osgText.dll','OpenThreads.dll','libpng16.dll','zlib.dll']:
    shutil.copy2(osg/name,dest/name)
plugins=dest/'osgPlugins-3.6.5';plugins.mkdir(exist_ok=True)
for name in ['osg','serializers_osg','jpeg','png','obj','ply','stl']:
    shutil.copy2(osg/'osgPlugins-3.6.5'/f'osgdb_{name}.dll',plugins)
shutil.copy2(root/'build/native/Release/mesh_writer.exe',dest)
for name in ['reader','viewer']:shutil.copy2(root/f'build/native/Release/mesh_{name}.exe',dest)
for name in ['ktx.exe','ktx.dll']:shutil.copy2(root/'vendor/ktx/bin'/name,dest)
redist=Path(r'C:\UE\BuildTools2022\VC\Redist\MSVC')
if redist.exists():
    crt=sorted(redist.glob('*/x64/Microsoft.VC143.CRT'))[-1]
    for p in crt.glob('*.dll'):shutil.copy2(p,dest)
print('Runtime ready:',dest)
