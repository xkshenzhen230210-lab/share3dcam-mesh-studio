"""Headless export checks. Repairs only reconstruct generated data from trusted inputs."""
import hashlib
import shutil
import tempfile
import warnings
from pathlib import Path
import numpy as np
from PIL import Image


class QualityError(RuntimeError):
    pass


def file_hash(path, control):
    digest=hashlib.sha256()
    with Path(path).open('rb') as stream:
        while block:=stream.read(1024*1024):
            control.check();digest.update(block)
    return digest.hexdigest()


def next_record(stream):
    for line in stream:
        if line.strip():return line.strip()
    raise QualityError('输出网格记录不完整 / Incomplete mesh records')


def compare_records(stream, tag, expected, control, face_width=0, slashes=0):
    """Independent text parsing in bounded batches; no whole-model arrays."""
    expected=np.asarray(expected)
    for start in range(0,len(expected),4096):
        control.check();batch=expected[start:start+4096];rows=[]
        for _ in batch:
            line=next_record(stream)
            if not line.startswith(tag+' '):raise QualityError('网格记录顺序异常 / Invalid mesh record order')
            value=line[len(tag)+1:]
            if face_width:
                tokens=value.split()
                if len(tokens)!=3 or any(t.count('/')!=slashes for t in tokens):
                    raise QualityError('面索引格式异常 / Invalid face indices')
                for token in tokens:
                    parts=token.split('/')
                    if face_width==2 and slashes==2:
                        valid=bool(parts[0] and not parts[1] and parts[2])
                    else:valid=len(parts)==face_width and all(parts)
                    if not valid:raise QualityError('面属性索引格式异常 / Invalid face attribute indices')
                value=value.replace('/',' ')
            elif len(value.split())!=batch.shape[1]:
                raise QualityError('顶点属性维度异常 / Invalid vertex attribute dimensions')
            rows.append(value)
        try:
            with warnings.catch_warnings():
                warnings.simplefilter('error')
                actual=np.fromstring(' '.join(rows),sep=' ',dtype=expected.dtype).reshape(batch.shape)
        except (ValueError,Warning) as error:
            raise QualityError('网格数值记录异常 / Invalid mesh numeric records') from error
        if not np.isfinite(actual).all() or not np.array_equal(actual,batch):
            raise QualityError('输出精度或面索引不一致 / Export precision or face index mismatch')


def verify_chunk(path, buffer, entries, control):
    with Path(path).open(encoding='utf-8') as stream,Path(buffer).open('rb') as binary:
        for entry in entries:
            if next_record(stream)!='g '+entry['group'] or next_record(stream)!='usemtl '+entry['materialName']:
                raise QualityError('输出分组或材质引用异常 / Group or material mismatch')
            binary.seek(entry['offset']);count=entry['vertices']
            for tag,width,present in [('v',3,True),('vt',2,entry['uv']),('vn',3,entry['normals'])]:
                if present:
                    values=np.fromfile(binary,dtype='<f8',count=count*width)
                    if values.size!=count*width:raise QualityError('网格源缓冲不完整 / Incomplete source buffer')
                    compare_records(stream,tag,values.reshape(count,width),control)
            idx=np.fromfile(binary,dtype='<u4',count=entry['indices']).astype(np.int64)
            if len(idx)!=entry['indices'] or len(idx)%3 or (len(idx) and idx.max()>=count):
                raise QualityError('源网格索引越界 / Source index out of bounds')
            columns=[idx+entry['vertexBase']+1]
            if entry['uv']:columns.append(idx+entry['uvBase']+1)
            if entry['normals']:columns.append(idx+entry['normalBase']+1)
            expected=np.stack(columns,axis=1).reshape(-1,3*len(columns))
            compare_records(stream,'f',expected,control,len(columns),2 if entry['normals'] else int(entry['uv']))
        if any(line.strip() for line in stream):raise QualityError('输出存在额外网格记录 / Unexpected extra mesh records')


class ExportQuality:
    def __init__(self, control):
        self.control=control
        self.temp=tempfile.TemporaryDirectory(prefix='meshquality_')
        self.folder=Path(self.temp.name)
        self.obj_path=self.folder/'Model.obj'
        self.obj_hash=hashlib.sha256()
        self.textures={}
        self.report={'state':'checking','repairs':0,'checked_chunks':0,'checked_textures':0,
                     'position_uv_normal_roundtrip':'exact_float64','scope':'OBJ generated geometry, indices, groups, base materials, texture bytes and decoding; source defects are preserved.'}

    def repaired(self):
        self.report['repairs']+=1

    def check_chunk(self, path, buffer, entries, regenerate):
        for attempt in range(2):
            try:
                verify_chunk(path,buffer,entries,self.control)
                self.report['checked_chunks']+=1
                return
            except (QualityError,OSError,UnicodeError):
                if attempt:raise
                self.repaired();regenerate()

    def append(self, source, target):
        with Path(source).open('rb') as stream:
            while block:=stream.read(1024*1024):
                self.control.check();target.write(block);self.obj_hash.update(block)

    def remember_texture(self, source, name):
        if name not in self.textures:
            digest=file_hash(source,self.control);backup=self.folder/name
            shutil.copyfile(source,backup)
            if file_hash(backup,self.control)!=digest:raise QualityError('贴图暂存校验失败 / Texture staging check failed')
            self.textures[name]=(backup,digest)

    def restore_file(self, source, target, expected_hash):
        for attempt in range(2):
            if Path(target).is_file() and file_hash(target,self.control)==expected_hash:return
            if attempt:raise QualityError('自动恢复后校验未通过 / Automatic recovery did not pass verification')
            self.repaired();shutil.copyfile(source,target)

    def finish(self, folder, material_text, metadata_bytes):
        self.control.log('后台检查模型和贴图 / Checking model and textures…',94)
        expected=self.obj_hash.hexdigest()
        if file_hash(self.obj_path,self.control)!=expected:
            raise QualityError('暂存模型校验未通过，未发布成功结果 / Staged mesh verification failed')
        # Publish only independently checked geometry; re-copy automatically on an I/O mismatch.
        target=folder/'Model.obj';shutil.copyfile(self.obj_path,target)
        self.restore_file(self.obj_path,target,expected)
        for name,data in [('Model.mtl',material_text.encode('utf-8')),('metadata.xml',metadata_bytes)]:
            target=folder/name
            if not target.is_file() or target.read_bytes()!=data:
                self.repaired();target.write_bytes(data)
            if target.read_bytes()!=data:raise QualityError('材质或坐标元数据恢复失败 / Material or metadata recovery failed')
        for index,(name,(backup,digest)) in enumerate(self.textures.items()):
            self.control.check();target=folder/name;self.restore_file(backup,target,digest)
            try:
                with Image.open(target) as image:image.load()
            except (OSError,ValueError) as error:
                raise QualityError('源贴图无法完整解码 / Source texture cannot be fully decoded: '+name) from error
            self.report['checked_textures']+=1
            if index%25==0:self.control.log('后台检查贴图 / Checking textures…',95+4*(index+1)/max(1,len(self.textures)))
        self.report.update(state='passed',obj_sha256=expected)
        return self.report

    def close(self):
        self.temp.cleanup()
