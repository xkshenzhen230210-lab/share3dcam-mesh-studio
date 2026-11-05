"""Small workspace operations shared by the desktop controls."""
import json
import math
import os
from pathlib import Path
import shutil
import time
from uuid import uuid4

from PIL import Image

from converter import write_json


def validated_box(values):
    try:
        box = tuple(float(value) for value in values)
    except (ValueError, TypeError) as error:
        raise ValueError('剪切范围须为有效数字 / Enter valid clipping numbers') from error
    if len(box) != 6 or not all(math.isfinite(v) for v in box) or any(box[i] >= box[i+3] for i in range(3)):
        raise ValueError('各轴最小值须小于最大值 / Min must be below Max on each axis')
    return box


class ClipHistory:
    def __init__(self, bounds):
        self.original = self.box = validated_box(bounds)
        self.history = []

    def edit(self, values, record=True):
        box = validated_box(values)
        if box == self.box:
            return False
        if record:
            self.history.append(self.box)
            del self.history[:-20]
        self.box = box
        return True

    def undo(self):
        if not self.history:
            return False
        self.box = self.history.pop()
        return True


def read_recent(path):
    try:
        if path.stat().st_size > 128_000:
            return []
        entries = json.loads(path.read_text(encoding='utf-8'))
        if isinstance(entries, list):
            return [entry for entry in entries if isinstance(entry, str) and entry and '\x00' not in entry][:8]
    except (OSError, ValueError):
        pass
    return []


def remember_model(path, model):
    name = str(model)
    entries = [entry for entry in read_recent(path) if os.path.normcase(entry) != os.path.normcase(name)]
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f'.recent-{uuid4().hex}.json')
    try:
        temp.write_text(json.dumps([name, *entries[:7]], ensure_ascii=False, indent=2), encoding='utf-8')
        temp.replace(path)
    finally:
        temp.unlink(missing_ok=True)


def available_output(path):
    """Use the requested empty directory or choose a fresh numbered sibling."""
    if not path.exists():
        return path
    if not path.is_dir():
        raise ValueError('输出路径须为文件夹 / Output must be a folder')
    if not path.name:
        return available_output(path / 'SHARE3DCAM_export')
    if not any(path.iterdir()):
        return path
    for index in range(2, 10000):
        candidate = path.with_name(f'{path.name}_{index:02d}')
        if not candidate.exists():
            return candidate
    raise ValueError('请选择新的输出目录 / Choose a new output folder')


def save_view_snapshot(ipc, destination, control, viewer, after_seq):
    token = uuid4().hex
    write_json(ipc / 'snapshot_request.json', {'id': token, 'after_seq': after_seq})
    response = ipc / 'snapshot_result.json'
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        control.check()
        if viewer.poll() is not None:
            raise RuntimeError('查看器已关闭 / Viewer closed')
        try:
            result = json.loads(response.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            result = {}
        if result.get('id') == token:
            if result.get('error'):
                raise RuntimeError('无法截取视图 / Could not capture the view')
            break
        time.sleep(.05)
    else:
        raise TimeoutError('截图超时，请重试 / Snapshot timed out')
    with Image.open(ipc / 'snapshot.png') as image:
        if image.format != 'PNG':
            raise ValueError('截图文件无效 / Invalid snapshot')
        image.load()
    control.check()
    # Publish beside the destination so a failed write never leaves a partial PNG.
    temp = destination.with_name(f'.snapshot-{token}.png')
    try:
        shutil.copyfile(ipc / 'snapshot.png', temp)
        control.check()
        temp.replace(destination)
    finally:
        temp.unlink(missing_ok=True)
