"""Portable engineering handoff: PDF, offline HTML, CSV, maps and viewer caches."""
from collections import Counter
import csv
from html import escape
import json
from pathlib import Path
import numpy as np

from converter import write_json
from wall_flatness import deviation_colors
from inspection_figures import ASSETS,FONT,overview,wall_map,region_colors

STATUS={'within':'容差内 / Within','outside':'存在超差 / Outside','review':'需复核 / Review'}
NOTES=[
    '检测口径：各墙面全部归属原始点参与最小二乘平面拟合；同一墙面各分区共用该参考平面，不按分区重新拟合。',
    '对象识别：根据近竖直平面、表面方向和空间连通性自动分割。墙面编号是几何候选编号，不代表房号或建筑轴网；柜体、玻璃等平面可能被识别为候选。',
    '覆盖范围：未归属点包含地面、顶面、遮挡、边界、不确定表面及未识别墙面。已归属点占比不等于墙面覆盖率；未归属区域没有容差判定。',
    '判定边界：容差由使用者设置。本报告为扫描数据的平面偏差技术分析，不等同于 2 米靠尺、最小区域平整度、扫描仪测量精度或自动工程验收结论。',
    '色谱：蓝色为负偏差，绿色接近零，红色为正偏差；正负由记录的参考法向决定，不表示建筑内外。每个有点网格显示绝对偏差最大的点，空白格不插值。',
    '数据质量：低覆盖、小片边缘、归属边界附近点、较厚表面及坐标步长大于容差的区域标为需复核。点归属之后没有剔除离群点。',
    '识别限制：空间采样决定候选表面和连通关系。未被采样捕获的孤立突起、稀疏墙面和复杂交界可能未归属；局部连接深度余量为 25 mm，另计沿表面间距。未归属点不能解释为无缺陷。',
    '现场使用：按总览图和分区号定位，结合原色点云及最大偏差坐标核实构件和遮挡；整改后可用同一单位、容差和分区设置复测。源坐标 Z 按竖直方向使用。',
]


def _csv(path,headers,rows):
    def safe(value):
        if isinstance(value,str) and value.startswith(('=','+','-','@')):return "'"+value
        return value
    with Path(path).open('w',encoding='utf-8-sig',newline='') as f:
        writer=csv.writer(f);writer.writerow(headers)
        writer.writerows([[safe(v) for v in row] for row in rows])


def _cache(folder,xyz,rgb,origin,source,source_count):
    folder.mkdir(parents=True,exist_ok=True)
    packed=np.ones((len(xyz),7),dtype='<f4');packed[:,:3]=xyz-origin;packed[:,3:6]=rgb
    if not np.isfinite(packed).all():raise ValueError('Invalid inspection preview')
    packed.tofile(folder/'points.bin')
    write_json(folder/'model.spoints',dict(format='share3dcam-points',version=1,kind='points',stride_floats=7,
               count=len(xyz),source_count=source_count,data='points.bin',origin=origin.tolist(),
               bounds=[xyz.min(axis=0).tolist(),xyz.max(axis=0).tolist()],sh_degree=0,preview=True,
               sampled=len(xyz)<source_count,source=source,analysis='automatic_wall_inspection'))


def write_deliverables(folder,report,assets,control):
    folder=Path(folder);(folder/'figures').mkdir()
    xyz=assets['sample']/assets['metres_per_unit']+assets['origin'];labels=assets['labels']
    palette=region_colors(len(report['walls']));colors=np.full((len(xyz),3),.60)
    selected=labels>=0
    if selected.any():colors[selected]=palette[labels[selected]]
    _cache(folder/'overview',xyz,colors,assets['origin'],report['source'],report['source_count'])
    overview(folder/'figures/overview.png',report,assets)
    for i,(wall,raster) in enumerate(zip(report['walls'],assets['maps'])):
        control.check();points=xyz[labels==i]
        d=((points-wall['centroid'])@np.asarray(wall['normal']))*assets['metres_per_unit']*1000
        _cache(folder/wall['id'],points,deviation_colors(d,report['tolerance_mm']),np.asarray(wall['centroid']),report['source'],wall['count'])
        _cache(folder/wall['id']/'original',points,assets['rgb'][labels==i],np.asarray(wall['centroid']),report['source'],wall['count'])
        wall_map(folder/f'figures/{wall["id"]}.png',wall,raster,report['tolerance_mm'],assets['metres_per_unit'])
        # Full-resolution grid data can be independently examined; blanks are
        # represented as empty cells rather than invented zero deviations.
        nonempty=np.argwhere(raster['count']>0)
        _csv(folder/wall['id']/'grid.csv',['U index','V index','Count','Minimum mm','Maximum mm'],
             ([int(x),int(y),int(raster['count'][x,y]),float(raster['minimum'][x,y]),float(raster['maximum'][x,y])] for x,y in nonempty))
        control.log(f'生成墙面图 / Creating wall figures {i+1}/{len(report["walls"])}',90+6*(i+1)/max(1,len(report['walls'])))
    zones=[z for wall in report['walls'] for z in wall['zones']]
    headers=['分区 Zone','状态 Status','点数 Points','最小偏差 Min mm','最大偏差 Max mm','最大绝对偏差 Max abs mm',
             '均方根 RMS mm','峰谷差 Range mm','超差点 Outside points','超差比例 Outside %','覆盖率 Occupancy %',
             '最差点 X','最差点 Y','最差点 Z','源坐标单位 Units','复核原因 Review reasons']
    rows=lambda values:([z['id'],STATUS[z['status']],z['count'],z['min_mm'],z['max_mm'],z['max_abs_mm'],z['rms_mm'],
                         z['range_mm'],z['outside_count'],z['outside_percent'],z['coverage_percent'],*z['worst_point'],
                         report['unit'],'; '.join(z['review_reasons'])] for z in values)
    _csv(folder/'分区统计.csv',headers,rows(zones))
    _csv(folder/'超差与复核清单.csv',headers,rows(z for z in zones if z['status']!='within'))
    _html(folder,report)
    control.log('排版完整报告 / Typesetting complete report',97);_pdf(folder,report,control)
    control.check()


def _html(folder,report):
    def table(headers,rows):
        return '<table><thead><tr>'+''.join('<th>'+escape(str(v))+'</th>' for v in headers)+'</tr></thead><tbody>'+''.join(
            '<tr>'+''.join('<td>'+escape(str(v))+'</td>' for v in row)+'</tr>' for row in rows)+'</tbody></table>'
    title=report['metadata']['project'] or Path(report['source']).stem
    sections=[]
    for w in report['walls']:
        rows=[[z['id'],STATUS[z['status']],f'{z["count"]:,}',f'{z["max_abs_mm"]:.3f}',f'{z["rms_mm"]:.3f}',
               f'{z["outside_percent"]:.2f}%',f'{z["coverage_percent"]:.1f}%'] for z in w['zones']]
        sections.append(f'<section id="{w["id"]}"><h2>{w["id"]} · {escape(STATUS[w["status"]])}</h2>'
            f'<p>全量点 {w["count"]:,} · 最大绝对偏差 {w["max_abs_mm"]:.3f} mm · RMS {w["rms_mm"]:.3f} mm</p>'
            f'<img src="figures/{w["id"]}.png" alt="{w["id"]} 墙面分区偏差图">'+
            table(['分区','状态','点数','最大绝对偏差 mm','RMS mm','超差比例','有点覆盖'],rows)+
            '<p>复核说明：'+escape('；'.join(w['review_reasons']) or '未触发数据质量提示。')+'</p></section>')
    index=' · '.join(f'<a href="#{w["id"]}">{w["id"]}</a>' for w in report['walls'])
    text=('<!doctype html><html lang="zh"><meta charset="utf-8"><title>'+escape(title)+' - 墙面分析报告</title>'+\
        '<style>body{font:16px system-ui,"Microsoft YaHei",sans-serif;max-width:1120px;margin:0 auto;color:#17263c;background:#f5f7fa}header,section{background:white;padding:28px;margin:18px 0;border-radius:10px}header{border-top:8px solid #d92f29}h1{font-size:30px}h2{font-size:24px}img{width:100%;height:auto}table{width:100%;border-collapse:collapse;font-size:14px}td,th{padding:10px;border-bottom:1px solid #dfe6ef;text-align:left}th{background:#edf2f8}p{line-height:1.7;overflow-wrap:anywhere}a{color:#176399}nav{line-height:2.1}@media print{body{background:white}section{break-before:page}header{border-radius:0}a{color:inherit}}</style>'+\
        f'<header><h1>{escape(title)}</h1><h2>墙面平面偏差检测报告 / Wall plane-deviation report</h2><p>SHARE3DCAM 电商销售中心 · {escape(report["created_at"])}</p>'+
        f'<p>{len(report["walls"])} 个墙面候选 · {report["zone_count"]} 个分区 · 容差 ±{report["tolerance_mm"]:g} mm · 分区 {report["zone_size_m"]:g} m</p>'+
        f'<p>源文件：{escape(report["source"])}<br>已归属 {report["assigned_count"]:,} / {report["source_count"]:,} 点；未归属 {report["unassigned_count"]:,} 点（含归属冲突 {report["ambiguous_count"]:,} 点）。</p>'+
        '<p><a href="墙面平整度报告.pdf">完整 PDF</a> · <a href="分区统计.csv">分区统计表</a> · <a href="超差与复核清单.csv">超差与复核清单</a></p><nav>'+index+'</nav></header>'+\
        '<section><h2>墙面定位总览</h2><img src="figures/overview.png" alt="墙面定位总览"></section>'+''.join(sections)+\
        '<section><h2>方法、范围与现场使用</h2>'+''.join('<p>'+escape(n)+'</p>' for n in NOTES)+'</section></html>')
    (folder/'report.html').write_text(text,encoding='utf-8')


def _pdf(folder,report,control):
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.lib import colors
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.pagesizes import A4
    from reportlab.platypus import SimpleDocTemplate,Paragraph,Spacer,Table,TableStyle,Image,PageBreak
    from reportlab.lib.utils import ImageReader
    pdfmetrics.registerFont(TTFont('InspectionSC',str(FONT)))
    pdfmetrics.registerFontFamily('InspectionSC',normal='InspectionSC',bold='InspectionSC',italic='InspectionSC',boldItalic='InspectionSC')
    body=ParagraphStyle('Body',fontName='InspectionSC',fontSize=9,leading=14,textColor=colors.HexColor('#243449'),spaceAfter=7,wordWrap='CJK')
    small=ParagraphStyle('Small',parent=body,fontSize=7.5,leading=11,spaceAfter=0)
    h1=ParagraphStyle('H1',parent=body,fontSize=23,leading=32,spaceAfter=15)
    h2=ParagraphStyle('H2',parent=body,fontSize=15,leading=22,spaceAfter=10)
    def p(text,style=body):return Paragraph(escape(str(text)).replace('\n','<br/>'),style)
    width=A4[0]-84
    def table(headers,rows,widths=None):
        data=[[p(v,small) for v in headers]]+[[p(v,small) for v in row] for row in rows]
        t=Table(data,colWidths=widths or [width/len(headers)]*len(headers),repeatRows=1,hAlign='LEFT')
        t.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#e7edf5')),
                              ('ROWBACKGROUNDS',(0,1),(-1,-1),[colors.white,colors.HexColor('#f8fafc')]),
                              ('LINEBELOW',(0,0),(-1,0),.6,colors.HexColor('#7e91aa')),
                              ('LINEBELOW',(0,1),(-1,-1),.3,colors.HexColor('#dce4ee')),
                              ('VALIGN',(0,0),(-1,-1),'TOP'),('LEFTPADDING',(0,0),(-1,-1),6),
                              ('RIGHTPADDING',(0,0),(-1,-1),6),('TOPPADDING',(0,0),(-1,-1),6),('BOTTOMPADDING',(0,0),(-1,-1),6)]))
        return t
    def picture(path,max_height):
        from PIL import Image as PILImage
        with PILImage.open(path) as im:w,h=im.size
        scale=min(width/w,max_height/h)
        return Image(str(path),width=w*scale,height=h*scale,hAlign='CENTER')
    project=report['metadata']['project'] or Path(report['source']).stem
    report_id='S3D-'+report['created_at'][:19].replace('-','').replace(':','').replace('T','-')
    def page(canvas,doc):
        control.check();canvas.saveState();canvas.setFillColor(colors.HexColor('#101d30'));canvas.rect(0,A4[1]-65,A4[0],65,fill=1,stroke=0)
        canvas.drawImage(ImageReader(str(ASSETS/'share3dcam.png')),42,A4[1]-45,width=133,height=29,mask='auto',preserveAspectRatio=True,anchor='c')
        canvas.setFillColor(colors.white);canvas.setFont('InspectionSC',10);canvas.drawRightString(A4[0]-42,A4[1]-29,'SHARE3DCAM 电商销售中心')
        canvas.setFont('InspectionSC',7);canvas.drawRightString(A4[0]-42,A4[1]-43,'E-commerce Sales Center | Mesh Studio 1.8.0')
        canvas.setStrokeColor(colors.HexColor('#dce4ee'));canvas.line(42,37,A4[0]-42,37)
        canvas.setFillColor(colors.HexColor('#53657b'));canvas.setFont('InspectionSC',7)
        canvas.drawString(42,24,report_id);canvas.drawRightString(A4[0]-42,24,f'第 {doc.page} 页 / Page {doc.page}')
        canvas.restoreState()
    zones=[z for w in report['walls'] for z in w['zones']];counts=Counter(z['status'] for z in zones)
    story=[p('墙面平面偏差检测报告',h1),p('Automatic wall segmentation & plane-deviation inspection'),Spacer(1,8),p(project,h2)]
    info=[['项目 / Project',project],['位置 / Site',report['metadata']['site'] or '未填写 / Not specified'],
          ['编制人 / Prepared by',report['metadata']['operator'] or '未填写 / Not specified'],
          ['项目依据 / Reference',report['metadata']['reference'] or '未指定验收标准；采用自定义平面偏差容差'],
          ['生成时间 / Generated',report['created_at']],['源文件 / Source',Path(report['source']).name],
          ['坐标单位 / Units',report['unit']],['分析设置 / Settings',f'容差 ±{report["tolerance_mm"]:g} mm；分区边长 {report["zone_size_m"]:g} m']]
    story+=[table(['项目 / Item','内容 / Value'],info,[125,width-125]),Spacer(1,18),p('结果摘要 / Executive summary',h2),
            table(['墙面候选 / Walls','分区 / Zones','容差内 / Within','存在超差 / Outside','需复核 / Review'],
                  [[len(report['walls']),len(zones),counts['within'],counts['outside'],counts['review']]]),Spacer(1,10),
            p(f'共读取 {report["source_count"]:,} 个原始点，其中 {report["assigned_count"]:,} 点归属至墙面候选；{report["unassigned_count"]:,} 点未归属。需复核分区也可能存在超差，详见逐区数值。'),
            p('本报告用于施工问题定位、整改沟通和复测记录。结果仅针对已识别且有点覆盖的表面；正式验收应结合合同、适用标准和现场复核。'),Spacer(1,22),
            p('编制：________________    复核：________________'),p('施工单位：____________    监理单位：____________'),PageBreak(),
            p('01  墙面定位与覆盖范围',h1),picture(folder/'figures/overview.png',440),Spacer(1,8),
            p(f'彩色为自动识别的墙面候选，编号与后续章节一致。灰色为未归属的采样点。定位图显示 {report["sample_count"]:,} 个采样点，所有数值统计均使用原始全量归属点。'),
            table(['原始点','已归属点','未归属点','其中归属冲突'],[[f'{report["source_count"]:,}',f'{report["assigned_count"]:,}',f'{report["unassigned_count"]:,}',f'{report["ambiguous_count"]:,}']]),
            p(f'已归属点占比 {report["assigned_point_percent"]:.2f}%，这不是墙面面积覆盖率。归属搜索带为 {report["assignment_band_m"]*1000:g} mm，独立于容差。未归属区域不作容差判定。')]
    if report['wall_limit_reached']:story.append(p('已达到自动识别数量上限；仍有待识别区域，不能视为全场覆盖。'))
    story+=[PageBreak(),p('02  墙面汇总 / Wall register',h1)]
    rows=[[w['id'],len(w['zones']),f'{w["count"]:,}',f'{w["max_abs_mm"]:.3f}',f'{w["rms_mm"]:.3f}',f'{w["outside_percent"]:.2f}',STATUS[w['status']]] for w in report['walls']]
    story.append(table(['墙面','分区数','原始点','最大绝对\n偏差 mm','RMS\nmm','超差\n比例 %','状态'],rows,[45,35,80,80,65,60,width-365]))
    if not rows:story.append(p('未识别到满足条件的墙面候选。本报告没有可判定墙面；请检查数据方向、密度及是否包含墙面。'))
    for w in report['walls']:
        control.check();story += [PageBreak(),p(f'03  {w["id"]} 墙面分区分析',h1),
            p(f'{STATUS[w["status"]]} | {w["count"]:,} 个原始点 | {len(w["zones"])} 个分区'),
            picture(folder/f'figures/{w["id"]}.png',240),
            p('黑色 × 标记最大绝对偏差位置；浅灰为无数据。图中分区号须与墙面号组合使用。',small),Spacer(1,8),
            table(['最大绝对偏差','均方根 RMS','峰谷差','超差点比例'],[[f'{w["max_abs_mm"]:.3f} mm',f'{w["rms_mm"]:.3f} mm',f'{w["range_mm"]:.3f} mm',f'{w["outside_percent"]:.2f}%']]),Spacer(1,10)]
        rows=[[z['id'].split('-')[-1],f'{z["count"]:,}',f'{z["max_abs_mm"]:.3f}',f'{z["rms_mm"]:.3f}',f'{z["outside_percent"]:.2f}',f'{z["coverage_percent"]:.1f}',STATUS[z['status']]] for z in w['zones']]
        story.append(table(['分区','点数','最大绝对\n偏差 mm','RMS\nmm','超差\n比例 %','有点\n覆盖 %','状态'],rows,[45,70,85,65,65,60,width-390]))
        story+=[Spacer(1,9),p('最大偏差点源坐标 ('+report['unit']+')：'+', '.join(f'{v:.6f}' for v in w['worst_point'])),
                p('复核说明：'+'；'.join(w['review_reasons']) if w['review_reasons'] else '未触发本软件的数据质量复核提示。',small)]
    story += [PageBreak(),p('04  超差与复核定位清单',h1),p('按最大绝对偏差从高到低排列。坐标使用源坐标单位；请结合现场坐标系定位，不能直接当作建筑轴网。')]
    issues=sorted((z for z in zones if z['status']!='within'),key=lambda z:z['max_abs_mm'],reverse=True)
    rows=[[z['id'],f'{z["max_abs_mm"]:.3f}',f'{z["outside_percent"]:.2f}',', '.join(f'{v:.4f}' for v in z['worst_point']),STATUS[z['status']]] for z in issues]
    story.append(table(['分区','最大绝对\n偏差 mm','超差 %',f'最差点 X, Y, Z ({report["unit"]})','状态'],rows,[75,75,55,width-275,70]))
    if not issues:story.append(p('已分析分区未触发超差或复核条件。未归属区域仍不作判定。'))
    story += [PageBreak(),p('05  方法、范围与复测说明',h1)]
    story += [p(n) for n in NOTES]
    story += [p('量化步长 ('+report['unit']+' 换算为 mm)：'+', '.join(f'{v:g}' for v in report['coordinate_steps_mm'])),
              p('归属方向来源：'+('源文件法向与局部空间几何' if report['orientation_method'].startswith('source_') else '局部邻域几何估计')),p('完整源路径：'+report['source']),
              p('可追溯信息：源文件大小 '+str(report['source_size'])+' 字节；修改时间戳 '+str(report['source_mtime_ns'])+'；算法版本 '+report['version']),
              p('同目录包含：分区统计.csv、超差与复核清单.csv、report.json（参考平面、坐标、单位、参数）、各墙面的全量偏差网格和离线 HTML 报告。')]
    doc=SimpleDocTemplate(str(folder/'墙面平整度报告.pdf'),pagesize=A4,rightMargin=42,leftMargin=42,topMargin=84,bottomMargin=52,
                          title=f'{project} - 墙面平面偏差检测报告',author='SHARE3DCAM 电商销售中心')
    doc.build(story,onFirstPage=page,onLaterPages=page)
