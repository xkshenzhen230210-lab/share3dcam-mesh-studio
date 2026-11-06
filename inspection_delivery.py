"""Verified report delivery with inherited share permissions and atomic publish."""
import hashlib
from pathlib import Path
import shutil
import time
from uuid import uuid4

from converter import write_json


def source_unchanged(source,report):
    current=source.stat()
    if (current.st_size,current.st_mtime_ns)!=(report['source_size'],report['source_mtime_ns']):
        raise ValueError('分析期间源文件发生变化 / Source changed during analysis')


def _copy_file(source,destination,control):
    expected=hashlib.sha256()
    with source.open('rb') as reader,destination.open('wb') as writer:
        while chunk:=reader.read(1024*1024):
            control.check();writer.write(chunk);expected.update(chunk)
    actual=hashlib.sha256()
    with destination.open('rb') as reader:
        while chunk:=reader.read(1024*1024):control.check();actual.update(chunk)
    if actual.digest()!=expected.digest():raise OSError('报告文件复制校验失败 / Report copy verification failed')


def publish_report(result,destination,source,report,control):
    """Never expose an incomplete final folder or overwrite an existing report.

    Private TemporaryDirectory ACLs are local-only. An ordinary sibling here
    inherits the selected share's permissions; no existing ACL is changed.
    """
    result,destination,source=map(Path,(result,destination,source))
    control.check();source_unchanged(source,report)
    if destination.exists():raise FileExistsError('报告目录已存在 / Report destination exists')
    destination.parent.mkdir(parents=True,exist_ok=True)
    stage=destination.parent/('inspection-publish-'+uuid4().hex)
    stage.mkdir();published=dict(report,output=str(destination),delivery='requested')
    try:
        write_json(result/'report.json',published)
        files=sorted(p for p in result.rglob('*') if p.is_file())
        for i,item in enumerate(files):
            control.check();target=stage/item.relative_to(result);target.parent.mkdir(parents=True,exist_ok=True)
            for attempt in range(3):
                try:_copy_file(item,target,control);break
                except OSError:
                    if attempt==2:raise
                    control.check();time.sleep(.2*(attempt+1))
            control.log(f'保存并校验报告 / Saving verified report {i+1}/{len(files)}',99)
        control.check();source_unchanged(source,report)
        if destination.exists():raise FileExistsError('Report destination appeared during analysis')
        stage.rename(destination)
        return published
    finally:
        # Only remove this call's random owned sibling. Cleanup must never hide
        # the original network/cancellation error or delete the final report.
        try:
            if stage.parent.resolve()==destination.parent.resolve() and stage.name.startswith('inspection-publish-'):
                shutil.rmtree(stage,ignore_errors=True)
        except OSError:pass
