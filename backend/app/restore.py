"""ZIP 预览、准备恢复，以及服务启动前的数据目录替换。"""
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import sqlite3
import stat
import time
import uuid
import zipfile

from . import config
from .backup import digest
from .lifecycle import serialized

MAX_ARCHIVE_BYTES = 512 * 1024 * 1024
MAX_EXPANDED_BYTES = 4 * 1024 * 1024 * 1024
MAX_FILES = 10000


def pending_path():
    return config.BASE_DIR / 'restore-pending.json'


def write_json(path, value):
    temp = path.with_name(path.name + '.tmp')
    with temp.open('w', encoding='utf-8') as output:
        json.dump(value, output, ensure_ascii=False, indent=2)
        output.flush(); os.fsync(output.fileno())
    os.replace(temp, path)


def stage_dir(token):
    if not isinstance(token, str) or not re.fullmatch('[a-f0-9]{32}', token):
        raise ValueError('恢复预览编号无效')
    return config.BASE_DIR / '.restore-staging' / token


def validate_database(path):
    conn = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)
    try:
        if conn.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
            raise ValueError('备份数据库完整性检查失败')
        if conn.execute("SELECT 1 FROM sqlite_master WHERE type IN ('trigger','view') LIMIT 1").fetchone():
            raise ValueError('备份含有不支持的数据库对象')
        for table, fields in {'docs': {'id', 'filename', 'file_hash', 'file_path'},
                              'chats': {'id', 'role', 'content'},
                              'memories': {'id', 'content'}}.items():
            columns = {r[1] for r in conn.execute(f'PRAGMA table_info({table})')}
            if not fields <= columns:
                raise ValueError(f'备份数据库缺少必要的 {table} 数据结构')
        return {table: conn.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]
                for table in ('docs', 'chats', 'memories')}
    finally:
        conn.close()


def verify_files(root, checksums):
    actual = {p.relative_to(root).as_posix() for p in root.rglob('*') if p.is_file()}
    if not isinstance(checksums, dict) or set(checksums) != actual:
        raise ValueError('备份文件清单不完整')
    for relative, expected in checksums.items():
        path = root / relative
        if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()) or digest(path) != expected:
            raise ValueError(f'备份文件校验失败：{relative}')


def preview_restore(source):
    source.seek(0, 2)
    if source.tell() > MAX_ARCHIVE_BYTES:
        raise ValueError('备份压缩包不能超过 512 MB')
    source.seek(0)
    token = uuid.uuid4().hex
    stage = stage_dir(token)
    data = stage / 'data'
    data.mkdir(parents=True, mode=0o700)
    try:
        with zipfile.ZipFile(source) as archive:
            entries = archive.infolist()
            if len(entries) > MAX_FILES or sum(e.file_size for e in entries) > MAX_EXPANDED_BYTES:
                raise ValueError('备份解压大小或文件数量超过限制')
            seen = set()
            for entry in entries:
                name = entry.filename
                relative = PurePosixPath(name)
                parts = relative.parts
                if ('\\' in name or relative.is_absolute() or '..' in parts or ':' in name or
                        not parts or parts[0] != 'Nebula-Memory' or stat.S_ISLNK(entry.external_attr >> 16)):
                    raise ValueError('备份包含不安全路径或符号链接')
                key = name.rstrip('/').casefold()
                if key in seen:
                    raise ValueError('备份包含重复文件路径')
                seen.add(key)
                if entry.is_dir():
                    continue
                relative = Path(*parts[1:])
                if not parts[1:] or (relative.as_posix() not in ('memory.db', 'settings.json', 'backup-manifest.json') and parts[1] != 'uploads'):
                    raise ValueError('备份包含未知文件')
                target = data / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(entry) as origin, target.open('xb') as output:
                    shutil.copyfileobj(origin, output, 1024 * 1024)
        manifest_file = data / 'backup-manifest.json'
        manifest = json.loads(manifest_file.read_text(encoding='utf-8'))
        if manifest.get('product') != 'Nebula Memory' or manifest.get('format') not in (1, 2):
            raise ValueError('不是受支持的 Nebula Memory 备份')
        manifest_file.unlink()
        if manifest['format'] == 2:
            verify_files(data, manifest.get('checksums'))
        counts = validate_database(data / 'memory.db')
        settings = data / 'settings.json'
        if settings.exists():
            saved = json.loads(settings.read_text(encoding='utf-8'))
            normalized = config.validate_patch(saved, base=config.DEFAULTS)
            if normalized != saved:
                write_json(settings, normalized)  # 兼容旧版保存的数字字符串。
        conn = sqlite3.connect(data / 'memory.db')
        conn.row_factory = sqlite3.Row
        try:
            mapping = manifest.get('document_files', {})
            for row in conn.execute('SELECT id,filename,file_path FROM docs').fetchall():
                relative = mapping.get(str(row['id']))
                if not relative and manifest['format'] == 1:
                    old = (row['file_path'] or '').replace('\\', '/')
                    if '/uploads/' in old:
                        relative = 'uploads/' + old.split('/uploads/', 1)[1]
                if not isinstance(relative, str) or '\\' in relative or '..' in PurePosixPath(relative).parts or not relative.startswith('uploads/'):
                    raise ValueError(f'备份缺少原文：{row["filename"]}，请从新版重新导出')
                if not (data / relative).is_file():
                    raise ValueError(f'备份缺少原文：{row["filename"]}')
                conn.execute('UPDATE docs SET file_path=? WHERE id=?', (str(config.DATA_DIR / relative), row['id']))
            # 旧关键词索引不再对应空的新向量库，等待用户统一重建。
            if conn.execute("SELECT 1 FROM sqlite_master WHERE name='kb_fts'").fetchone():
                conn.execute('DELETE FROM kb_fts')
            conn.commit()
        finally:
            conn.close()
        summary = {**counts, 'has_settings': settings.exists(), 'legacy': manifest['format'] == 1,
                   'created': manifest.get('created', ''), 'restart_required': True}
        write_json(stage / 'plan.json', {'id': token, 'created': time.time(), 'summary': summary,
                                         'checksums': {p.relative_to(data).as_posix(): digest(p) for p in data.rglob('*') if p.is_file()}})
        return {'preview_id': token, **summary}
    except Exception:
        shutil.rmtree(stage)
        raise


@serialized
def queue_restore(token, restore_settings=False):
    if pending_path().exists():
        raise ValueError('已有等待重启的恢复任务')
    stage = stage_dir(token)
    plan = json.loads((stage / 'plan.json').read_text(encoding='utf-8'))
    if time.time() - plan['created'] > 86400:
        raise ValueError('恢复预览已过期，请重新选择备份')
    verify_files(stage / 'data', plan['checksums'])
    if restore_settings and not (stage / 'data' / 'settings.json').is_file():
        raise ValueError('此备份不包含配置文件，请保留本机配置')
    write_json(pending_path(), {'id': token, 'restore_settings': restore_settings})
    return {'queued': True, 'restart_required': True, 'message': '恢复已准备就绪。请关闭并重新启动知识库服务，随后重建向量索引；原数据目录会保留。'}


def activate_pending():
    """仅在获取服务进程锁后、打开 SQLite/Chroma 前调用。"""
    marker = pending_path()
    if not marker.exists():
        return
    pending = json.loads(marker.read_text(encoding='utf-8'))
    token = pending['id']
    stage = stage_dir(token)
    staged_data = stage / 'data'
    previous = config.BASE_DIR / f'data-before-restore-{token}'
    if staged_data.exists():
        plan = json.loads((stage / 'plan.json').read_text(encoding='utf-8'))
        verify_files(staged_data, plan['checksums'])
        if config.DATA_DIR.is_symlink() or previous.is_symlink():
            raise ValueError('数据目录不能是符号链接')
        if not previous.exists():
            if not pending.get('restore_settings'):
                target = staged_data / 'settings.json'
                if config.SETTINGS_FILE.is_file():
                    shutil.copy2(config.SETTINGS_FILE, target)
                else:
                    target.unlink(missing_ok=True)
            write_json(staged_data / 'restore-report.json', {'id': token, 'previous_data': str(previous),
                                                            'restored_at': time.time(), 'needs_rebuild': True})
            # 更新计划保证中断重启时仍能验证已准备的数据。
            plan['checksums'] = {p.relative_to(staged_data).as_posix(): digest(p) for p in staged_data.rglob('*') if p.is_file()}
            write_json(stage / 'plan.json', plan)
            os.replace(config.DATA_DIR, previous)
        if config.DATA_DIR.exists():
            if any(p.is_file() or p.is_symlink() for p in config.DATA_DIR.rglob('*')):
                raise ValueError('恢复目标出现新数据，已停止以保护现有内容')
            shutil.rmtree(config.DATA_DIR)
        os.replace(staged_data, config.DATA_DIR)
    report = config.DATA_DIR / 'restore-report.json'
    if not previous.is_dir() or not report.is_file() or json.loads(report.read_text())['id'] != token:
        raise ValueError('恢复未完成，原数据目录仍保留，请检查恢复记录')
    marker.unlink()
    config.reload()


def restore_status():
    report = config.DATA_DIR / 'restore-report.json'
    return {'pending': pending_path().exists(),
            'report': json.loads(report.read_text(encoding='utf-8')) if report.exists() else None}


@serialized
def cancel_restore():
    pending_path().unlink(missing_ok=True)
    return {'pending': False}
