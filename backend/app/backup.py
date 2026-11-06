"""Consistent, portable backups for Nebula Memory."""

import json
import shutil
import sqlite3
import tempfile
import time
import zipfile
import hashlib
from pathlib import Path

from . import config, db
from .lifecycle import serialized


def digest(path):
    value = hashlib.sha256()
    with open(path, 'rb') as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b''):
            value.update(chunk)
    return value.hexdigest()


def locate_original(value, file_hash=''):
    path = Path(value or '')
    def managed(candidate):
        return candidate.is_file() and any(candidate.resolve().is_relative_to(parent.resolve()) for parent in (config.UPLOAD_DIR, config.INBOX_DIR))
    if value and managed(path):
        return path
    # 兼容旧版收件夹导入后搬移原件、但未更新数据库路径的记录。
    archive = path.parent / '已导入'
    if file_hash and archive.is_dir():
        matches = [candidate for candidate in archive.iterdir()
                   if candidate.name.endswith('_' + path.name) and managed(candidate) and digest(candidate).startswith(file_hash)]
        if len(matches) == 1:
            return matches[0]
    return None


@serialized
def create_backup() -> Path:
    """Create a ZIP containing source data, metadata and settings.

    Chroma is intentionally omitted: vectors depend on the selected embedding
    model and can be rebuilt from the included originals. SQLite is copied via
    its backup API so the archive is consistent while the app is running.
    """
    stamp = time.strftime("%Y%m%d-%H%M%S")
    work = Path(tempfile.mkdtemp(prefix="nebula-memory-backup-"))
    root = work / "Nebula-Memory"
    root.mkdir()

    target_db = sqlite3.connect(root / "memory.db")
    try:
        db.get().backup(target_db)
    finally:
        target_db.close()

    if config.UPLOAD_DIR.exists():
        shutil.copytree(config.UPLOAD_DIR, root / "uploads", dirs_exist_ok=True)
    if config.SETTINGS_FILE.exists():
        shutil.copy2(config.SETTINGS_FILE, root / "settings.json")

    document_files = {}
    snapshot = sqlite3.connect(root / 'memory.db')
    snapshot.row_factory = sqlite3.Row
    columns = {r[1] for r in snapshot.execute('PRAGMA table_info(docs)')}
    missing = []
    if {'id', 'file_path', 'filename', 'file_hash'} <= columns:
        for row in snapshot.execute('SELECT id,filename,file_path,file_hash FROM docs'):
            if not row['file_path']:
                missing.append(row['filename'])
                continue
            source = locate_original(row['file_path'], row['file_hash'])
            if source is None:
                missing.append(row['filename'])
                continue
            relative = f'uploads/restored/{row["id"]}{source.suffix.lower()}'
            target = root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            document_files[str(row['id'])] = relative
    snapshot.close()

    manifest = {
        "product": "Nebula Memory",
        "format": 2,
        "created": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "contains_secrets": config.SETTINGS_FILE.exists(),
        "vectors_included": False,
        "document_files": document_files,
        "missing_originals": missing,
        "checksums": {p.relative_to(root).as_posix(): digest(p) for p in root.rglob('*') if p.is_file()},
        "restore_note": "恢复数据库和原始资料后，请在设置中重建向量索引。",
    }
    (root / "backup-manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    archive = work / f"Nebula-Memory-backup-{stamp}.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in root.rglob("*"):
            if path.is_file():
                zf.write(path, path.relative_to(work))
    return archive


def cleanup_backup(archive: Path) -> None:
    shutil.rmtree(archive.parent, ignore_errors=True)
