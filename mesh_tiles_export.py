"""Static final-resolution 3D Tiles 1.1 export, with embedded Y-up GLB leaves.

The reader contract is Z-up world positions and OBJ/OSG UVs. Only the GLB
payload converts these back; tile bounds and double-precision translations
remain Z-up (OGC 22-025r4, 6.7.1.6.2). No simplified LOD is fabricated.
"""
import hashlib
import json
import shutil
import struct
import tempfile
import time
from pathlib import Path
from urllib.parse import quote

import numpy as np

from clipping import clip_primitive
from formats import reader
from gltf import Glb, Y_TO_Z, local_uri
from tiles import flatten, load_tiles, obj_nodes


def _digest(data):
    return hashlib.sha256(data).hexdigest()


def _array_digest(array):
    return _digest(np.ascontiguousarray(array).tobytes())


def _box(lo, hi):
    center = lo + (hi - lo) / 2
    # Small padding includes double-precision arithmetic at parent/child bounds.
    half = (hi - lo) / 2 + np.maximum(np.spacing(np.maximum(np.abs(lo), np.abs(hi))) * 4, 1e-9)
    return {'box': [*center.tolist(), half[0], 0., 0., 0., half[1], 0., 0., 0., half[2]]}


def _parts(model, node, clip_box, control):
    for part in model.primitives(node.transform, node.instance, node.chunk):
        control.check()
        if clip_box is not None:
            part = clip_primitive(part, clip_box)
        if len(part['positions']) and len(part['indices']):
            yield part


class _GlbWriter:
    """Spool binary arrays so memory is bounded by a primitive, not a leaf."""
    def __init__(self, work, control):
        self.work = work
        self.control = control
        self.binary = (work / 'tile.bin').open('w+b')
        self.doc = {'asset': {'version': '2.0', 'generator': 'SHARE3DCAM Mesh Studio'},
                    'buffers': [], 'bufferViews': [], 'accessors': [],
                    'meshes': [{'primitives': []}], 'nodes': [{'mesh': 0}],
                    'scenes': [{'nodes': [0]}], 'scene': 0, 'materials': []}
        self.textures = {}
        self.expected = []
        self.max_error = 0.
        self.lo = np.full(3, np.inf)
        self.hi = np.full(3, -np.inf)

    def close(self):
        self.binary.close()

    def view(self, data, target=None):
        self.binary.write(b'\0' * (-self.binary.tell() % 4))
        view = {'buffer': 0, 'byteOffset': self.binary.tell(), 'byteLength': len(data)}
        if target is not None:
            view['target'] = target
        self.binary.write(data)
        self.doc['bufferViews'].append(view)
        return len(self.doc['bufferViews']) - 1

    def accessor(self, array, kind, position=False):
        is_index = kind == 'SCALAR'
        value = {'bufferView': self.view(array.tobytes(), 34963 if is_index else 34962),
                 'componentType': 5125 if is_index else 5126, 'count': len(array), 'type': kind}
        if position:
            value.update(min=array.min(axis=0).tolist(), max=array.max(axis=0).tolist())
        self.doc['accessors'].append(value)
        return len(self.doc['accessors']) - 1

    def texture(self, model, texture):
        if texture in self.textures:
            return self.textures[texture]
        from converter import RUNTIME
        data, ext, sampler = model.image(texture)
        expected_size = None
        if ext == '.ktx2':
            if len(data) < 28 or data[:12] != b'\xabKTX 20\xbb\r\n\x1a\n':
                raise ValueError('KTX2 文件头无效')
            expected_size = struct.unpack_from('<II', data, 20)
            source = self.work / 'texture.ktx2'
            png = self.work / 'texture.png'
            source.write_bytes(data)
            if png.exists():
                png.unlink()
            self.control.run([RUNTIME / 'ktx.exe', 'extract', '--transcode', 'rgba8', source.name, png.name], self.work)
            data, ext = png.read_bytes(), '.png'
        mime = {'.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.png': 'image/png'}.get(ext.lower())
        if mime is None:
            raise ValueError(f'3D Tiles 不支持此基础色图像格式: {ext}')
        from PIL import Image
        import io
        with Image.open(io.BytesIO(data)) as image:
            size = image.size
            image.verify()
        if expected_size is not None and size != expected_size:
            raise ValueError('KTX2 转 PNG 后原图尺寸不一致')
        images = self.doc.setdefault('images', [])
        samplers = self.doc.setdefault('samplers', [])
        textures = self.doc.setdefault('textures', [])
        images.append({'bufferView': self.view(data), 'mimeType': mime})
        sampler = {k: v for k, v in sampler.items() if k in ('wrapS', 'wrapT', 'minFilter', 'magFilter')}
        allowed = {'wrapS': {33071, 33648, 10497}, 'wrapT': {33071, 33648, 10497},
                   'minFilter': {9728, 9729, 9984, 9985, 9986, 9987}, 'magFilter': {9728, 9729}}
        for key, value in sampler.items():
            if value not in allowed[key]:
                raise ValueError(f'3D Tiles 无法保留纹理采样参数 {key}={value}')
        samplers.append(sampler)
        textures.append({'source': len(images)-1, 'sampler': len(samplers)-1})
        result = {'index': len(textures)-1, 'hash': _digest(data), 'size': size, 'sampler': sampler}
        self.textures[texture] = result
        return result

    def add(self, model, part, origin):
        source = part['material']
        extensions = source.get('extensions', {})
        if set(extensions) - {'KHR_materials_unlit'}:
            raise ValueError('3D Tiles 导出暂不支持此材质扩展，请先烘焙为基础颜色纹理')
        material = {k: source[k] for k in ('name', 'alphaMode', 'alphaCutoff', 'doubleSided', 'emissiveFactor') if k in source}
        pbr_source = source.get('pbrMetallicRoughness', {})
        pbr = {k: pbr_source[k] for k in ('metallicFactor', 'roughnessFactor') if k in pbr_source}
        pbr['baseColorFactor'] = list(part['color'])
        if not isinstance(model, Glb):
            # Native mesh-reader output contains baked base color rather than PBR.
            pbr.setdefault('metallicFactor', 0.)
            pbr.setdefault('roughnessFactor', 1.)
            if 'alphaMode' not in material and part['color'][3] < 1:
                material['alphaMode'] = 'BLEND'
        material['pbrMetallicRoughness'] = pbr
        if 'KHR_materials_unlit' in extensions:
            material['extensions'] = {'KHR_materials_unlit': {}}
            self.doc['extensionsUsed'] = ['KHR_materials_unlit']
        texture = None
        if part['texture'] is not None:
            if part['uv'] is None:
                raise ValueError('纹理缺少 UV')
            texture = self.texture(model, part['texture'])
            # The reader has already baked KHR_texture_transform and selected UV set.
            pbr['baseColorTexture'] = {'index': texture['index']}
        xyz = np.asarray((part['positions'] - origin) @ Y_TO_Z[:3, :3], dtype='<f4')
        if not np.isfinite(xyz).all():
            raise ValueError('瓦片范围超出 GLB 浮点坐标范围')
        restored = xyz.astype(float) @ Y_TO_Z[:3, :3].T + origin
        self.max_error = max(self.max_error, float(np.max(np.abs(restored - part['positions']))))
        self.lo = np.minimum(self.lo, restored.min(axis=0))
        self.hi = np.maximum(self.hi, restored.max(axis=0))
        arrays = {'POSITION': xyz}
        if part['uv'] is not None:
            uv = np.asarray(part['uv'], dtype=float).copy()
            uv[:, 1] = 1 - uv[:, 1]
            arrays['TEXCOORD_0'] = np.asarray(uv, dtype='<f4')
        if part['normals'] is not None:
            arrays['NORMAL'] = np.asarray(part['normals'] @ Y_TO_Z[:3, :3], dtype='<f4')
        if any(not np.isfinite(array).all() for array in arrays.values()):
            raise ValueError('UV 或法线包含无效数值')
        attributes = {name: self.accessor(array, 'VEC2' if name == 'TEXCOORD_0' else 'VEC3', name == 'POSITION')
                      for name, array in arrays.items()}
        indices = np.asarray(part['indices'], dtype='<u4').reshape(-1)
        if indices.max() >= len(xyz):
            raise ValueError('三角形索引越界')
        primitive = {'attributes': attributes, 'indices': self.accessor(indices, 'SCALAR'),
                     'material': len(self.doc['materials']), 'mode': 4}
        self.doc['materials'].append(material)
        self.doc['meshes'][0]['primitives'].append(primitive)
        self.expected.append({'arrays': {name: _array_digest(array) for name, array in arrays.items()},
                              'indices': _array_digest(indices), 'world': _array_digest(restored),
                              'texture': texture, 'material': material,
                              'vertices': len(xyz), 'triangles': len(indices)//3})

    def finish(self, path):
        self.doc['buffers'] = [{'byteLength': self.binary.tell()}]
        self.binary.write(b'\0' * (-self.binary.tell() % 4))
        size = self.binary.tell()
        document = json.dumps(self.doc, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode('utf-8')
        document += b' ' * (-len(document) % 4)
        total = 28 + len(document) + size
        if total > 0xffffffff:
            raise ValueError('单个 GLB 瓦片超过 4 GiB，请先增加源模型分块')
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix('.glb.tmp')
        self.binary.seek(0)
        with temporary.open('wb') as output:
            output.write(struct.pack('<4sII', b'glTF', 2, total))
            output.write(struct.pack('<II', len(document), 0x4e4f534a)); output.write(document)
            output.write(struct.pack('<II', size, 0x004e4942))
            while chunk := self.binary.read(1024 * 1024):
                self.control.check(); output.write(chunk)
        temporary.replace(path)

    def verify(self, path, origin):
        transform = np.eye(4); transform[:3, 3] = origin
        with Glb(path) as model:
            primitives = model.doc['meshes'][0]['primitives']
            if len(primitives) != len(self.expected):
                raise ValueError('GLB 后台校验失败：网格数量不一致')
            for expected, primitive, part in zip(self.expected, primitives, model.primitives(transform), strict=True):
                self.control.check()
                for name, digest in expected['arrays'].items():
                    if _array_digest(model.accessor(primitive['attributes'][name])) != digest:
                        raise ValueError(f'GLB 后台校验失败：{name}')
                if _array_digest(part['indices'].reshape(-1)) != expected['indices'] or _array_digest(part['positions']) != expected['world']:
                    raise ValueError('GLB 后台校验失败：三角形或世界坐标不一致')
                if part['material'] != expected['material']:
                    raise ValueError('GLB 后台校验失败：材质不一致')
                if expected['texture'] is not None:
                    data, _, sampler = model.image(part['texture'])
                    if _digest(data) != expected['texture']['hash'] or sampler != expected['texture']['sampler']:
                        raise ValueError('GLB 后台校验失败：原图或采样参数不一致')


def _export_leaf(node, destination, work, control, clip_box):
    lo, hi = np.full(3, np.inf), np.full(3, -np.inf)
    # Bounds pass avoids retaining all primitive arrays to find a local origin.
    with reader(node.source) as model:
        for part in _parts(model, node, clip_box, control):
            lo = np.minimum(lo, part['positions'].min(axis=0))
            hi = np.maximum(hi, part['positions'].max(axis=0))
    if not np.isfinite(lo).all():
        return None
    origin = lo + (hi - lo) / 2
    writer = _GlbWriter(work, control)
    try:
        with reader(node.source) as model:
            for part in _parts(model, node, clip_box, control):
                writer.add(model, part, origin)
        writer.finish(destination)
        writer.verify(destination, origin)
        transform = np.eye(4); transform[:3, 3] = origin
        tile = {'boundingVolume': _box(writer.lo-origin, writer.hi-origin), 'geometricError': 0,
                'transform': transform.T.reshape(-1).tolist()}
        counts = {'primitives': len(writer.expected),
                  'vertices': sum(p['vertices'] for p in writer.expected),
                  'triangles': sum(p['triangles'] for p in writer.expected),
                  'textures': len(writer.textures), 'max_position_error': writer.max_error}
        return tile, writer.lo, writer.hi, counts
    finally:
        writer.close()


def _hierarchy(leaves):
    """Empty grouping tiles provide directory-level culling, with no coarse mesh."""
    groups = {'children': {}, 'leaves': []}
    for relative, tile, lo, hi in leaves:
        group = groups
        for folder in relative.parent.parts:
            group = group['children'].setdefault(folder, {'children': {}, 'leaves': []})
        group['leaves'].append((tile, lo, hi))

    def build(group):
        entries = group['leaves'] + [build(child) for child in group['children'].values()]
        lo = np.min([entry[1] for entry in entries], axis=0)
        hi = np.max([entry[2] for entry in entries], axis=0)
        return {'boundingVolume': _box(lo, hi), 'geometricError': float(max(np.linalg.norm(hi-lo), 1.)),
                'refine': 'ADD', 'children': [entry[0] for entry in entries]}, lo, hi
    return build(groups)


def _verify_hierarchy(path, leaves, control):
    """Check serialized group/leaf bounds and translations against written geometry."""
    expected = {(path.parent / relative).resolve(): (tile, lo, hi) for relative, tile, lo, hi in leaves}
    document = json.loads(path.read_text(encoding='utf-8'))
    checked = 0

    def visit(tile, parent):
        nonlocal checked
        control.check()
        matrix = parent @ np.asarray(tile.get('transform', np.eye(4).T.reshape(-1)), dtype=float).reshape(4, 4).T
        # Exported content uses only translation; all rotations are baked into GLB.
        if not np.isfinite(matrix).all() or not np.array_equal(matrix[:3, :3], np.eye(3)):
            raise ValueError('3D Tiles 后台校验失败：瓦片坐标变换不一致')
        bounds = []
        if 'content' in tile:
            source = local_uri(path.parent, tile['content']['uri'])
            wanted, lo, hi = expected[source]
            if not np.array_equal(matrix, np.asarray(wanted['transform']).reshape(4, 4).T):
                raise ValueError('3D Tiles 后台校验失败：瓦片平移不一致')
            bounds.append((lo, hi))
        bounds.extend(visit(child, matrix) for child in tile.get('children', []))
        lo = np.min([bound[0] for bound in bounds], axis=0)
        hi = np.max([bound[1] for bound in bounds], axis=0)
        box = np.asarray(tile['boundingVolume']['box'], dtype=float)
        axes = box[3:].reshape(3, 3)
        if not np.isfinite(box).all() or np.any(np.diag(axes) <= 0) or not np.array_equal(axes, np.diag(np.diag(axes))):
            raise ValueError('3D Tiles 后台校验失败：包围体无效')
        center = box[:3] + matrix[:3, 3]
        half = np.diag(axes)
        tolerance = np.maximum(np.spacing(np.maximum(np.abs(lo), np.abs(hi))) * 8, 1e-9)
        if np.any(lo < center-half-tolerance) or np.any(hi > center+half+tolerance):
            raise ValueError('3D Tiles 后台校验失败：包围体遗漏几何')
        checked += 1
        return lo, hi

    visit(document['root'], np.eye(4))
    return checked


def export_tiles(input_path, output_path, control=None, clip_box=None, prepared=None):
    """Export to output/3dtiles and return a conversion report after readback.

    ``prepared`` is converter's (tree, original_source, input_kind) tuple for a
    native-reader temporary mesh. The caller must keep that temporary mesh alive.
    Output must be empty and independent of the original input directory.
    """
    from converter import Cancelled, Control, input_tree, metadata, write_json
    control = control or Control()
    started = time.time()
    if clip_box is not None:
        clip_box = np.asarray(clip_box, dtype=float)
        if clip_box.shape != (6,) or not np.isfinite(clip_box).all() or np.any(clip_box[:3] >= clip_box[3:]):
            raise ValueError('剪切盒范围无效 / Invalid clipping box')
    tree, source, kind = prepared or input_tree(input_path)
    source = Path(source).resolve()
    output = Path(output_path).resolve()
    input_base = source if source.is_dir() else source.parent
    if output == input_base or output in input_base.parents or output.is_relative_to(input_base):
        raise ValueError('输出目录必须独立于输入目录，避免覆盖或混入原数据')
    if output.exists() and any(output.iterdir()):
        raise ValueError('输出目录不是空目录，请选择新目录')
    nodes = obj_nodes(tree)
    output.mkdir(parents=True, exist_ok=True)
    folder = output / '3dtiles'; folder.mkdir()
    quality = {'state': 'running', 'tiles': 0, 'primitives': 0, 'vertices': 0, 'triangles': 0,
               'textures': 0, 'max_position_error': 0., 'texture_policy': 'Original PNG/JPEG bytes; KTX2 decoded to PNG at source resolution'}
    report = {'source': str(source), 'input_kind': kind, 'formats': '3dtiles', 'state': 'running',
              'nodes': len(list(flatten(tree))), 'selected_contents': len(nodes), 'converted': [],
              'coordinate_policy': 'Z-up tiles, Y-up GLB; float32 local vertices + float64 tile translations; source transforms applied',
              'clip_box': clip_box.tolist() if clip_box is not None else None, 'preview_textures': False,
              'warnings': ['静态最终精度瓦片；保留分块，不生成简化 LOD。'], 'quality': quality}
    completed = 0
    write_json(output / 'conversion_report.json', report)
    write_json(output / 'mesh_progress.json', {'progress': 0, 'state': 'running'})
    try:
        control.log('导出 3D Tiles：保留原图并自动校验 / Exporting and verifying 3D Tiles…')
        leaves = []; used = set()
        with tempfile.TemporaryDirectory(prefix='meshtiles_') as temporary:
            work = Path(temporary)
            for index, node in enumerate(nodes):
                control.check()
                relative = node.output.with_suffix('.glb')
                if relative.is_absolute() or '..' in relative.parts:
                    raise ValueError('输出瓦片路径无效')
                candidate = relative
                suffix = 1
                while relative.as_posix().casefold() in used:
                    relative = candidate.with_stem(candidate.stem + f'_{suffix}'); suffix += 1
                used.add(relative.as_posix().casefold())
                percent = round(90 * index / max(len(nodes), 1), 2)
                control.log(f'[{index+1}/{len(nodes)}] {relative}', percent)
                write_json(output / 'mesh_progress.json', {'progress': percent, 'state': 'running', 'current': relative.as_posix()})
                exported = _export_leaf(node, folder / relative, work, control, clip_box)
                completed += 1
                if exported is None:
                    continue
                tile, lo, hi, counts = exported
                tile['content'] = {'uri': quote(relative.as_posix(), safe='/')}
                leaves.append((relative, tile, lo, hi))
                quality['tiles'] += 1
                for key in ('primitives', 'vertices', 'triangles', 'textures'):
                    quality[key] += counts[key]
                quality['max_position_error'] = max(quality['max_position_error'], counts['max_position_error'])
                report['converted'].append({'output': relative.as_posix(), 'source': str(node.source), **counts})
        if not leaves:
            raise ValueError('剪切盒内没有最终精度网格 / No final-resolution geometry inside clipping box')
        root, lo, hi = _hierarchy(leaves)
        tileset = {'asset': {'version': '1.1', 'tilesetVersion': 'SHARE3DCAM-static-1'},
                   'geometricError': root['geometricError'], 'root': root}
        write_json(folder / 'tileset.json', tileset)
        (folder / 'metadata.xml').write_bytes(metadata(source))
        contract = input_base / 'coordinate_contract.json'
        if contract.is_file():
            shutil.copy2(contract, output / 'coordinate_contract.json')
        control.log('后台检查瓦片引用和包围体 / Checking tile references and bounds…', 95)
        reread = obj_nodes(load_tiles(folder / 'tileset.json'))
        if len(reread) != len(leaves):
            raise ValueError('3D Tiles 后台校验失败：瓦片引用数量不一致')
        expected_paths = {(folder / relative).resolve() for relative, *_ in leaves}
        if {tile.source for tile in reread} != expected_paths:
            raise ValueError('3D Tiles 后台校验失败：瓦片路径不一致')
        quality['bounding_volumes_verified'] = _verify_hierarchy(folder / 'tileset.json', leaves, control)
        control.check()
        quality.update(state='passed', references_verified=len(reread))
        report.update(state='succeeded', seconds=round(time.time()-started, 2), bounds=[lo.tolist(), hi.tolist()])
        data = {'progress': 100, 'tileset_path': '3dtiles', 'tileset_root': '3dtiles/tileset.json',
                'tileset_model_list': ['3dtiles/' + relative.as_posix() for relative, *_ in leaves]}
        write_json(output / 'quality_report.json', quality)
        write_json(output / 'conversion_report.json', report)
        write_json(output / 'mesh_result.json', {'code': 0, 'data': data, 'engine_code': 0, 'error_reason': '',
                                                'message': '', 'state': 'succeeded', 'taskState': 2})
        write_json(output / 'mesh_progress.json', {'progress': 100, 'state': 'succeeded'})
        control.log(f'转换完成：{output}', 100)
        return report
    except Exception as error:
        state = 'cancelled' if isinstance(error, Cancelled) else 'failed'
        quality.update(state=state, error=str(error))
        report.update(state=state, error=str(error), seconds=round(time.time()-started, 2))
        write_json(output / 'quality_report.json', quality)
        write_json(output / 'conversion_report.json', report)
        write_json(output / 'mesh_result.json', {'code': 1, 'state': state, 'error_reason': str(error), 'data': {}})
        write_json(output / 'mesh_progress.json', {'progress': round(90*completed/max(len(nodes), 1), 2), 'state': state})
        raise
