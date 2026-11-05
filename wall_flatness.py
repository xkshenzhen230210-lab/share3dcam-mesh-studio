"""Full-resolution, bounded-memory LAS distances to a least-squares plane.

This is plane deviation, not minimum-zone flatness or a 2 m straightedge test.
No records are filtered other than the user's inclusive selection box.
"""
import csv
from datetime import datetime
from html import escape
import math
from pathlib import Path

import numpy as np

from converter import Control, write_json
from point_data import _LasSource, _mask, PREVIEW_LIMIT

UNIT_MM = {'m': 1000., 'cm': 10., 'mm': 1.}


def deviation_colors(deviation_mm, tolerance_mm):
    """Blue = negative, green = zero, red = positive; saturate at tolerance."""
    t = np.clip(np.asarray(deviation_mm)/tolerance_mm, -1, 1)
    zero = np.array([.12, .82, .35])
    ends = np.where((t < 0)[:, None], [.12, .35, 1.], [1., .18, .12])
    return zero + np.abs(t)[:, None]*(ends-zero)


def wall_camera(report, aspect=1.):
    center = np.asarray(report['centroid'])
    normal = np.asarray(report['normal'])
    bounds = np.asarray(report['bounds'])
    up = np.array([0., 0., 1.])
    if abs(normal @ up) > .95:
        up = np.array([0., 1., 0.])
    up -= normal*(up @ normal)
    up /= np.linalg.norm(up)
    right = np.cross(up,normal)
    corners = np.array([[bounds[i,0],bounds[j,1],bounds[k,2]]
                        for i in range(2) for j in range(2) for k in range(2)])-center
    tangent = math.tan(math.radians(35/2))
    distance = max(np.max(np.abs(corners@up))/tangent,
                   np.max(np.abs(corners@right))/(tangent*max(.1,float(aspect))))*1.15
    distance += float(np.max(np.abs(corners@normal)))
    distance = max(distance, .1)
    return {'eye': (center+normal*distance).tolist(), 'center': center.tolist(),
            'up': up.tolist(), 'fovy': 35.}


def _reports(folder, report):
    rows = [
        ('源文件 / Source', report['source']),
        ('方法 / Method', '最小二乘拟合平面 / Least-squares plane; all selected points'),
        ('源坐标单位 / Source unit', report['unit']),
        ('选区点数 / Selected points', report['count']),
        ('显示点数 / Display points', report['preview_count']),
        ('容差 ± / Tolerance ± (mm)', report['tolerance_mm']),
        ('最大绝对偏差 / Max absolute (mm)', report['max_abs_mm']),
        ('均方根 / RMS (mm)', report['rms_mm']),
        ('平均绝对偏差 / Mean absolute (mm)', report['mean_abs_mm']),
        ('最小有符号偏差 / Minimum signed (mm)', report['min_mm']),
        ('最大有符号偏差 / Maximum signed (mm)', report['max_mm']),
        ('峰谷差 / Peak-to-valley (mm)', report['range_mm']),
        ('超差点数 / Outside tolerance', report['outside_count']),
        ('超差比例 / Outside tolerance (%)', report['outside_percent']),
        ('坐标量化步长 / Coordinate steps (mm)', report['coordinate_steps_mm']),
        ('选区范围 / Selection box', report['clip_box']),
        ('参考平面中心 / Plane centroid', report['centroid']),
        ('参考法向 / Plane normal', report['normal']),
        ('生成时间 / Generated', report['created_at']),
    ]
    with (folder/'summary.csv').open('w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.writer(stream)
        writer.writerow(['项目 / Metric', '数值 / Value'])
        writer.writerows(rows)
    cells = ''.join(f'<tr><th>{escape(label)}</th><td>{escape(str(value))}</td></tr>' for label, value in rows)
    warnings = ''.join(f'<p>{escape(text)}</p>' for text in report['notes'])
    (folder/'report.html').write_text(
        '<!doctype html><meta charset="utf-8"><title>SHARE3DCAM 墙面分析</title>'
        '<style>body{font:16px "Segoe UI",sans-serif;max-width:1000px;margin:40px auto;color:#17263c}'
        'h1{color:#101d30}table{border-collapse:collapse;width:100%}th,td{border-bottom:1px solid #ddd;'
        'padding:12px;text-align:left;overflow-wrap:anywhere}th{width:45%}.legend{height:24px;'
        'background:linear-gradient(90deg,#1f59ff,#1fd159,#ff2e1f)}</style>'
        '<h1>SHARE3DCAM 墙面平面偏差 / Wall plane deviation</h1>'
        '<p>SHARE3DCAM 电商销售中心 / E-commerce Sales Center</p>'
        f'<div class="legend"></div><p>蓝 / Blue ≤ −{report["tolerance_mm"]:g} mm · '
        f'绿 / Green = 0 · 红 / Red ≥ +{report["tolerance_mm"]:g} mm</p>'
        + warnings + '<table>' + cells + '</table>', encoding='utf-8')


def analyze_wall(source, output, box, unit='m', tolerance_mm=5., control=None):
    control = control or Control()
    control.check()
    source, output = Path(source).resolve(), Path(output).resolve()
    tolerance_mm = float(tolerance_mm)
    box = np.asarray(box, dtype=np.float64)
    if unit not in UNIT_MM or not math.isfinite(tolerance_mm) or tolerance_mm <= 0:
        raise ValueError('请选择坐标单位并输入正数容差 / Select units and a positive tolerance')
    if box.shape != (6,) or not np.isfinite(box).all() or np.any(box[:3] >= box[3:]):
        raise ValueError('墙面选区范围无效 / Invalid wall selection box')
    if source.suffix.lower() != '.las':
        raise ValueError('墙面分析需要 LAS 点云 / Wall analysis requires a LAS point cloud')
    before = source.stat()
    reader = _LasSource(source)
    if not reader.count:
        raise ValueError('LAS 点云为空 / LAS point cloud is empty')
    if output.exists():
        raise FileExistsError('成果目录已存在，请使用新目录 / Result folder exists; choose a new folder')

    def unchanged():
        stat = source.stat()
        if (stat.st_size, stat.st_mtime_ns) != (before.st_size, before.st_mtime_ns):
            raise ValueError('分析期间源文件发生变化，请重新分析 / Source changed during analysis')

    def selected():
        for start, records, _ in reader.chunks(control):
            xyz = reader.xyz(records)
            if not np.isfinite(xyz).all():
                raise ValueError('LAS 含无效坐标 / Invalid LAS coordinates')
            yield start+len(records), xyz[_mask(xyz, box)]

    count = 0
    mean, moment = np.zeros(3), np.zeros((3, 3))
    anchor = None
    bounds = np.array([[np.inf]*3, [-np.inf]*3])
    for read, xyz in selected():
        if len(xyz):
            if anchor is None:
                anchor = xyz[0].copy()
            local = xyz-anchor
            chunk_mean = local.mean(axis=0)
            centered = local-chunk_mean
            delta = chunk_mean-mean
            total = count+len(xyz)
            moment += centered.T @ centered + np.outer(delta, delta)*(count*len(xyz)/total)
            mean += delta*(len(xyz)/total)
            count = total
            bounds[0] = np.minimum(bounds[0], xyz.min(axis=0))
            bounds[1] = np.maximum(bounds[1], xyz.max(axis=0))
        control.log('拟合墙面 / Fitting wall plane', 45*read/reader.count)
    unchanged()
    if count < 30:
        raise ValueError('选区至少需要 30 个墙面点，请调整剪切盒 / Select at least 30 wall points')
    eigenvalues, vectors = np.linalg.eigh(moment/count)
    if eigenvalues[1] <= max(1e-20, eigenvalues[2]*1e-10):
        raise ValueError('选区接近一条线，无法拟合墙面 / Selection is line-like; select a wall area')
    ratio = max(0., float(eigenvalues[0]))/eigenvalues[1]
    if ratio > .1:
        raise ValueError('选区不接近平面，请只选一面墙，排除地面和家具 / Select one wall; exclude floors and objects')
    normal = vectors[:, 0]
    if normal[np.argmax(np.abs(normal))] < 0:
        normal = -normal
    centroid = anchor+mean
    factor = UNIT_MM[unit]
    stride = max(1, math.ceil(count/PREVIEW_LIMIT))
    output.mkdir(parents=True, exist_ok=False)
    generated = ['points.bin', 'model.spoints', 'summary.csv', 'report.html', 'report.json']
    minimum, maximum, absolute_sum, square_sum = math.inf, -math.inf, 0., 0.
    outside, seen, preview = 0, 0, 0
    try:
        with (output/'points.bin').open('xb') as stream:
            for read, xyz in selected():
                if len(xyz):
                    deviations = ((xyz-anchor-mean) @ normal)*factor
                    absolute = np.abs(deviations)
                    minimum = min(minimum, float(deviations.min()))
                    maximum = max(maximum, float(deviations.max()))
                    absolute_sum += float(absolute.sum())
                    square_sum += float(deviations @ deviations)
                    outside += int(np.count_nonzero(absolute > tolerance_mm))
                    choice = slice((-seen) % stride, None, stride)
                    sample = xyz[choice]
                    packed = np.ones((len(sample), 7), dtype='<f4')
                    packed[:, :3] = sample-centroid
                    packed[:, 3:6] = deviation_colors(deviations[choice], tolerance_mm)
                    if not np.isfinite(packed).all():
                        raise ValueError('选区坐标范围过大 / Selection coordinate range is too large')
                    stream.write(packed.tobytes())
                    seen += len(xyz)
                    preview += len(sample)
                control.log('计算全量点偏差 / Measuring all selected points', 45+50*read/reader.count)
        unchanged()
        if seen != count:
            raise ValueError('Source changed: selected point count differs')
        control.check()
        notes = [
            '相对最佳拟合平面的偏差；不是 2 米靠尺或工程验收结论。 / Best-fit plane deviation; not a 2 m straightedge or acceptance result.',
            '全部选区点参与统计，未剔除离群点。 / All selected points included; no outlier removal.',
            '正负由参考法向决定，不自动表示墙面内外。 / Sign follows the reference normal, not building inside/outside.',
            '坐标单位由用户指定；LAS 缩放步长不等于测量精度。 / User-specified units; coordinate steps are not measurement accuracy.',
        ]
        steps = (np.asarray(reader.header.scales)*factor).tolist()
        if max(steps) > tolerance_mm:
            notes.append('坐标量化步长大于容差，无法可靠分辨该容差。 / Coordinate step exceeds tolerance.')
        if ratio > .01:
            notes.append('选区厚度较大，请检查是否混入其他物体。 / Thick selection; check for other objects.')
        report = dict(state='succeeded', source=str(source), source_size=before.st_size,
                      source_mtime_ns=before.st_mtime_ns, source_count=reader.count,
                      count=count, preview_count=preview, clip_box=box.tolist(), unit=unit,
                      tolerance_mm=tolerance_mm, centroid=centroid.tolist(), normal=normal.tolist(),
                      bounds=bounds.tolist(), min_mm=minimum, max_mm=maximum,
                      max_abs_mm=max(abs(minimum), abs(maximum)), range_mm=maximum-minimum,
                      rms_mm=math.sqrt(square_sum/count), mean_abs_mm=absolute_sum/count,
                      outside_count=outside, outside_percent=100*outside/count,
                      coordinate_steps_mm=steps, planarity_ratio=ratio, notes=notes,
                      method='least_squares_plane_all_selected_points_no_outlier_removal',
                      created_at=datetime.now().astimezone().isoformat(), output=str(output))
        manifest = dict(format='share3dcam-points', version=1, kind='points', stride_floats=7,
                        count=preview, source_count=count, data='points.bin', origin=centroid.tolist(),
                        bounds=bounds.tolist(), sh_degree=0, preview=True, sampled=stride>1,
                        sample_stride=stride, source=str(source), analysis='wall_plane_deviation')
        _reports(output, report)
        control.check()
        unchanged()
        write_json(output/'model.spoints', manifest)
        write_json(output/'report.json', report)
        control.log('墙面分析完成 / Wall analysis complete', 100)
        return report
    except BaseException:
        for name in generated:
            (output/name).unlink(missing_ok=True)
        raise
