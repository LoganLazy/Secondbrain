"""安全更新展示用元数据；不改原文、向量或文档身份。"""
import json
from . import db
from .lifecycle import serialized
from .restore import pending_path


def clean_text(value, limit, name, required=False):
    if not isinstance(value, str):
        raise ValueError(f'{name}必须是文字')
    value = value.strip()
    if len(value) > limit or (required and not value):
        raise ValueError(f'{name}不能为空或超过 {limit} 个字符' if required else f'{name}不能超过 {limit} 个字符')
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise ValueError(f'{name}不能包含控制字符')
    return value


@serialized
def update(doc_id, kb_id, changes):
    if pending_path().exists():
        raise BlockingIOError('已有等待重启的恢复任务，请先重启知识库服务')
    if not changes or set(changes) - {'title', 'category', 'tags'}:
        raise ValueError('只能更新标题、分类和标签，且至少提供一项')
    values = {}
    if 'title' in changes:
        values['title'] = clean_text(changes['title'], 160, '标题', True)
    if 'category' in changes:
        values['category'] = clean_text(changes['category'], 80, '分类')
    if 'tags' in changes:
        tags = changes['tags']
        if not isinstance(tags, list) or len(tags) > 20:
            raise ValueError('标签必须为列表，最多 20 项')
        unique, seen = [], set()
        for tag in tags:
            tag = clean_text(tag, 40, '标签').lstrip('#').strip()
            if tag and tag.casefold() not in seen:
                unique.append(tag)
                seen.add(tag.casefold())
        values['tags'] = json.dumps(unique, ensure_ascii=False)
    conn = db.get()
    if not conn.execute('SELECT 1 FROM docs WHERE id=? AND kb_id=?', (doc_id, kb_id)).fetchone():
        raise LookupError('文档不存在或不属于当前知识库')
    fields = ','.join(name + '=?' for name in values)
    conn.execute('UPDATE docs SET ' + fields + ' WHERE id=? AND kb_id=?',
                 (*values.values(), doc_id, kb_id))
    conn.commit()
    row = dict(conn.execute('SELECT id,title,category,tags FROM docs WHERE id=? AND kb_id=?',
                            (doc_id, kb_id)).fetchone())
    row['tags'] = json.loads(row['tags'])
    return row
