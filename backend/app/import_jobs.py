"""持久化文档导入队列，单工作线程，按知识库隔离查看和重试。"""
import json
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from . import config


class ImportJobs:
    def __init__(self, database=None, process=None):
        self._lock = threading.RLock()
        self._running = False
        self._thread = None
        self._token = None
        self.error = ''
        self._process = process or self._ingest
        self._db = sqlite3.connect(database or config.DATA_DIR / 'import-jobs.sqlite3', check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.execute('CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY,kb_id TEXT,state TEXT,created REAL,updated REAL,items TEXT)')
        with self._db:
            for row in self._db.execute("SELECT * FROM jobs WHERE state IN ('queued','running','stopping')").fetchall():
                items = json.loads(row['items'])
                for item in items:
                    if item['status'] == 'running':
                        item.update(status='pending', stage='waiting')
                self._db.execute("UPDATE jobs SET state='interrupted',items=? WHERE id=?", (json.dumps(items), row['id']))

    def _ingest(self, item, kb_id, progress):
        from . import db, ingest
        path = Path(item['path'])
        if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to((config.UPLOAD_DIR / kb_id).resolve()):
            raise ValueError('待导入原文件不存在或已移动，请重新上传')
        if not db.get().execute('SELECT 1 FROM kbs WHERE id=?', (kb_id,)).fetchone():
            raise ValueError('知识库已不存在')
        return ingest.ingest(path, display_name=item['file'], keep_path=path, kb_id=kb_id, progress=progress)

    def _get(self, job_id, kb_id=None):
        row = self._db.execute('SELECT * FROM jobs WHERE id=?', (job_id,)).fetchone()
        if row is None or (kb_id is not None and row['kb_id'] != kb_id):
            raise ValueError('导入任务不存在')
        return {**dict(row), 'items': json.loads(row['items'])}

    def _save(self, job):
        job['updated'] = time.time()
        with self._db:
            self._db.execute('UPDATE jobs SET state=?,updated=?,items=? WHERE id=?',
                             (job['state'], job['updated'], json.dumps(job['items'], ensure_ascii=False), job['id']))

    def public(self, job):
        result = {k: v for k, v in job.items() if k != 'items'}
        result['items'] = [{k: v for k, v in item.items() if k != 'path'} for item in job['items']]
        result['done'] = sum(item['status'] in ('success', 'failed', 'duplicate') for item in job['items'])
        result['total'] = len(job['items'])
        result['error'] = self.error
        return result

    def list(self, kb_id):
        with self._lock:
            rows = self._db.execute('SELECT id FROM jobs WHERE kb_id=? ORDER BY created DESC LIMIT 20', (kb_id,)).fetchall()
            return [self.public(self._get(row['id'])) for row in rows]

    def active(self):
        with self._lock:
            return bool(self._db.execute("SELECT 1 FROM jobs WHERE state IN ('queued','running','stopping') LIMIT 1").fetchone())

    def create(self, kb_id, items):
        if not items:
            raise ValueError('请选择需要导入的文件')
        with self._lock:
            now = time.time()
            job = {'id': uuid.uuid4().hex, 'kb_id': kb_id, 'state': 'queued', 'created': now, 'updated': now,
                   'items': [{**item, 'status': 'pending', 'stage': 'waiting'} for item in items]}
            with self._db:
                self._db.execute('INSERT INTO jobs VALUES(?,?,?,?,?,?)', (job['id'], kb_id, job['state'], now, now, json.dumps(job['items'])))
            self._launch()
            return self.public(job)

    def control(self, job_id, kb_id, action):
        with self._lock:
            job = self._get(job_id, kb_id)
            if action == 'stop':
                if job['state'] == 'queued':
                    job['state'] = 'stopped'
                elif job['state'] == 'running':
                    job['state'] = 'stopping'
                self._save(job)
            elif action in ('resume', 'retry'):
                if job['state'] in ('queued', 'running', 'stopping'):
                    raise ValueError('任务正在处理中')
                wanted = ('failed',) if action == 'retry' else ('pending', 'running')
                items = [{k: item[k] for k in ('path', 'file')} for item in job['items'] if item['status'] in wanted]
                if not items:
                    raise ValueError('没有可重试或继续的文件')
                # 继续原任务，仅重新处理未完成项；失败重试创建新记录。
                if action == 'retry':
                    return self.create(kb_id, items)
                job['state'] = 'queued'
                for item in job['items']:
                    if item['status'] == 'running':
                        item.update(status='pending', stage='waiting')
                self._save(job)
                self._launch()
            else:
                raise ValueError('不支持的任务操作')
            return self.public(job)

    def _launch(self):
        if self._running:
            return
        self.error = ''
        self._running = True
        token = self._token = uuid.uuid4().hex
        self._thread = threading.Thread(target=self._run, args=(token,), daemon=True, name='memory-import')
        try:
            self._thread.start()
        except Exception:
            self._running = False
            with self._db:
                self._db.execute("UPDATE jobs SET state='interrupted' WHERE state='queued'")
            raise

    def _progress(self, job_id, index, stage):
        with self._lock:
            job = self._get(job_id)
            job['items'][index]['stage'] = stage
            self._save(job)

    def _run(self, token):
        try:
            while True:
                with self._lock:
                    row = self._db.execute("SELECT id FROM jobs WHERE state IN ('queued','running','stopping') ORDER BY created LIMIT 1").fetchone()
                    if row is None:
                        self._running = False
                        return
                    job = self._get(row['id'])
                    index = next((i for i, item in enumerate(job['items']) if item['status'] == 'pending'), None)
                    if index is None or job['state'] == 'stopping':
                        job['state'] = 'completed' if index is None else 'stopped'
                        self._save(job)
                        continue
                    job['state'] = 'running'
                    job['items'][index].update(status='running', stage='checking')
                    self._save(job)
                    item = job['items'][index].copy()
                try:
                    info = self._process(item, job['kb_id'], lambda stage: self._progress(job['id'], index, stage))
                    result = {'status': 'success', 'stage': 'done', 'title': info['title'], 'id': info['id'], 'msg': '已导入'}
                except Exception as exc:
                    duplicate = '已有此文档' in str(exc) or '文档已存在' in str(exc)
                    result = {'status': 'duplicate' if duplicate else 'failed', 'stage': 'done', 'msg': str(exc)}
                with self._lock:
                    job = self._get(job['id'])
                    job['items'][index].update(result)
                    self._save(job)
        except Exception as exc:
            with self._lock:
                self.error = f'导入任务记录异常，已停止：{exc}'
                try:
                    with self._db:
                        self._db.execute("UPDATE jobs SET state='interrupted' WHERE state IN ('queued','running','stopping')")
                except sqlite3.Error:
                    pass
        finally:
            with self._lock:
                if self._token == token:
                    self._running = False

    def close(self):
        if self._thread:
            self._thread.join(5)
        with self._lock:
            if self._running:
                raise RuntimeError('导入任务仍在运行')
            self._db.close()
