"""Whole-scan wall candidates and full-source, shared-plane zone statistics."""
from datetime import datetime
import math
from pathlib import Path
import tempfile
import numpy as np

from converter import Control
from point_data import _LasSource, _rgb
from wall_flatness import UNIT_MM
from wall_segmentation import (detect_walls, assign_points, ASSIGN_BAND, AMBIGUITY,
                               LAYER_STEP, LOCAL_SUPPORT_DEPTH, OVERLAP_CELL, overlapping_surface_cells)

SAMPLE_LIMIT=250_000


class Moments:
    def __init__(self):
        self.count=0;self.mean=np.zeros(3);self.moment=np.zeros((3,3))
        self.bounds=np.array([[np.inf]*3,[-np.inf]*3])

    def add(self,xyz):
        if not len(xyz):return
        mean=xyz.mean(axis=0);centered=xyz-mean;delta=mean-self.mean
        total=self.count+len(xyz)
        self.moment+=centered.T@centered+np.outer(delta,delta)*(self.count*len(xyz)/total)
        self.mean+=delta*(len(xyz)/total);self.count=total
        self.bounds[0]=np.minimum(self.bounds[0],xyz.min(axis=0))
        self.bounds[1]=np.maximum(self.bounds[1],xyz.max(axis=0))


class Statistics:
    def __init__(self):
        self.count=0;self.minimum=math.inf;self.maximum=-math.inf
        self.square_sum=0.;self.absolute_sum=0.;self.outside=0;self.worst=None
        self.max_abs=-1.;self.band_edge=0

    def add(self,xyz,d,tolerance,seed_distance):
        if not len(d):return
        absolute=np.abs(d);index=int(absolute.argmax())
        if absolute[index]>self.max_abs:self.max_abs=float(absolute[index]);self.worst=xyz[index].copy()
        self.count+=len(d);self.minimum=min(self.minimum,float(d.min()));self.maximum=max(self.maximum,float(d.max()))
        self.square_sum+=float(d@d);self.absolute_sum+=float(absolute.sum())
        self.outside+=int(np.count_nonzero(absolute>tolerance))
        self.band_edge+=int(np.count_nonzero(seed_distance>ASSIGN_BAND*.8))

    def result(self,origin,metres_per_unit):
        return dict(count=self.count,min_mm=self.minimum,max_mm=self.maximum,max_abs_mm=self.max_abs,
                    rms_mm=math.sqrt(self.square_sum/self.count),range_mm=self.maximum-self.minimum,
                    mean_abs_mm=self.absolute_sum/self.count,outside_count=self.outside,
                    outside_percent=100*self.outside/self.count,band_edge_count=self.band_edge,
                    worst_point=(self.worst/metres_per_unit+origin).tolist())


def measure_scan(source,unit='m',tolerance_mm=5.,zone_size_m=2.,metadata=None,control=None):
    control=control or Control();control.check()
    tolerance_mm=float(tolerance_mm);zone_size_m=float(zone_size_m)
    if unit not in UNIT_MM or not math.isfinite(tolerance_mm) or tolerance_mm<=0:
        raise ValueError('请选择单位并输入正数容差 / Select units and a positive tolerance')
    if not math.isfinite(zone_size_m) or not .25<=zone_size_m<=20:
        raise ValueError('分区边长需为 0.25～20 米 / Zone size must be 0.25 to 20 metres')
    source=Path(source).resolve()
    if source.suffix.lower()!='.las':raise ValueError('整栋分析需要 LAS / Whole-scan inspection requires LAS')
    before=source.stat();reader=_LasSource(source)
    if not reader.count:raise ValueError('点云为空 / Empty point cloud')
    factor=UNIT_MM[unit]/1000.;origin=np.asarray(reader.header.offsets,dtype=float)
    stride=max(1,math.ceil(reader.count/SAMPLE_LIMIT));samples=[];colors=[];sample_normals=[]
    normal_fields=[next((n for n in reader.names if n.lower()==wanted),None) for wanted in ('normalx','normaly','normalz')]
    has_normals=all(normal_fields)
    def normals(records):
        return np.column_stack([np.asarray(records[n],dtype=float) for n in normal_fields]) if has_normals else None
    def unchanged():
        now=source.stat()
        if (now.st_size,now.st_mtime_ns)!=(before.st_size,before.st_mtime_ns):
            raise ValueError('分析期间源文件发生变化 / Source changed during analysis')
    def chunks():
        for start,records,_ in reader.chunks(control):
            xyz=(reader.xyz(records)-origin)*factor
            if not np.isfinite(xyz).all():raise ValueError('点云含无效坐标 / Non-finite coordinates')
            yield start,records,xyz
    for start,records,xyz in chunks():
        choice=slice((-start)%stride,None,stride)
        samples.append(xyz[choice]);colors.append(_rgb(reader,records)[choice])
        if has_normals:sample_normals.append(normals(records)[choice])
        control.log('读取点云与空间采样 / Reading spatial sample',15*(start+len(records))/reader.count)
    unchanged();sample=np.concatenate(samples);rgb=np.concatenate(colors)
    walls,limited=detect_walls(sample,control)
    moment=[Moments() for _ in walls]
    uv_bounds=[np.array([[np.inf]*2,[-np.inf]*2]) for _ in walls]
    assigned=ambiguous=0
    for start,records,xyz in chunks():
        labels,ambiguity=assign_points(xyz,walls,control,normals(records));ambiguous+=int(ambiguity.sum());assigned+=int((labels>=0).sum())
        for i in np.unique(labels[labels>=0]):
            points=xyz[labels==i];moment[i].add(points)
            wall=walls[i];uv=(points-wall['centroid'])@np.column_stack((wall['u'],wall['v']))
            uv_bounds[i][0]=np.minimum(uv_bounds[i][0],uv.min(axis=0));uv_bounds[i][1]=np.maximum(uv_bounds[i][1],uv.max(axis=0))
        control.log('全量点归属与墙面拟合 / Assigning all source points',30+30*(start+len(records))/reader.count)
    unchanged()
    maps=[];stats=[];zones=[]
    for wall,m,uv in zip(walls,moment,uv_bounds):
        if m.count<3:raise ValueError('自动识别的墙面点数不足 / Insufficient wall points')
        values,vectors=np.linalg.eigh(m.moment/m.count);normal=vectors[:,0]
        if normal@wall['normal']<0:normal=-normal
        wall['fit_center']=m.mean;wall['fit_normal']=normal
        wall['ratio']=max(0.,float(values[0]))/max(1e-20,float(values[1]))
        wall['uv_bounds']=uv
        resolution=max(.05,float(np.max(uv[1]-uv[0]))/399)
        shape=np.maximum(1,np.ceil((uv[1]-uv[0])/resolution).astype(int)+1)
        maps.append(dict(resolution=resolution,shape=shape,count=np.zeros(tuple(shape),dtype=np.int64),
                         minimum=np.full(tuple(shape),np.inf),maximum=np.full(tuple(shape),-np.inf)))
        stats.append(Statistics());zones.append({})
    seen=0
    for start,records,xyz in chunks():
        labels,_=assign_points(xyz,walls,control,normals(records))
        for i in np.unique(labels[labels>=0]):
            wall=walls[i];points=xyz[labels==i];seen+=len(points)
            d=(points-wall['fit_center'])@wall['fit_normal']*1000
            seed_distance=np.abs((points-wall['centroid'])@wall['normal'])
            stats[i].add(points,d,tolerance_mm,seed_distance)
            uv=(points-wall['centroid'])@np.column_stack((wall['u'],wall['v']))-wall['uv_bounds'][0]
            grid=np.floor(np.maximum(uv,0)/zone_size_m).astype(np.int64)
            unique,inverse=np.unique(grid,axis=0,return_inverse=True)
            for k,key in enumerate(unique):
                entry=zones[i].setdefault(tuple(key),Statistics());chosen=inverse==k
                entry.add(points[chosen],d[chosen],tolerance_mm,seed_distance[chosen])
            if sum(len(z) for z in zones)>4096:raise ValueError('分区过多，请增大分区边长 / Too many zones; increase zone size')
            raster=maps[i];cell=np.floor(np.maximum(uv,0)/raster['resolution']).astype(int)
            cell=np.minimum(cell,raster['shape']-1);indices=tuple(cell.T)
            np.add.at(raster['count'],indices,1);np.minimum.at(raster['minimum'],indices,d);np.maximum.at(raster['maximum'],indices,d)
        control.log('逐分区计算全部原始点 / Measuring every zone',60+30*(start+len(records))/reader.count)
    unchanged()
    if seen!=assigned:raise ValueError('全量点计数不一致 / Point accounting changed')
    sample_labels,_=assign_points(sample,walls,control,np.concatenate(sample_normals) if has_normals else None)
    steps=(np.asarray(reader.header.scales)*UNIT_MM[unit]).tolist();reports=[]
    for wall_index,(wall,m,stat,raster,wall_zones) in enumerate(zip(walls,moment,stats,maps,zones)):
        points=sample[sample_labels==wall_index]
        uv=(points-wall['centroid'])@np.column_stack((wall['u'],wall['v']))-wall['uv_bounds'][0]
        overlap=overlapping_surface_cells(uv,(points-wall['fit_center'])@wall['fit_normal'])
        info=stat.result(origin,factor)
        info.update(id=wall['id'],centroid=(wall['fit_center']/factor+origin).tolist(),normal=wall['fit_normal'].tolist(),
                    bounds=(m.bounds/factor+origin).tolist(),plane_origin=(wall['centroid']/factor+origin).tolist(),
                    u=wall['u'].tolist(),v=wall['v'].tolist(),uv_bounds=wall['uv_bounds'].tolist(),
                    map_resolution_m=raster['resolution'],planarity_ratio=wall['ratio'],overlap_cells=overlap.tolist(),zones=[])
        span=wall['uv_bounds'][1]-wall['uv_bounds'][0]
        for index,(key,values) in enumerate(sorted(wall_zones.items(),key=lambda item:(item[0][1],item[0][0]))):
            zone=values.result(origin,factor);lo=np.array(key)*zone_size_m;hi=np.minimum(lo+zone_size_m,span)
            # A point exactly on an outer grid line belongs to the last thin
            # zone. Its zero/small footprint is explicitly review-required.
            area=float(np.prod(np.maximum(hi-lo,0)))
            xs=(np.arange(raster['shape'][0])+.5)*raster['resolution'];ys=(np.arange(raster['shape'][1])+.5)*raster['resolution']
            selection=(xs[:,None]>=lo[0])&(xs[:,None]<hi[0])&(ys[None,:]>=lo[1])&(ys[None,:]<hi[1])
            occupied=int(np.count_nonzero((raster['count']>0)&selection))
            coverage=min(100.,occupied*raster['resolution']**2/max(area,1e-12)*100)
            reasons=[]
            overlap_count=int(np.count_nonzero(np.all((overlap+OVERLAP_CELL/2>=lo)&(overlap-OVERLAP_CELL/2<hi),axis=1)))
            if overlap_count:reasons.append('同位置存在分层表面，无法确认单一墙面 / Overlapping surfaces; wall unresolved')
            if values.count<30:reasons.append('点数不足 / Too few points')
            if area<.05 or coverage<30:reasons.append('覆盖不足或狭窄边缘 / Sparse coverage or narrow edge')
            if values.band_edge:reasons.append('接近归属边界，需检查混入物或漏分割 / Near membership band')
            if wall['ratio']>.01:reasons.append('墙面厚度较大，可能混入其他表面 / Thick candidate surface')
            if max(steps)>tolerance_mm:reasons.append('坐标步长大于容差 / Coordinate step exceeds tolerance')
            zone.update(id=f'{wall["id"]}-Z{index+1:03d}',grid=list(map(int,key)),uv_bounds=[lo.tolist(),hi.tolist()],
                        reference_area_m2=area,occupied_area_m2=occupied*raster['resolution']**2,
                        coverage_percent=coverage,overlap_cell_count=overlap_count,review_reasons=reasons,
                        status='review' if reasons else 'outside' if values.outside else 'within')
            info['zones'].append(zone)
        info['review_reasons']=sorted({reason for z in info['zones'] for reason in z['review_reasons']})
        info['status']='review' if info['review_reasons'] else 'outside' if info['outside_count'] else 'within'
        reports.append(info)
    metadata={k:str((metadata or {}).get(k,'')).strip()[:200] for k in ('project','site','operator','reference')}
    report=dict(version='1.9.0',source=str(source),source_size=before.st_size,source_mtime_ns=before.st_mtime_ns,
                source_count=reader.count,unit=unit,tolerance_mm=tolerance_mm,zone_size_m=zone_size_m,
                coordinate_steps_mm=steps,metadata=metadata,created_at=datetime.now().astimezone().isoformat(),
                assigned_count=assigned,unassigned_count=reader.count-assigned,ambiguous_count=ambiguous,
                assigned_point_percent=100*assigned/reader.count,sample_count=len(sample),sample_stride=stride,
                assignment_band_m=ASSIGN_BAND,ambiguity_m=AMBIGUITY,wall_limit_reached=limited,
                orientation_method='source_normals_with_spatial_fallback' if has_normals else 'sample_neighbourhood_normals',
                local_connection_depth_slack_m=LOCAL_SUPPORT_DEPTH,sampled_surface_depth_step_m=LAYER_STEP,
                overlap_check_cell_m=OVERLAP_CELL,
                method='automatic_connected_vertical_planes; all_assigned_points_least_squares; shared_wall_reference',
                walls=reports,zone_count=sum(len(w['zones']) for w in reports),source_unchanged=True)
    control.check();unchanged()
    assets=dict(sample=sample,rgb=rgb,labels=sample_labels,maps=maps,origin=origin,metres_per_unit=factor)
    return report,assets


def analyze_building(source,output,unit='m',tolerance_mm=5.,zone_size_m=2.,metadata=None,control=None):
    """Publish a complete report folder only after every deliverable succeeds."""
    from wall_report import write_deliverables
    from converter import write_json
    control=control or Control();control.check()
    output=Path(output).expanduser().resolve()
    if output.exists():raise FileExistsError('报告目录已存在 / Report destination already exists')
    output.parent.mkdir(parents=True,exist_ok=True)
    report,assets=measure_scan(source,unit,tolerance_mm,zone_size_m,metadata,control)
    report['output']=str(output)
    with tempfile.TemporaryDirectory(prefix='.inspection-',dir=output.parent) as temporary:
        work=Path(temporary).resolve()
        if work.parent!=output.parent or not work.name.startswith('.inspection-'):raise ValueError('Invalid staging path')
        write_deliverables(work,report,assets,control)
        control.check();after=Path(report['source']).stat()
        if (after.st_size,after.st_mtime_ns)!=(report['source_size'],report['source_mtime_ns']):
            raise ValueError('分析期间源文件发生变化 / Source changed during analysis')
        report['state']='succeeded';write_json(work/'report.json',report)
        if output.exists():raise FileExistsError('Report destination appeared during analysis')
        work.rename(output)
    control.log('整份点云报告已完成 / Whole-scan report complete',100)
    return report
