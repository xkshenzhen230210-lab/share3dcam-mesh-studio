"""Shared entry resolution and incomplete-export protection for UI and CLI."""
import json
from pathlib import Path

MODEL_SUFFIXES={'.glb','.b3dm','.json','.osgb','.obj','.ply','.stl','.mesh','.las'}
ENTRIES=('tileset.json','Model.osgb','Model.glb','Model.obj','Model.ply','Model.stl','Model.las',
         'osgb/Model.osgb','3dtiles/tileset.json','glb/Model.glb','obj/Model.obj',
         'ply/Model.ply','stl/Model.stl','las/Model.las')


def check_export_state(path):
    folder=path if path.is_dir() else path.parent
    roots=[folder]
    if folder.name.lower() in ('obj','osgb','glb','ply','stl'):roots.append(folder.parent)
    for root in roots:
        for name in ('mesh_result.json','mesh_progress.json'):
            marker=root/name
            if not marker.is_file():continue
            try:state=json.loads(marker.read_text(encoding='utf-8'))
            except (OSError,ValueError):continue
            status=state.get('state')
            if status=='succeeded':break
            if status in ('running','checking','failed','cancelled','interrupted'):
                labels={'failed':'上次导出失败','cancelled':'上次导出已取消','interrupted':'上次导出已中断'}
                message=labels.get(status,'导出尚未完成或已中断')
                raise ValueError(message+'，当前目录不是完整模型 / Export incomplete or interrupted: '+str(root))


def resolve_model(value, allow_glb_collection=False):
    path=Path(str(value).strip().strip('"')).resolve()
    check_export_state(path)
    if path.is_dir():
        for name in ENTRIES:
            if (path/name).is_file():return path/name
        candidates=[p for p in path.iterdir() if p.is_file() and p.suffix.lower() in MODEL_SUFFIXES- {'.json','.mesh'}]
        if len(candidates)==1:return candidates[0]
        if allow_glb_collection and any(path.rglob('*.glb')):return path
        if len(candidates)>1:raise ValueError('目录包含多个模型，请选择具体模型文件 / Multiple models found; select a model file')
        raise ValueError('目录中没有可打开的模型文件；材质和贴图不能单独打开 / No model geometry file found')
    if not path.is_file():raise ValueError('模型路径不存在 / Model not found: '+str(path))
    if path.suffix.lower() not in MODEL_SUFFIXES:raise ValueError('不支持此文件格式 / Unsupported file format')
    return path
