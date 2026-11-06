"""Streaming point sources and byte-preserving source-format exports.

The .spoints v1 render manifest uses little-endian float32 records. Points have
7 floats (local xyz, rgba); Gaussians have 62 (xyz, rgba, activated scale xyz,
unit quaternion wxyz, 16 RGB SH coefficient triplets). Origin and world bounds
remain double precision. This render cache is never used as an export source.

Gaussian crop semantics are center inclusion, with inclusive box boundaries.
Selected original records, including every extra property, are copied intact;
the ellipsoid is not cut, re-fit, or re-trained at the box boundary.
"""
import copy
import hashlib
import json
import math
import re
import struct
import tempfile
from pathlib import Path

import numpy as np
from spatial_frame import ClipBox, footprint_hull


PREVIEW_LIMIT = 300_000
CHUNK_SIZE = 131_072
_SH_C0 = 0.28209479177387814
_TYPES = {'char': 'i1', 'int8': 'i1', 'uchar': 'u1', 'uint8': 'u1',
          'short': 'i2', 'int16': 'i2', 'ushort': 'u2', 'uint16': 'u2',
          'int': 'i4', 'int32': 'i4', 'uint': 'u4', 'uint32': 'u4',
          'float': 'f4', 'float32': 'f4', 'double': 'f8', 'float64': 'f8'}
_GAUSSIAN_FIELDS = {'f_dc_0', 'f_dc_1', 'f_dc_2', 'opacity',
                    'scale_0', 'scale_1', 'scale_2', 'rot_0', 'rot_1', 'rot_2', 'rot_3'}


class PointQualityError(RuntimeError):
    pass


def _control(control):
    if control is None:
        from converter import Control
        return Control()
    return control


def _write_json(path, value):
    # Import lazily: converter also dispatches to this module.
    from converter import write_json
    write_json(path, value)


def _ply_header(path):
    lines, elements, current = [], [], None
    fmt = None
    with Path(path).open('rb') as stream:
        if stream.readline() != b'ply\n':
            stream.seek(0)
            if stream.readline().rstrip(b'\r\n') != b'ply':
                raise ValueError('不是有效的 PLY 文件 / Invalid PLY signature')
        stream.seek(0)
        while True:
            raw = stream.readline(65537)
            if not raw or len(raw) > 65536 or sum(map(len, lines)) + len(raw) > 1024 * 1024:
                raise ValueError('PLY 头缺失或过长 / Invalid PLY header')
            lines.append(raw)
            tokens = raw.decode('utf-8', errors='replace').strip().split()
            if not tokens:
                continue
            if tokens[0] == 'format':
                if len(tokens) != 3 or tokens[2] != '1.0' or fmt is not None:
                    raise ValueError('不支持的 PLY 格式 / Unsupported PLY format')
                fmt = tokens[1]
            elif tokens[0] == 'element':
                if len(tokens) != 3 or not tokens[2].isdigit():
                    raise ValueError('PLY 元素数量无效 / Invalid PLY element count')
                current = {'name': tokens[1], 'count': int(tokens[2]), 'properties': [], 'line': len(lines)-1}
                elements.append(current)
            elif tokens[0] == 'property':
                if current is None:
                    raise ValueError('PLY property 缺少 element / Missing PLY element')
                current['properties'].append(tokens[1:])
            elif tokens[0] == 'end_header':
                break
    if fmt not in ('ascii', 'binary_little_endian', 'binary_big_endian'):
        raise ValueError('不支持的 PLY 编码 / Unsupported PLY encoding')
    return {'lines': lines, 'elements': elements, 'format': fmt, 'offset': sum(map(len, lines))}


def is_point_source(path):
    """True for LAS/LAZ or face-free point/Gaussian PLY; mesh PLY stays a mesh."""
    path = Path(path)
    if not path.is_file():
        return False
    if path.suffix.lower() in ('.las', '.laz'):
        with path.open('rb') as stream:
            return stream.read(4) == b'LASF'
    if path.suffix.lower() != '.ply':
        return False
    try:
        elements = _ply_header(path)['elements']
        return any(e['name'] == 'vertex' for e in elements) and not any(
            e['name'] == 'face' and e['count'] for e in elements)
    except (ValueError, OSError):
        return False


class _PlySource:
    def __init__(self, path):
        self.path = Path(path)
        self.header = _ply_header(path)
        elements = self.header['elements']
        vertices = [e for e in elements if e['name'] == 'vertex']
        if len(vertices) != 1 or any(e['name'] != 'vertex' and e['count'] for e in elements):
            raise ValueError('此 PLY 含面或其他元素，请按网格读取 / PLY contains non-point elements')
        self.vertex = vertices[0]
        self.count = self.vertex['count']
        fields = []
        for prop in self.vertex['properties']:
            if len(prop) != 2 or prop[0] not in _TYPES:
                raise ValueError('点 PLY 只支持标量字段 / Point PLY requires scalar properties')
            fields.append((prop[1], ('>' if self.header['format'] == 'binary_big_endian' else '<') + _TYPES[prop[0]]))
        if len({name for name, _ in fields}) != len(fields):
            raise ValueError('PLY 字段重名 / Duplicate PLY property')
        self.dtype = np.dtype(fields)
        self.names = set(self.dtype.names or ())
        if not {'x', 'y', 'z'} <= self.names:
            raise ValueError('点 PLY 缺少 XYZ / PLY is missing XYZ')
        self.kind = 'gaussian' if _GAUSSIAN_FIELDS <= self.names else 'points'
        if self.names & {'f_dc_0', 'opacity', 'scale_0', 'rot_0'} and self.kind != 'gaussian':
            raise ValueError('高斯 PLY 字段不完整 / Incomplete Gaussian PLY properties')
        self.rest = sorted((n for n in self.names if n.startswith('f_rest_')), key=lambda n: int(n[7:]) if n[7:].isdigit() else -1)
        if self.kind == 'gaussian' and (self.rest != [f'f_rest_{i}' for i in range(len(self.rest))] or len(self.rest) not in (0, 9, 24, 45)):
            raise ValueError('仅支持标准 Inria SH0–SH3 / Unsupported Gaussian SH layout')
        self.sh_degree = int(math.sqrt(1 + len(self.rest)//3) - 1) if self.kind == 'gaussian' else 0
        if self.header['format'] != 'ascii':
            expected = self.header['offset'] + self.count * self.dtype.itemsize
            if self.path.stat().st_size != expected:
                raise ValueError('PLY 数据长度与头部不符 / PLY record length mismatch')

    def chunks(self, control):
        if self.header['format'] != 'ascii':
            if not self.count:
                return
            mapped = np.memmap(self.path, dtype=self.dtype, mode='r', offset=self.header['offset'], shape=(self.count,))
            try:
                for start in range(0, self.count, CHUNK_SIZE):
                    control.check()
                    yield start, mapped[start:start+CHUNK_SIZE], None
            finally:
                mapped._mmap.close()
        else:
            with self.path.open('rb') as stream:
                stream.seek(self.header['offset'])
                for start in range(0, self.count, min(CHUNK_SIZE, 32768)):
                    control.check()
                    lines = [stream.readline() for _ in range(min(32768, self.count-start))]
                    tokens = [line.split() for line in lines]
                    if any(len(row) != len(self.dtype.names) for row in tokens):
                        raise ValueError('ASCII PLY 点字段数量错误 / Invalid ASCII PLY record')
                    try:
                        records = np.array([tuple(row) for row in tokens], dtype=self.dtype)
                    except (ValueError, OverflowError) as exc:
                        raise ValueError('ASCII PLY 字段数值无效 / Invalid ASCII PLY value') from exc
                    yield start, records, lines
                if stream.read().strip():
                    raise ValueError('ASCII PLY 有未声明的数据 / Unexpected PLY trailing data')

    def xyz(self, records):
        return np.column_stack([records[name] for name in ('x', 'y', 'z')]).astype(np.float64)


class _LasSource:
    def __init__(self, path):
        import laspy
        self.path = Path(path)
        with laspy.open(self.path) as source:
            self.header = copy.deepcopy(source.header)
        self.count = self.header.point_count
        self.names = set(self.header.point_format.dimension_names)
        self.kind, self.sh_degree = 'points', 0

    def chunks(self, control):
        import laspy
        with laspy.open(self.path) as source:
            start = 0
            for points in source.chunk_iterator(CHUNK_SIZE):
                control.check()
                yield start, points, None
                start += len(points)
            if start != self.count:
                raise ValueError('LAS 点数量与头部不符 / LAS record count mismatch')

    def xyz(self, records):
        return np.column_stack([np.asarray(records[name]) for name in ('x', 'y', 'z')])


def _source(path):
    path = Path(path)
    if path.suffix.lower() in ('.las', '.laz'):
        return _LasSource(path)
    if path.suffix.lower() == '.ply':
        return _PlySource(path)
    raise ValueError('请选择 LAS、LAZ 或点 PLY / Select LAS, LAZ or point PLY')


def point_info(path):
    """Inspect point headers only; never scan the point payload."""
    source = Path(path).resolve()
    reader = _source(source)
    info = {'source': str(source), 'kind': reader.kind, 'count': reader.count,
            'source_count': reader.count, 'sh_degree': reader.sh_degree,
            'format': source.suffix.lower()[1:], 'fields': sorted(reader.names),
            'bounds': None, 'file_size_bytes': source.stat().st_size}
    if isinstance(reader, _LasSource):
        info.update(bounds=[reader.header.mins.tolist(), reader.header.maxs.tolist()],
                    scales=reader.header.scales.tolist(), offsets=reader.header.offsets.tolist(),
                    point_format=reader.header.point_format.id, version=str(reader.header.version),
                    record_bytes=reader.header.point_format.size)
    else:
        info.update(encoding=reader.header['format'], record_bytes=reader.dtype.itemsize,
                    crop_semantics='center_inside_inclusive_box')
    return info


def _bounds_update(bounds, xyz):
    if not np.isfinite(xyz).all():
        raise ValueError('点坐标含无效数值 / Non-finite point coordinates')
    if len(xyz):
        bounds[0] = np.minimum(bounds[0], xyz.min(axis=0))
        bounds[1] = np.maximum(bounds[1], xyz.max(axis=0))


def _empty_bounds():
    return np.array([[np.inf]*3, [-np.inf]*3], dtype=np.float64)


def _rgb(reader, records):
    names = reader.names
    channels = ('red', 'green', 'blue')
    if set(channels) <= names:
        rgb = np.column_stack([np.asarray(records[n]) for n in channels]).astype(np.float64)
        if isinstance(reader, _LasSource):
            divisor = 65535
        else:
            kind = records.dtype['red'].kind
            divisor = np.iinfo(records.dtype['red']).max if kind in 'ui' else 1
        return np.clip(rgb/divisor, 0, 1)
    if 'intensity' in names:
        gray = np.asarray(records['intensity'], dtype=np.float64)/65535
        return np.repeat(np.clip(gray, 0, 1)[:, None], 3, axis=1)
    return np.full((len(records), 3), .75)


def _pack(reader, records, xyz, origin):
    gaussian = reader.kind == 'gaussian'
    packed = np.zeros((len(records), 62 if gaussian else 7), dtype='<f4')
    packed[:, :3] = xyz-origin
    if gaussian:
        dc = np.column_stack([records[f'f_dc_{i}'] for i in range(3)])
        opacity = np.asarray(records['opacity'], dtype=np.float64)
        scales = np.column_stack([records[f'scale_{i}'] for i in range(3)]).astype(np.float64)
        rotation = np.column_stack([records[f'rot_{i}'] for i in range(4)]).astype(np.float64)
        if not all(np.isfinite(a).all() for a in (dc, opacity, scales, rotation)):
            raise ValueError('高斯属性含无效数值 / Non-finite Gaussian properties')
        norms = np.linalg.norm(rotation, axis=1)
        if np.any(norms == 0) or np.any(scales > 80) or np.any(scales < -100):
            raise ValueError('高斯缩放或旋转无效 / Invalid Gaussian scale or rotation')
        packed[:, 3:6] = np.maximum(.5 + _SH_C0*dc, 0)
        packed[:, 6] = np.exp(-np.logaddexp(0, -opacity))
        packed[:, 7:10] = np.exp(scales)
        packed[:, 10:14] = rotation/norms[:, None]
        packed[:, 14:17] = dc
        if reader.rest:
            rest = np.column_stack([records[n] for n in reader.rest])
            count = len(reader.rest)//3
            packed[:, 17:17+len(reader.rest)] = rest.reshape(-1, 3, count).transpose(0, 2, 1).reshape(-1, len(reader.rest))
    else:
        packed[:, 3:6] = _rgb(reader, records)
        packed[:, 6] = 1
        if 'alpha' in reader.names and isinstance(reader, _PlySource):
            dtype = records.dtype['alpha']
            divisor = np.iinfo(dtype).max if dtype.kind in 'ui' else 1
            packed[:, 6] = np.clip(records['alpha']/divisor, 0, 1)
    if not np.isfinite(packed).all():
        raise ValueError('渲染属性超出有效范围 / Invalid render attributes')
    return packed


def prepare_points(source, folder, control=None, preview=False):
    """Prepare a native render cache; preview only samples at most 300,000 points."""
    control = _control(control)
    control.check()
    source, folder = Path(source).resolve(), Path(folder)
    before = source.stat()
    reader = _source(source)
    if not reader.count:
        raise ValueError('点数据为空 / Empty point source')
    folder.mkdir(parents=True, exist_ok=True)
    manifest, data = folder/'model.spoints', folder/'points.bin'
    if manifest.exists() or data.exists():
        raise FileExistsError(f'输出已存在 / Output exists: {folder}')
    # LAS headers supply a precise stable origin; PLY is streamed once for bounds.
    bounds = _empty_bounds()
    if isinstance(reader, _LasSource):
        origin = (np.asarray(reader.header.mins) + np.asarray(reader.header.maxs))/2
    else:
        for start, records, _ in reader.chunks(control):
            _bounds_update(bounds, reader.xyz(records))
            control.log('读取点云范围 / Reading point bounds', 15*(start+len(records))/reader.count)
        origin = (bounds[0] + bounds[1])/2
    stride = max(1, math.ceil(reader.count/PREVIEW_LIMIT)) if preview else 1
    rendered = 0
    footprint = np.empty((0, 2))
    partial = folder/'points.bin.partial'
    try:
        with partial.open('xb') as output:
            for start, records, _ in reader.chunks(control):
                xyz = reader.xyz(records)
                _bounds_update(bounds, xyz)
                footprint = footprint_hull(np.vstack([footprint, footprint_hull(xyz[:, :2])]))
                selection = slice((-start) % stride, None, stride)
                packed = _pack(reader, records[selection], xyz[selection], origin)
                output.write(packed.tobytes())
                rendered += len(packed)
                control.log('准备点云显示 / Preparing points', 15 + 80*(start+len(records))/reader.count)
        after = source.stat()
        if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
            raise PointQualityError('读取期间源文件发生变化 / Source changed while reading')
        control.check()
        partial.replace(data)
        doc = {'format': 'share3dcam-points', 'version': 1, 'kind': reader.kind,
               'source': str(source), 'data': data.name, 'count': rendered, 'render_count': rendered,
               'source_count': reader.count, 'origin': origin.tolist(), 'bounds': bounds.tolist(),
               'footprint': footprint.tolist(),
               'stride_floats': 62 if reader.kind == 'gaussian' else 7, 'sh_degree': reader.sh_degree,
               'preview': bool(preview), 'sampled': stride > 1, 'sample_stride': stride,
               'position_encoding': 'float32_relative_to_double_origin',
               'crop_semantics': 'center_inside_inclusive_box', 'source_size': before.st_size,
               'source_mtime_ns': before.st_mtime_ns}
        _write_json(manifest, doc)
        control.log('点云已准备 / Points ready', 100)
        return manifest
    except BaseException:
        partial.unlink(missing_ok=True)
        data.unlink(missing_ok=True)
        manifest.unlink(missing_ok=True)
        raise


def _hash_file(path, control):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        while block := stream.read(8*1024*1024):
            control.check()
            digest.update(block)
    return digest.hexdigest()


def _vlrs(vlrs):
    return [(v.user_id, v.record_id, v.description, v.record_data_bytes()) for v in vlrs or []]


def _las_metadata(header):
    return {'version': str(header.version), 'format': header.point_format.id,
            'dtype': header.point_format.dtype().descr, 'scales': header.scales.tolist(),
            'offsets': header.offsets.tolist(), 'vlrs': _vlrs(header.vlrs),
            'evlrs': _vlrs(header.evlrs), 'uuid': str(header.uuid),
            'file_source_id': header.file_source_id, 'global_encoding': header.global_encoding.value,
            'system_identifier': header.system_identifier, 'generating_software': header.generating_software,
            'creation_date': str(header.creation_date), 'extra_header_bytes': header.extra_header_bytes,
            'extra_vlr_bytes': header.extra_vlr_bytes}


def _mask(xyz, box):
    return ClipBox(box).contains(xyz)


def _crop_ply(reader, output, box, control):
    payload = output.with_suffix('.records')
    digest, count = hashlib.sha256(), 0
    bounds = _empty_bounds()
    with payload.open('xb') as stream:
        for start, records, lines in reader.chunks(control):
            xyz = reader.xyz(records)
            if not np.isfinite(xyz).all():
                raise ValueError('点坐标含无效数值 / Non-finite point coordinates')
            selected = _mask(xyz, box)
            raw = records[selected].tobytes() if lines is None else b''.join(line for line, keep in zip(lines, selected) if keep)
            stream.write(raw)
            digest.update(raw)
            count += int(selected.sum())
            _bounds_update(bounds, xyz[selected])
            control.log('裁剪原始点记录 / Clipping source records', 70*(start+len(records))/reader.count)
    if not count:
        raise ValueError('剪切盒内没有点 / No point centers inside clipping box')
    lines = list(reader.header['lines'])
    index = reader.vertex['line']
    lines[index] = re.sub(rb'(element\s+vertex\s+)\d+', lambda m: m[1]+str(count).encode(), lines[index])
    with output.open('xb') as stream, payload.open('rb') as body:
        stream.write(b''.join(lines))
        while block := body.read(8*1024*1024):
            control.check()
            stream.write(block)
    payload.unlink()
    return count, bounds, digest.hexdigest()


def _crop_las(reader, output, box, control):
    import laspy
    if reader.header.point_format.id in (4, 5, 9, 10):
        raise ValueError('波形 LAS 仅支持完整原格式导出 / Waveform LAS requires full source export')
    digest, count = hashlib.sha256(), 0
    bounds = _empty_bounds()
    with laspy.open(output, mode='w', header=copy.deepcopy(reader.header), do_compress=output.suffix.lower() == '.laz') as writer:
        for start, records, _ in reader.chunks(control):
            xyz = reader.xyz(records)
            if not np.isfinite(xyz).all():
                raise ValueError('点坐标含无效数值 / Non-finite point coordinates')
            selected = _mask(xyz, box)
            kept = records[selected]
            writer.write_points(kept)
            digest.update(kept.array.tobytes())
            count += len(kept)
            _bounds_update(bounds, xyz[selected])
            control.log('裁剪原始点记录 / Clipping source records', 70*(start+len(records))/reader.count)
        if reader.header.evlrs:
            writer.write_evlrs(copy.deepcopy(reader.header.evlrs))
    if not count:
        raise ValueError('剪切盒内没有点 / No point centers inside clipping box')
    _restore_las_metadata_bytes(reader.path, output, control)
    return count, bounds, digest.hexdigest()


def _las_vlr_regions(path):
    """Offsets permit streaming even large EVLR payloads without allocating them."""
    regions = []
    with Path(path).open('rb') as stream:
        fixed = stream.read(375)
        if len(fixed) < 227 or fixed[:4] != b'LASF':
            raise ValueError('LAS 头损坏 / Invalid LAS header')
        size, offset, count = struct.unpack_from('<HII', fixed, 94)
        filesize = Path(path).stat().st_size
        groups = [(size, count, False, offset)]
        if fixed[24] == 1 and fixed[25] >= 4:
            if len(fixed) < 375:
                raise ValueError('LAS 1.4 头损坏 / Invalid LAS 1.4 header')
            evlr_offset, evlr_count = struct.unpack_from('<QI', fixed, 235)
            groups.append((evlr_offset, evlr_count, True, filesize))
        for beginning, number, extended, limit in groups:
            stream.seek(beginning)
            header_size = 60 if extended else 54
            for _ in range(number):
                start = stream.tell()
                header = stream.read(header_size)
                if len(header) != header_size:
                    raise ValueError('LAS VLR 截断 / Truncated LAS VLR')
                # IDs end at the first NUL. Some source writers leave nonzero
                # padding after it; retain those raw bytes when restoring VLRs.
                user = header[2:18].split(b'\0', 1)[0]
                record_id = struct.unpack_from('<H', header, 18)[0]
                length = struct.unpack_from('<Q' if extended else '<H', header, 20)[0]
                if start + header_size + length > limit:
                    raise ValueError('LAS VLR 长度无效 / Invalid LAS VLR length')
                if user != b'laszip encoded':
                    regions.append(((extended, user, record_id), start, header_size+length))
                stream.seek(length, 1)
    return regions


def _restore_las_metadata_bytes(source, output, control):
    # laspy resets optional Extra Bytes min/max even when those fields are
    # inactive. Restore all original VLR/EVLR bytes, including CRS and reserved
    # bytes; LAZ compressor metadata belongs to the newly encoded stream.
    original, written = _las_vlr_regions(source), _las_vlr_regions(output)
    if [(key, length) for key, _, length in original] != [(key, length) for key, _, length in written]:
        raise PointQualityError('LAS VLR 布局发生变化 / LAS VLR layout changed')
    with Path(source).open('rb') as incoming, Path(output).open('r+b') as outgoing:
        for (_, source_offset, length), (_, target_offset, _) in zip(original, written):
            incoming.seek(source_offset)
            outgoing.seek(target_offset)
            while length:
                control.check()
                block = incoming.read(min(length, 1024*1024))
                if not block:
                    raise PointQualityError('LAS VLR 读取不完整 / Incomplete VLR read')
                outgoing.write(block)
                length -= len(block)


def _verify_crop(reader, output, count, bounds, digest, control):
    actual = _source(output)
    if actual.count != count:
        raise PointQualityError('输出点数量核对失败 / Output count mismatch')
    if isinstance(reader, _LasSource):
        if _las_metadata(reader.header) != _las_metadata(actual.header):
            raise PointQualityError('LAS 属性或元数据核对失败 / LAS metadata mismatch')
    else:
        expected = list(reader.header['lines'])
        index = reader.vertex['line']
        expected[index] = re.sub(rb'(element\s+vertex\s+)\d+', lambda m: m[1]+str(count).encode(), expected[index])
        if expected != actual.header['lines']:
            raise PointQualityError('PLY 字段或头部核对失败 / PLY header mismatch')
    observed, observed_bounds, observed_count = hashlib.sha256(), _empty_bounds(), 0
    for start, records, lines in actual.chunks(control):
        raw = records.array.tobytes() if isinstance(actual, _LasSource) else records.tobytes() if lines is None else b''.join(lines)
        observed.update(raw)
        _bounds_update(observed_bounds, actual.xyz(records))
        observed_count += len(records)
        control.log('后台核对全部点字段 / Verifying every point field', 70+25*(start+len(records))/count)
    if observed.hexdigest() != digest or observed_count != count or not np.array_equal(observed_bounds, bounds):
        raise PointQualityError('原始点记录核对失败 / Source record verification failed')


def crop_points(source, outputfolder, clip_box, control=None):
    """Export the original format, preserving every selected record byte.

    clip_box is a world-axis list or a ClipBox working-frame descriptor.
    None copies the complete original file without any re-encoding. Outputs
    become visible only after background verification; a failed check retries
    once from the original source and can never publish a success report.
    """
    control = _control(control)
    control.check()
    source, outputfolder = Path(source).resolve(), Path(outputfolder).resolve()
    before = source.stat()
    reader = _source(source)
    if not reader.count:
        raise ValueError('点数据为空 / Empty point source')
    box = None if clip_box is None else ClipBox(clip_box)
    outputfolder.mkdir(parents=True, exist_ok=True)
    output = outputfolder/source.name
    if output.exists() or (outputfolder/'point_result.json').exists():
        raise FileExistsError(f'输出已存在 / Output exists: {output}')
    repairs = 0
    try:
        with tempfile.TemporaryDirectory(prefix='.point-export-', dir=outputfolder) as work:
            temporary = Path(work)/source.name
            for attempt in range(2):
                control.check()
                try:
                    if box is None:
                        with source.open('rb') as original, temporary.open('xb') as target:
                            while block := original.read(8*1024*1024):
                                control.check()
                                target.write(block)
                        digest = _hash_file(source, control)
                        control.log('后台核对原始文件 / Verifying complete source', 80)
                        if _hash_file(temporary, control) != digest:
                            raise PointQualityError('完整文件核对失败 / Full file verification failed')
                        count, bounds = reader.count, None
                    else:
                        count, bounds, digest = (_crop_las if isinstance(reader, _LasSource) else _crop_ply)(reader, temporary, box, control)
                        _verify_crop(reader, temporary, count, bounds, digest, control)
                    break
                except PointQualityError:
                    if attempt:
                        raise
                    repairs += 1
                    temporary.unlink(missing_ok=True)
                    control.log('自动重新生成输出 / Regenerating output', 0)
            after = source.stat()
            if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                raise PointQualityError('导出期间源文件发生变化 / Source changed during export')
            control.check()
            temporary.replace(output)
        report = {'state': 'succeeded', 'source': str(source), 'output': str(output),
                  'format': source.suffix.lower()[1:], 'kind': reader.kind, 'count': count,
                  'source_count': reader.count, 'clip_box': box.tolist() if box is not None else None,
                  'bounds': bounds.tolist() if bounds is not None else None,
                  'crop_semantics': 'center_inside_inclusive_box' if box is not None else 'complete_source_file',
                  'quality': {'state': 'passed', 'repairs': repairs, 'source_unchanged': True,
                              'all_fields_preserved': True, 'records_sha256' if box is not None else 'file_sha256': digest},
                  'file_size_bytes': output.stat().st_size}
        _write_json(outputfolder/'point_result.json', report)
        control.log('原格式导出完成 / Source-format export complete', 100)
        return report
    except BaseException as exc:
        if not output.exists():
            _write_json(outputfolder/'point_result.json', {'state': 'failed', 'error': str(exc), 'source': str(source)})
        raise
