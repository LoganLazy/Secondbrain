"""独立临时数据的资料编辑、搜索竞态、筛选分页浏览器回归。"""
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

if '--serve' in sys.argv:
    sock = socket.socket()
    sock.bind(('127.0.0.1', 0))
    print(sock.getsockname()[1], flush=True)
    from app.main import app, ingest
    original_embed = ingest.providers.embed
    def embed(texts):
        if any('slow' in text for text in texts):
            time.sleep(1)
        if any('broken' in text for text in texts):
            raise OSError('secret-api-key')
        return original_embed(texts)
    ingest.providers.embed = embed
    import uvicorn
    uvicorn.Server(uvicorn.Config(app, log_level='error')).run(sockets=[sock])
    sys.exit()

from playwright.sync_api import sync_playwright, expect

with tempfile.TemporaryDirectory(prefix='memory-library-browser-') as temp:
    base = Path(temp)
    with open(base / 'server.log', 'a') as log:
        process = subprocess.Popen(
            [str(BACKEND / '.venv/bin/python'), str(Path(__file__)), '--serve'],
            cwd=BACKEND, stdout=subprocess.PIPE, stderr=log, text=True,
            env={**os.environ, 'NEBULA_MEMORY_HOME':str(base / 'backend'),
                 'NEBULA_DISABLE_INBOX':'1', 'NET_MODE':'offline', 'EMBED_PROVIDER':'mock',
                 'ANONYMIZED_TELEMETRY':'False'})
        try:
            port = int(process.stdout.readline())
            url = f'http://127.0.0.1:{port}'
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True, executable_path=os.environ.get('CHROMIUM_PATH'),
                                            args=['--no-sandbox','--disable-gpu'])
                page = browser.new_page(viewport={'width':1500,'height':1000})
                page.on('dialog', lambda dialog: dialog.accept())
                errors, searches = [], []
                page.on('pageerror', lambda error: errors.append(str(error)))
                page.on('request', lambda request: searches.append(request.post_data) if request.url.endswith('/api/search/details') else None)
                for _ in range(100):
                    try:
                        if page.request.get(url + '/api/kbs', timeout=1000).ok:
                            break
                    except Exception:
                        pass
                    time.sleep(.1)
                else:
                    raise RuntimeError((base / 'server.log').read_text()[-2000:])
                for i in range(34):
                    response = page.request.post(url + '/api/import/jobs', multipart={
                        'files':{'name':f'doc-{i:02}.txt', 'mimeType':'text/plain',
                                 'buffer':f'alpha shared evidence unique marker{i:02} original document'.encode()}})
                    assert response.ok, response.text()
                for _ in range(200):
                    docs = page.request.get(url + '/api/docs').json()
                    if len(docs) == 34:
                        break
                    time.sleep(.1)
                assert len(docs) == 34
                first = next(doc for doc in docs if doc['filename'] == 'doc-00.txt')
                original = page.request.get(url + f'/api/docs/{first["id"]}/file').body()
                page.goto(url)
                page.locator('.nav button').nth(1).click()
                expect(page.locator('.doc')).to_have_count(30)
                page.locator('.pagination button').last.click()
                expect(page.locator('.doc')).to_have_count(4)
                page.get_by_label('筛选资料', exact=True).fill('doc-00')
                expect(page.locator('.doc')).to_have_count(1)
                page.locator('.edit').click()
                modal = page.get_by_role('dialog', name='编辑资料信息')
                modal.get_by_label('标题', exact=True).fill('Edited alpha')
                modal.get_by_label('分类', exact=True).fill('Work')
                modal.locator('input').nth(2).fill('#AI, ai, 知识')
                modal.get_by_role('button', name='保存', exact=True).click()
                expect(modal).to_have_count(0)
                expect(page.locator('.doc')).to_contain_text('Edited alpha')
                expect(page.locator('.doc .tag')).to_have_count(2)
                assert page.request.get(url + f'/api/docs/{first["id"]}/file').body() == original
                revised = next(doc for doc in page.request.get(url + '/api/docs').json() if doc['id'] == first['id'])
                assert revised['revision'] == first['revision'] and revised['chunks'] == first['chunks']
                page.get_by_role('button', name='重置筛选', exact=True).click()
                page.get_by_label('筛选分类', exact=True).select_option('Work')
                page.get_by_label('筛选标签', exact=True).select_option('AI')
                expect(page.locator('.doc')).to_have_count(1)
                page.locator('.doc').click()
                expect(page.locator('.reader .page-text')).to_contain_text('marker00')
                page.locator('.back').click()
                expect(page.get_by_label('筛选分类', exact=True)).to_have_value('Work')
                expect(page.locator('.doc')).to_have_count(1)
                print('PASS 元数据编辑、标签去重、筛选分页与阅读返回，原文和索引版本不变', flush=True)

                def denied(route):
                    route.fulfill(status=403, content_type='application/json', body='{"detail":"test denied"}')
                page.route('**/api/docs/' + str(first['id']), denied)
                page.locator('.edit').click()
                modal.get_by_label('标题', exact=True).fill('Keep unsaved draft')
                modal.get_by_role('button', name='保存', exact=True).click()
                expect(modal.locator('[role=alert]')).to_contain_text('保存失败')
                expect(modal.get_by_label('标题', exact=True)).to_have_value('Keep unsaved draft')
                page.unroute('**/api/docs/' + str(first['id']), denied)
                modal.get_by_role('button', name='取消', exact=True).click()
                print('PASS 保存失败时保留编辑内容，不关闭对话框', flush=True)

                def search(query, mode='keyword'):
                    page.get_by_label('检索模式', exact=True).select_option(mode)
                    page.get_by_label('全文搜索', exact=True).fill(query)
                    page.get_by_label('全文搜索', exact=True).press('Enter')
                search('marker00')
                expect(page.locator('.hits .hit')).to_have_count(1)
                expect(page.locator('.hit-head')).to_contain_text('Edited alpha')
                expect(page.locator('.hit-snippet mark')).to_have_text('marker00')
                count = len(searches)
                page.locator('.hit').click()
                expect(page.locator('.reader .page-text')).to_contain_text('marker00')
                page.locator('.back').click()
                expect(page.locator('.hits h4')).to_contain_text('marker00')
                assert len(searches) == count
                legacy = page.request.post(url + '/api/search', data={'query':'marker00','mode':'keyword'}).json()
                assert isinstance(legacy, list) and legacy[0]['title'] == 'Edited alpha'
                print('PASS 本地关键词搜索、命中片段高亮、来源阅读返回不重复查询，旧搜索接口兼容', flush=True)

                def failed(route):
                    route.fulfill(status=500, content_type='application/json', body='{"detail":"server unavailable"}')
                page.route('**/api/search/details', failed)
                search('failed request')
                expect(page.locator('.search-error')).to_contain_text('已有结果暂时保留')
                expect(page.locator('.hits h4')).to_contain_text('marker00')
                page.unroute('**/api/search/details', failed)
                page.get_by_label('全文搜索', exact=True).fill('marker01')
                page.locator('.search-error button').click()
                expect(page.locator('.hits h4')).to_contain_text('marker01')
                expect(page.locator('.search-error')).to_have_count(0)
                search('slow alpha', 'hybrid')
                expect(page.locator('.search-status')).to_be_visible()
                search('marker02')
                expect(page.locator('.hits h4')).to_contain_text('marker02')
                page.wait_for_timeout(1200)
                expect(page.locator('.hits h4')).to_contain_text('marker02')
                search('slow alpha', 'hybrid')
                expect(page.locator('.search-status')).to_be_visible()
                page.locator('.search-status button').click()
                page.wait_for_timeout(1200)
                expect(page.locator('.hits h4')).to_contain_text('marker02')
                page.get_by_label('全文搜索', exact=True).fill('')
                expect(page.locator('.hits')).to_have_count(0)
                print('PASS 搜索失败可重试并保留结果，快速连续搜索及取消后无旧结果覆盖', flush=True)

                search('broken alpha', 'hybrid')
                expect(page.locator('.search-warning')).to_contain_text('已降级为关键词检索')
                assert 'secret-api-key' not in page.locator('.lib').inner_text()
                search('broken alpha', 'keyword')
                expect(page.locator('.search-status')).to_have_count(0)
                expect(page.locator('.search-warning')).to_have_count(0)
                print('PASS 混合搜索异常显示降级提示，显式本地关键词不经过向量服务', flush=True)

                search('marker00')
                expect(page.locator('.hit')).to_have_count(1)
                page.locator('.hit').click()
                response = page.request.post(url + '/api/import/jobs', multipart={
                    'files':{'name':'doc-00.txt','mimeType':'text/plain','buffer':b'replacement unique freshmarker new original text'}})
                assert response.ok
                for _ in range(100):
                    latest = next(doc for doc in page.request.get(url + '/api/docs').json() if doc['id'] == first['id'])
                    if latest['revision'] != first['revision']:
                        break
                    time.sleep(.1)
                assert latest['revision'] != first['revision']
                page.locator('.back').click()
                expect(page.locator('.hit')).to_have_count(0)
                expect(page.locator('.search-warning')).to_contain_text('移除过期结果')
                print('PASS 同名资料更新后移除旧版本搜索片段，不展示过期缓存', flush=True)

                foreign = page.request.post(url + '/api/kbs', data={'name':'Other'}).json()['id']
                endpoint = url + f'/api/docs/{first["id"]}'
                assert page.request.patch(endpoint, data={'title':'forbidden'}, headers={'X-KB-ID':foreign}).status == 404
                assert page.request.patch(endpoint, data={'file_path':'/etc/passwd'}).status == 422
                assert page.request.patch(endpoint, data={'title':'  '}).status == 400
                assert page.request.patch(endpoint, data={'tags':['x'] * 21}).status == 422
                assert page.request.patch(endpoint, data={'title':'forbidden'}, headers={'Origin':'https://evil.test'}).status == 403
                assert page.request.post(url + '/api/search/details', data={'query':' ', 'mode':'keyword'}).status == 400
                assert page.request.post(url + '/api/search/details', data={'query':'alpha', 'mode':'invalid'}).status == 422
                assert not errors, errors
                print('PASS 编辑及搜索参数验证、知识库隔离、跨站保护，无前端脚本错误', flush=True)
                browser.close()
        finally:
            process.terminate()
            process.wait(timeout=10)
