"""独立数据目录、离线模型的真实浏览器与重启恢复验证。"""
import io
import json
import os
from pathlib import Path
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import zipfile

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

if '--serve' in sys.argv:
    sock = socket.socket()
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(('127.0.0.1', int(os.environ.get('MEMORY_TEST_PORT', '0'))))
    print(sock.getsockname()[1], flush=True)
    from app.main import app, ingest
    original_parse = ingest.parser.parse
    failures_seen = set()
    def parse(path):
        if 'slow' in path.name:
            time.sleep(1.5)
        if path.name.endswith('retry.txt') and path.name not in failures_seen:
            failures_seen.add(path.name)
            raise ValueError('模拟解析故障，可重试')
        if path.read_bytes().startswith(b'REJECT'):
            raise ValueError('模拟文档解析失败')
        return original_parse(path)
    ingest.parser.parse = parse
    import uvicorn
    uvicorn.Server(uvicorn.Config(app, log_level='error')).run(sockets=[sock])
    sys.exit()

from playwright.sync_api import sync_playwright

with tempfile.TemporaryDirectory(prefix='memory-browser-') as temp:
    base = Path(temp)
    home = base / 'backend'
    log = open(base / 'server.log', 'a')
    def start(port=0):
        process = subprocess.Popen([str(BACKEND / '.venv/bin/python'), str(Path(__file__)), '--serve'],
            cwd=BACKEND, stdout=subprocess.PIPE, stderr=log, text=True,
            env={**os.environ, 'NEBULA_MEMORY_HOME':str(home), 'NEBULA_DISABLE_INBOX':'1',
                 'NET_MODE':'offline', 'EMBED_PROVIDER':'mock', 'ANONYMIZED_TELEMETRY':'False', 'MEMORY_TEST_PORT':str(port)})
        server_port = int(process.stdout.readline().strip())
        return process, server_port
    process, port = start()
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, executable_path=os.environ.get('CHROMIUM_PATH'), args=['--no-sandbox','--disable-gpu'])
            page = browser.new_page(viewport={'width':1380,'height':1000})
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.on('dialog', lambda dialog: dialog.accept())
            url = f'http://127.0.0.1:{port}'
            def ready():
                for _ in range(100):
                    try:
                        response = page.request.get(url + '/api/kbs', timeout=1000)
                        if response.ok:
                            return
                    except Exception:
                        pass
                    time.sleep(.1)
                raise RuntimeError('temporary server failed to start: ' + (base / 'server.log').read_text()[-2000:])
            ready()
            page.goto(url)
            page.locator('.nav button').nth(1).click()
            upload = page.locator('.lib input[type=file]')
            upload.set_input_files([{'name':'slow.txt','mimeType':'text/plain','buffer':b'original alpha reference information'},
                                    {'name':'retry.txt','mimeType':'text/plain','buffer':b'beta retry reference information'}])
            page.wait_for_selector('.import-jobs')
            page.reload()
            page.locator('.nav button').nth(1).click()
            page.wait_for_function("() => document.querySelector('.import-jobs')?.textContent.includes('导入完成')")
            page.locator('.import-jobs summary').first.click()
            assert '模拟解析故障' in page.locator('.import-jobs').inner_text()
            print('PASS 后台导入与刷新恢复，失败可见', flush=True)
            page.get_by_role('button', name='重试失败文件').first.click()
            page.wait_for_function("() => document.querySelectorAll('.doc').length === 2")
            docs = page.request.get(url + '/api/docs').json()
            original = next(doc for doc in docs if doc['filename'] == 'slow.txt')
            upload.set_input_files({'name':'slow.txt','mimeType':'text/plain','buffer':b'REJECT replacement must not overwrite old original'})
            page.wait_for_function("() => document.querySelector('.import-jobs').textContent.includes('模拟文档解析失败')")
            source = page.request.get(url + f'/api/docs/{original["id"]}/file')
            assert source.body() == b'original alpha reference information'
            print('PASS 失败重试与同名导入失败保留旧原文', flush=True)
            # 同一任务中的未完成文件经过进程中断后不能自动恢复。
            upload.set_input_files([{'name':'slow-second.txt','mimeType':'text/plain','buffer':b'gamma second reference'},
                                    {'name':'slow-third.txt','mimeType':'text/plain','buffer':b'delta third reference'}])
            page.wait_for_function("() => document.querySelector('.import-jobs').textContent.includes('正在导入')")
            process.terminate(); process.wait(timeout=10)
            process, _ = start(port); ready()
            page.reload(); page.locator('.nav button').nth(1).click()
            page.wait_for_function("() => document.querySelector('.import-jobs')?.textContent.includes('服务中断')")
            page.get_by_role('button', name='继续未完成文件').first.click()
            page.wait_for_function("() => document.querySelectorAll('.doc').length === 4")
            print('PASS 服务重启后手动继续剩余文件', flush=True)
            page.locator('.nav button').nth(4).click()
            backup_file = base / 'backup.zip'
            with page.expect_download() as download:
                page.get_by_role('button', name='下载完整备份').click()
            download.value.save_as(backup_file)
            with zipfile.ZipFile(backup_file) as archive:
                manifest = json.loads(archive.read('Nebula-Memory/backup-manifest.json'))
                assert manifest['format'] == 2
                assert len(manifest['document_files']) == 4
            page.locator('.nav button').nth(1).click()
            page.locator('.lib input[type=file]').set_input_files({'name':'extra.txt','mimeType':'text/plain','buffer':b'epsilon extra after backup'})
            page.wait_for_function("() => document.querySelectorAll('.doc').length === 5")
            page.locator('.nav button').nth(4).click()
            page.locator('#restore-file').set_input_files(backup_file)
            page.wait_for_selector('#restore-preview')
            assert '文档 4' in page.locator('#restore-preview').inner_text()
            assert len(page.request.get(url + '/api/docs').json()) == 5
            page.locator('#confirm-restore').click()
            page.wait_for_function("() => document.querySelector('#restore-message').textContent.includes('准备就绪')")
            assert len(page.request.get(url + '/api/docs').json()) == 5
            print('PASS 完整备份预览与确认，重启前不替换资料', flush=True)
            process.terminate(); process.wait(timeout=10)
            process, _ = start(port); ready()
            page.reload(); page.locator('.nav button').nth(4).click()
            page.wait_for_function("() => document.querySelector('#restore-panel').textContent.includes('上次恢复时间')")
            assert len(page.request.get(url + '/api/docs').json()) == 4
            report = page.request.get(url + '/api/backup/restore-status').json()['report']
            previous = sqlite3.connect(Path(report['previous_data']) / 'memory.db')
            assert previous.execute('SELECT COUNT(*) FROM docs').fetchone()[0] == 5
            previous.close()
            assert page.request.get(url + f'/api/docs/{original["id"]}/file').body() == b'original alpha reference information'
            page.get_by_role('button', name='重建向量索引', exact=True).click()
            page.wait_for_function("() => document.querySelector('.settings').textContent.includes('重建完成')")
            hits = page.request.post(url + '/api/search', data={'query':'alpha'}).json()
            assert hits and any('alpha' in hit['text'] for hit in hits)
            print('PASS 重启恢复、保留原数据目录及重建后检索', flush=True)
            stream = io.BytesIO()
            with zipfile.ZipFile(stream, 'w') as archive:
                archive.writestr('Nebula-Memory/uploads/../../escape', 'invalid')
            page.locator('#restore-file').set_input_files({'name':'unsafe.zip','mimeType':'application/zip','buffer':stream.getvalue()})
            page.wait_for_function("() => document.querySelector('#restore-message').textContent.includes('不安全路径')")
            assert len(page.request.get(url + '/api/docs').json()) == 4
            assert page.request.get(url + '/api/import/jobs', headers={'x-kb-id':'missing'}).status == 404
            assert page.request.post(url + '/api/backup/restore-cancel', headers={'Origin':'https://evil.test'}).status == 403
            assert not errors, errors
            print('PASS 不安全备份拒绝、知识库隔离和跨站保护，无脚本错误', flush=True)
            browser.close()
    finally:
        process.terminate(); process.wait(timeout=10)
        log.close()
