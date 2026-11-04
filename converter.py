import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
import numpy as np
from gltf import Glb
from tiles import Tile, flatten, load_tiles, obj_nodes
from formats import reader, mesh_tree
from clipping import clip_primitive
from quality import ExportQuality
from model_paths import resolve_model

RUNTIME=Path(getattr(sys,'_MEIPASS',Path(__file__).parent))/'runtime'


class Cancelled(Exception):pass


def write_json(path, value):
    path=Path(path);temp=path.with_suffix(path.suffix+'.tmp')
    temp.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
    # Windows readers may briefly hold the destination without delete sharing.
    for attempt in range(8):
        try:temp.replace(path);return
        except PermissionError:
            if attempt==7:raise
            time.sleep(.025*(attempt+1))


class Control:
    def __init__(self, callback=None, event=None):
        self.callback=callback or (lambda message,percent:print(f'{percent:5.1f}% {message}',flush=True))
        self.event=event or threading.Event()
    def check(self):
        if self.event.is_set():raise Cancelled('用户已取消；保留未完成目录供检查')
    def log(self,text,percent=0):self.check();self.callback(text,percent)
    def run(self,command,cwd):
        self.check()
        env=os.environ.copy();env['OSG_LIBRARY_PATH']=str(RUNTIME/'osgPlugins-3.6.5')
        env['PATH']=str(RUNTIME)+os.pathsep+env.get('PATH','')
        # A file avoids pipe deadlocks while preserving diagnostics from native tools.
        with tempfile.TemporaryFile() as output:
            p=subprocess.Popen([str(x) for x in command],cwd=cwd,env=env,stdout=output,stderr=subprocess.STDOUT,
                               creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            while p.poll() is None:
                if self.event.wait(.1):
                    p.kill();p.wait();self.check()
            output.seek(0);text=output.read().decode('utf-8',errors='replace')
            if p.returncode:raise RuntimeError(f'{Path(command[0]).name} 失败 ({p.returncode}): {text[-4000:]}')
            return text


class ObjWriter:
    def __init__(self,folder,quality=None):
        self.folder=folder;folder.mkdir(parents=True)
        self.obj=(quality.obj_path if quality else folder/'Model.obj').open('wb',buffering=1024*1024)
        self.mtl=(folder/'Model.mtl').open('w',encoding='utf-8',newline='\n');self.material_text=[]
        header=b'# Z-up local coordinates; units: metres; see metadata.xml\nmtllib Model.mtl\n'
        self.obj.write(header)
        if quality:quality.obj_hash.update(header)
        self.v=0;self.vt=0;self.vn=0;self.materials=set();self.faces=0
    def close(self):self.obj.close();self.mtl.close()
    def add(self,part,texture,name,group):
        xyz=part['positions'];uv=part['uv'];normal=part['normals'];idx=part['indices']
        if name not in self.materials:
            self.materials.add(name);c=part['color']
            text=f'newmtl {name}\nKa 1 1 1\nKd {c[0]} {c[1]} {c[2]}\nd {c[3]}\nillum 1\n'
            if texture:text+=f'map_Kd {texture}\n'
            text+='\n';self.mtl.write(text);self.material_text.append(text)
        entry={'materialName':name,'group':group,'vertexBase':self.v,'uvBase':self.vt,'normalBase':self.vn}
        self.v+=len(xyz);self.vt+=len(uv) if uv is not None else 0;self.vn+=len(normal) if normal is not None else 0;self.faces+=len(idx)
        return entry



def input_tree(path):
    path=resolve_model(path,allow_glb_collection=True)
    if path.is_dir():
        for candidate in ['tileset.json','3dtiles/tileset.json','Model.glb','glb/Model.glb','Model.osgb','Model.obj','Model.ply','Model.stl']:
            if (path/candidate).is_file():path=path/candidate;break
        else:
            glbs=sorted(path.rglob('*.glb'))
            if not glbs:raise ValueError('目录中未找到 tileset.json 或 GLB')
            return glb_tree(glbs),path,'glb'
    if not path.is_file():raise FileNotFoundError(f'输入不存在: {path}')
    if path.suffix.lower()=='.json':return load_tiles(path),path,'3dtiles'
    if path.suffix.lower() in ('.glb','.b3dm'):return glb_tree([path]),path,'glb'
    if path.suffix.lower() in ('.ply','.stl','.mesh'):return mesh_tree(path),path,path.suffix[1:].lower()
    raise ValueError('请选择 GLB、tileset.json 或它们所在的目录')


def glb_tree(paths):
    root=Tile(Path('Model.osgb'))
    for i,path in enumerate(paths):
        block=Tile(Path(f'Block_{i}/Block_{i}.osgb'));root.children.append(block)
        with Glb(path) as glb:
            for node,mesh,_ in glb.instances():
                count=len(glb.doc['meshes'][mesh]['primitives'])
                for start in range(0,count,8):
                    block.children.append(Tile(Path(f'Block_{i}/Block_{i}_Node{node}_Part{start//8}.osgb'),
                                               path,instance=node,chunk=(start,min(start+8,count))))
    return root


def metadata(input_path):
    folder=input_path if input_path.is_dir() else input_path.parent
    candidates=[folder/'metadata.xml',folder.parent/'glb/metadata.xml',folder.parent/'osgb/metadata.xml']
    for p in candidates:
        if p.is_file():return p.read_bytes()
    return b'<?xml version="1.0" encoding="UTF-8"?>\n<ModelMetadata version="1.0"><SRS>LOCAL</SRS><SRSOrigin>0, 0, 0</SRSOrigin></ModelMetadata>\n'


def convert(input_path,output_path,formats='both',control=None,clip_box=None,preview=False):
    control=control or Control();source=resolve_model(input_path,allow_glb_collection=True)
    if clip_box is not None:
        clip_box=np.asarray(clip_box,dtype=float)
        if clip_box.shape!=(6,) or not np.isfinite(clip_box).all() or np.any(clip_box[:3]>=clip_box[3:]):raise ValueError('剪切盒范围无效 / Invalid clipping box')
    if source.is_dir():
        for name in ('tileset.json','3dtiles/tileset.json','Model.glb','glb/Model.glb','Model.osgb','Model.obj','Model.ply','Model.stl'):
            if (source/name).is_file():source=source/name;break
    from point_data import is_point_source,crop_points,prepare_points
    if is_point_source(source):
        started=time.monotonic();output=Path(output_path).resolve();base=source.parent
        if output==base or output in base.parents or output.is_relative_to(base):raise ValueError('输出目录必须独立于输入目录')
        if output.exists() and any(output.iterdir()):raise ValueError('输出目录不是空目录')
        if formats not in ('source','pointcache'):
            raise ValueError('点云／高斯请选择“原格式 / Source”导出；三角网格可导出 OBJ、OSGB、3D Tiles / Select Source format for point data')
        output.mkdir(parents=True,exist_ok=True)
        try:
            if formats=='source':report=crop_points(source,output,clip_box,control)
            else:
                manifest=prepare_points(source,output,control,preview=preview)
                info=json.loads(manifest.read_text(encoding='utf-8'))
                report=dict(state='succeeded',source=str(source),output=str(manifest),kind=info['kind'],count=info['count'],preview=preview)
            report.update(seconds=round(time.monotonic()-started,2),formats=formats)
            write_json(output/'conversion_report.json',report)
            write_json(output/'mesh_result.json',dict(state='succeeded',code=0,data={'source_file':Path(report['output']).name}))
            write_json(output/'mesh_progress.json',dict(state='succeeded',progress=100))
            return report
        except Exception as error:
            state='cancelled' if isinstance(error,Cancelled) else 'failed'
            write_json(output/'mesh_result.json',dict(state=state,code=1,error_reason=str(error),data={}))
            raise
    if formats in ('source','pointcache'):raise ValueError('原格式导出用于 LAS 或点／高斯 PLY / Source export requires point data')
    if source.suffix.lower() in ('.obj','.osgb'):
        output=Path(output_path).resolve();base=source.parent
        if output==base or output in base.parents or output.is_relative_to(base):raise ValueError('输出目录必须独立于输入目录')
        if output.exists() and any(output.iterdir()):raise ValueError('输出目录不是空目录')
        with tempfile.TemporaryDirectory(prefix='meshread_') as temp:
            work=Path(temp);control.log('读取网格、材质与最终精度节点 / Reading mesh and materials…')
            job={'source':str(source),'output':str(work/'mesh')}
            if clip_box is not None:job['clipBox']=clip_box.tolist()
            write_json(work/'read.json',job)
            control.run([RUNTIME/'mesh_reader.exe','read.json'],work)
            tree=mesh_tree(work/'mesh/model.mesh')
            return _convert(source,output_path,formats,control,clip_box,preview,(tree,source,source.suffix[1:]))
    return _convert(source,output_path,formats,control,clip_box,preview)


def _convert(input_path,output_path,formats='both',control=None,clip_box=None,preview=False,prepared=None):
    control=control or Control();started=time.time()
    if formats=='3dtiles':
        from mesh_tiles_export import export_tiles
        return export_tiles(input_path,output_path,control,clip_box,prepared)
    if formats not in ('obj','osgb','both'):raise ValueError('无效输出格式')
    control.log('分析输入结构、坐标和文件引用…')
    tree,source,kind=prepared or input_tree(input_path)
    output=Path(output_path).resolve();input_base=source if source.is_dir() else source.parent
    if output==input_base or output in input_base.parents or output.is_relative_to(input_base):
        raise ValueError('输出目录必须独立于输入目录，避免覆盖或混入原数据')
    if output.exists() and any(output.iterdir()):raise ValueError('输出目录不是空目录，请选择新目录')
    all_nodes=list(flatten(tree));selected=set(obj_nodes(tree));want_obj=formats in ('obj','both');want_osg=formats in ('osgb','both')
    if not (RUNTIME/'mesh_writer.exe').is_file():raise RuntimeError('缺少内置转换引擎，请运行完整软件包')
    output.mkdir(parents=True,exist_ok=True)
    if want_osg:(output/'osgb').mkdir()
    report={'source':str(source),'input_kind':kind,'formats':formats,'state':'running','nodes':len(all_nodes),
            'source_contents':sum(n.source is not None for n in all_nodes),'obj_contents':len(selected),
            'warnings':[],'converted':[],'coordinate_policy':'Z_UP, metres; full transforms applied'}
    if kind=='glb':report['warnings'].append('GLB 不含 LOD 树：保留源节点分块，生成静态分页 OSGB，不臆造多级细节。')
    report['warnings'].append('OBJ 是静态最终精度网格；PBR 参数仅映射基础颜色/透明度。')
    progress_file=output/'mesh_progress.json'
    obj=None;quality=None;global_min=np.full(3,np.inf);global_max=-global_min
    completed=0;geometry_count=0;empty_nodes=set()
    report['clip_box']=list(clip_box) if clip_box is not None else None
    report['preview_textures']=preview
    write_json(output/'conversion_report.json',report)
    try:
        quality=ExportQuality(control) if want_obj and not preview else None
        obj=ObjWriter(output/'obj',quality) if want_obj else None
        with tempfile.TemporaryDirectory(prefix='meshconvert_') as temp:
            work=Path(temp)
            # Reverse order ensures child coarse files exist when writing parent LOD pages.
            for node in reversed(all_nodes):
                control.check();completed+=1;percent=(90 if quality else 100)*(completed-1)/len(all_nodes)
                label=str(node.output)
                if completed==1 or completed%10==0 or node.source:
                    control.log(f'[{completed}/{len(all_nodes)}] {label}',percent)
                write_json(progress_file,{'progress':round(percent,2),'state':'running','current':label})
                do_obj=obj is not None and node in selected
                if not want_osg and not do_obj:continue
                primitives=[];textures={};tile_min=np.full(3,np.inf);tile_max=-tile_min
                for p in work.iterdir():
                    if p.is_file():p.unlink()
                buffer=work/'geometry.bin'
                if node.source:
                    with reader(node.source) as glb,buffer.open('wb') as binary:
                        for part in glb.primitives(node.transform,node.instance,node.chunk):
                            control.check()
                            if clip_box is not None:part=clip_primitive(part,clip_box)
                            if not len(part['positions']):continue
                            geometry_count+=len(part['indices'])
                            xyz=part['positions'];tile_min=np.minimum(tile_min,xyz.min(axis=0));tile_max=np.maximum(tile_max,xyz.max(axis=0))
                            entry={'offset':binary.tell(),'vertices':len(xyz),'indices':part['indices'].size,
                                   'uv':part['uv'] is not None,'normals':part['normals'] is not None,'color':part['color'],
                                   'attributesDouble':True}
                            for key in ['doubleSided','alphaMode','alphaCutoff']:
                                if key in part['material']:entry[key]=part['material'][key]
                            texpath=None;digest='plain'
                            if part['texture'] is not None:
                                tid=part['texture']
                                if tid not in textures:
                                    data,ext,sampler=glb.image(tid);digest=hashlib.sha256(data).hexdigest()[:24]
                                    texpath=work/(digest+ext);texpath.write_bytes(data)
                                    if ext=='.ktx2':
                                        png=texpath.with_suffix('.png')
                                        control.run([RUNTIME/'ktx.exe','extract','--transcode','rgba8',texpath.name,png.name],work)
                                        texpath=png
                                    if preview:
                                        from PIL import Image
                                        with Image.open(texpath) as im:
                                            if max(im.size)>512:
                                                im.thumbnail((512,512));im.save(texpath)
                                    textures[tid]=(texpath,digest,sampler)
                                texpath,digest,sampler=textures[tid]
                                entry['texture']=texpath.name;entry.update({k:v for k,v in sampler.items() if k in ('wrapS','wrapT','minFilter','magFilter')})
                            if do_obj:
                                texture_name='tex_'+texpath.name if texpath else None
                                if quality and texpath:quality.remember_texture(texpath,texture_name)
                                if texpath and not (obj.folder/texture_name).exists():shutil.copy2(texpath,obj.folder/texture_name)
                                material_name='mat_'+hashlib.sha256((digest+json.dumps(part['material'],sort_keys=True)).encode()).hexdigest()[:24]
                                entry.update(obj.add(part,texture_name,material_name,f'{node.output.stem}_n{part["node"]}_p{part["primitive"]}'))
                                global_min=np.minimum(global_min,xyz.min(axis=0));global_max=np.maximum(global_max,xyz.max(axis=0))
                            if want_osg or do_obj:
                                for key in ('positions','uv','normals','indices'):
                                    arr=part[key]
                                    if arr is not None:np.asarray(arr,dtype='<u4' if key=='indices' else '<f8').tofile(binary)
                                primitives.append(entry)
                    if np.isfinite(tile_min).all() and kind!='3dtiles':
                        node.center=((tile_min+tile_max)/2).tolist();node.radius=float(np.linalg.norm(tile_max-tile_min)/2)
                node.children=[c for c in node.children if c not in empty_nodes]
                if not primitives and not node.children:
                    empty_nodes.add(node);continue
                if node.children and kind!='3dtiles':
                    lo=np.min([np.array(c.center)-c.radius for c in node.children],axis=0)
                    hi=np.max([np.array(c.center)+c.radius for c in node.children],axis=0)
                    node.center=((lo+hi)/2).tolist();node.radius=float(np.linalg.norm(hi-lo)/2)
                if want_osg or do_obj:
                    destination=output/'osgb'/node.output
                    if want_osg:destination.parent.mkdir(parents=True,exist_ok=True)
                    child_page=node.output.with_stem(node.output.stem+'_children')
                    job={'writeOsg':want_osg,'output':'result.osgb','primitives':primitives,'children':[],
                         'center':node.center,'radius':max(node.radius,.001),'refine':node.refine,
                         'threshold':max(1,min(1e8,2*node.radius/max(node.error,1e-9)*16)),
                         'childrenPage':child_page.name,'childrenOutput':'children.osgb'}
                    if primitives:job['buffer']=buffer.name
                    if do_obj:job['objOutput']='part.obj'
                    for child_index,c in enumerate(node.children if want_osg else []):
                        rel=os.path.relpath(c.output,node.output.parent).replace('\\','/')
                        child={'path':rel,'center':c.center,'radius':max(c.radius,.001)}
                        if primitives:
                            local=f'child_{child_index}.osgb';shutil.copy2(output/'osgb'/c.output,work/local)
                            child.update(localFile=local,prefix=str(Path(rel).parent).replace('\\','/'))
                        job['children'].append(child)
                    write_json(work/'job.json',job)
                    control.run([RUNTIME/'mesh_writer.exe','write','job.json'],work)
                    if do_obj and quality:
                        quality.check_chunk(work/'part.obj',buffer,primitives,
                                            lambda:control.run([RUNTIME/'mesh_writer.exe','write','job.json'],work))
                    if want_osg:shutil.copy2(work/'result.osgb',destination)
                    if do_obj:
                        if quality:quality.append(work/'part.obj',obj.obj)
                        else:
                            with (work/'part.obj').open('rb') as part_file:shutil.copyfileobj(part_file,obj.obj,1024*1024)
                    if (work/'children.osgb').is_file():shutil.copy2(work/'children.osgb',output/'osgb'/child_page)
                report['converted'].append({'output':label,'source':str(node.source) if node.source else None,
                                            'primitives':len(primitives),'obj':do_obj})
        if not geometry_count or (obj is not None and not obj.faces):raise ValueError('剪切盒内没有最终精度网格 / No final-resolution geometry inside clipping box')
        material_text=''
        if obj:
            obj.close();material_text=''.join(obj.material_text)
            report.update(obj_vertices=obj.v,obj_triangles=obj.faces,obj_materials=len(obj.materials));obj=None
        for fmt in ('obj','osgb'):
            folder=output/fmt
            if folder.exists():(folder/'metadata.xml').write_bytes(metadata(source))
        contract=source.parent/'coordinate_contract.json'
        if contract.is_file():shutil.copy2(contract,output/'coordinate_contract.json')
        if quality:
            report['quality']=quality.finish(output/'obj',material_text,metadata(source))
            write_json(output/'quality_report.json',report['quality'])
        data={'progress':100}
        if want_obj:data.update(obj_path='obj',obj_merge_flag=1,obj_model_list=['obj/Model.obj'],obj_material_list=['obj/Model.mtl'])
        if want_osg:data.update(osgb_path='osgb',osgb_root='osgb/Model.osgb',osgb_model_list=['osgb/Model.osgb'])
        report.update(state='succeeded',seconds=round(time.time()-started,2))
        if np.isfinite(global_min).all():report['obj_bounds']=[global_min.tolist(),global_max.tolist()]
        write_json(output/'conversion_report.json',report)
        write_json(output/'mesh_result.json',{'code':0,'data':data,'engine_code':0,'error_reason':'','message':'','state':'succeeded','taskState':2})
        write_json(progress_file,{'progress':100,'state':'succeeded'})
        control.log(f'转换完成：{output}',100)
        return report
    except Exception as e:
        if obj:obj.close()
        state='cancelled' if isinstance(e,Cancelled) else 'failed'
        report.update(state=state,error=str(e),seconds=round(time.time()-started,2))
        if quality:
            quality.report.update(state=state,error=str(e));report['quality']=quality.report
            write_json(output/'quality_report.json',quality.report)
        write_json(output/'conversion_report.json',report)
        write_json(output/'mesh_result.json',{'code':1,'state':state,'error_reason':str(e),'data':{}})
        write_json(progress_file,{'progress':round(100*completed/len(all_nodes),2),'state':state})
        raise
    finally:
        if quality:quality.close()
