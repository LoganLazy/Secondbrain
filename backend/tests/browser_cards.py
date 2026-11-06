"""临时知识库的出题、复习失败重试、重复提交和来源变更浏览器回归。"""
import json
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
    def chat(messages, **kwargs):
        content = messages[-1]['content']
        if 'model-fail' in content:
            raise OSError('secret-api-key')
        if 'slow-generation' in content and '生成最多' in content:
            (Path(os.environ['NEBULA_MEMORY_HOME']) / 'generation-started').touch()
            time.sleep(1)
        return json.dumps([{'q':f'第{i}题：alpha 是什么？','a':'alpha 是资料中的示例词。'} for i in range(12)])
    ingest.call_chat = chat
    import uvicorn
    uvicorn.Server(uvicorn.Config(app, log_level='error')).run(sockets=[sock])
    sys.exit()

from playwright.sync_api import sync_playwright, expect

with tempfile.TemporaryDirectory(prefix='memory-cards-browser-') as temporary:
    base = Path(temporary)
    with open(base / 'server.log', 'a') as log:
        process = subprocess.Popen([str(BACKEND / '.venv/bin/python'), str(Path(__file__)), '--serve'],
            cwd=BACKEND, stdout=subprocess.PIPE, stderr=log, text=True,
            env={**os.environ, 'NEBULA_MEMORY_HOME':str(base / 'backend'), 'NEBULA_DISABLE_INBOX':'1',
                 'NET_MODE':'offline', 'EMBED_PROVIDER':'mock', 'ANONYMIZED_TELEMETRY':'False'})
        try:
            port = int(process.stdout.readline())
            url = f'http://127.0.0.1:{port}'
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True, executable_path=os.environ.get('CHROMIUM_PATH'),
                                            args=['--no-sandbox', '--disable-gpu'])
                page = browser.new_page(viewport={'width':1450,'height':1000})
                errors, submissions = [], []
                page.on('pageerror', lambda error: errors.append(str(error)))
                page.on('request', lambda request: submissions.append(request.post_data_json) if request.url.endswith('/answer') else None)
                for _ in range(100):
                    try:
                        if page.request.get(url + '/api/health', timeout=1000).ok:
                            break
                    except Exception:
                        pass
                    time.sleep(.1)
                else:
                    raise RuntimeError((base / 'server.log').read_text()[-2000:])
                def upload(name, text, old_hash=None):
                    response = page.request.post(url + '/api/import/jobs', multipart={
                        'files':{'name':name,'mimeType':'text/plain','buffer':text.encode()}})
                    assert response.ok
                    for _ in range(200):
                        docs = page.request.get(url + '/api/docs').json()
                        doc = next((doc for doc in docs if doc['filename'] == name and doc['revision'] != old_hash), None)
                        if doc:
                            return doc
                        time.sleep(.1)
                    raise RuntimeError('import did not complete')
                manual = upload('manual.txt', 'alpha original source evidence for flashcards')
                slow = upload('slow.txt', 'slow-generation alpha source evidence for generation race')
                failed = upload('failed.txt', 'model-fail alpha document for error handling')
                page.goto(url)
                def cards_tab():
                    page.locator('.nav button').nth(3).click()
                    expect(page.get_by_label('出题资料', exact=True)).to_be_enabled()
                cards_tab()
                def generate(doc_id):
                    page.get_by_label('出题资料', exact=True).select_option(str(doc_id))
                    page.get_by_label('闪卡数量', exact=True).select_option('6')
                    page.locator('.gen-row button').click()
                generate(manual['id'])
                expect(page.locator('.gen .msg')).to_contain_text('新增了 6 张')
                expect(page.locator('.item')).to_have_count(6)
                expect(page.locator('.item .source-note').first).to_contain_text('资料版本')
                generate(manual['id'])
                expect(page.locator('.gen .msg')).to_contain_text('没有新增卡片')
                expect(page.locator('.item')).to_have_count(6)
                print('PASS 按请求数量生成并记录来源版本，同版本问题去重，不超量保存', flush=True)

                page.locator('.btn-review').click()
                expect(page.locator('.bigcard')).to_be_visible()
                question = page.locator('.q-side .text').inner_text()
                page.locator('.bigcard').click()
                def failed_submit(route):
                    route.fulfill(status=500, content_type='application/json', body='{"detail":"temporary failure"}')
                page.route('**/api/flashcards/*/answer', failed_submit)
                page.locator('.g.ok').click()
                expect(page.locator('.fc-error')).to_contain_text('提交未得到确认')
                expect(page.locator('.q-side .text')).to_have_text(question)
                expect(page.locator('.progress')).to_contain_text('成功提交 0 张')
                page.unroute('**/api/flashcards/*/answer', failed_submit)
                baseline = len(submissions)
                page.evaluate("() => { const button=document.querySelector('.g.ok'); button.click(); button.click(); }")
                expect(page.locator('.progress')).to_contain_text('成功提交 1 张')
                assert len(submissions) == baseline + 1
                saved = page.request.get(url + '/api/flashcards').json()
                reviewed = next(card for card in saved if card['reviews'] == 1)
                assert page.request.post(url + f'/api/flashcards/{reviewed["id"]}/answer', data={
                    'result':'correct','expected_reviews':0}).status == 409
                assert page.request.get(url + '/api/flashcards/stats').json()['reviews'] == 1
                for number in range(2, 7):
                    page.locator('.bigcard').click()
                    page.locator('.g.ok').click()
                    if number < 6:
                        expect(page.locator('.progress')).to_contain_text(f'成功提交 {number} 张')
                    else:
                        expect(page.locator('.review-message')).to_contain_text('成功提交 6 张')
                expect(page.locator('.review-message')).to_contain_text('成功提交 6 张')
                assert page.request.get(url + '/api/flashcards/stats').json()['reviews'] == 6
                print('PASS 提交失败不跳卡，重试成功才推进；双击及旧版本重放均不重复计次', flush=True)

                page.locator('.item .source-link').first.click()
                expect(page.locator('.reader .page-text')).to_contain_text('alpha original')
                cards_tab()
                generate(failed['id'])
                expect(page.locator('.gen .msg.bad')).to_contain_text('出题未完成')
                assert 'secret-api-key' not in page.locator('.fc').inner_text()
                assert len(page.request.get(url + '/api/flashcards').json()) == 6
                generate(slow['id'])
                for _ in range(100):
                    if (base / 'backend/generation-started').exists():
                        break
                    time.sleep(.01)
                assert (base / 'backend/generation-started').exists()
                assert page.request.delete(url + f'/api/docs/{slow["id"]}').ok
                expect(page.locator('.gen .msg.bad')).to_contain_text('更新或删除')
                assert len(page.request.get(url + '/api/flashcards').json()) == 6
                print('PASS 原文可打开，模型失败不泄露错误；出题途中删除资料不会生成孤儿卡', flush=True)

                upload('manual.txt', 'replacement alpha changed original source for new version', manual['revision'])
                page.locator('.nav button').first.click(); cards_tab()
                expect(page.locator('.source-note').first).to_contain_text('暂停复习')
                expect(page.locator('.btn-review')).to_be_disabled()
                expect(page.locator('.item')).to_have_count(6)
                stats = page.request.get(url + '/api/flashcards/stats').json()
                assert stats['paused'] == 6 and stats['reviews'] == 6 and stats['due'] == 0
                generate(manual['id'])
                expect(page.locator('.gen .msg')).to_contain_text('新增了 6 张')
                expect(page.locator('.item')).to_have_count(12)
                stats = page.request.get(url + '/api/flashcards/stats').json()
                assert stats['paused'] == 6 and stats['due'] == 6
                assert page.request.delete(url + f'/api/docs/{manual["id"]}').ok
                page.locator('.nav button').first.click(); cards_tab()
                expect(page.locator('.item')).to_have_count(12)
                expect(page.locator('.btn-review')).to_be_disabled()
                stats = page.request.get(url + '/api/flashcards/stats').json()
                assert stats['paused'] == 12 and stats['reviews'] == 6 and stats['due'] == 0
                print('PASS 来源更新/删除后保留卡片和复习记录并暂停旧卡，新版本可重新出题', flush=True)

                def failed_stats(route):
                    route.fulfill(status=500, content_type='application/json', body='{}')
                page.route('**/api/flashcards/stats', failed_stats)
                page.locator('.nav button').first.click()
                page.locator('.nav button').nth(3).click()
                expect(page.locator('.fc-error')).to_contain_text('加载失败')
                expect(page.locator('.btn-review')).to_be_disabled()
                page.unroute('**/api/flashcards/stats', failed_stats)
                page.locator('.fc-error button').click()
                expect(page.locator('.item')).to_have_count(12)
                assert page.request.post(url + '/api/flashcards/generate', data={'doc_id':failed['id'],'num':21}).status == 422
                assert page.request.post(url + f'/api/flashcards/{reviewed["id"]}/answer', data={'result':'correct'}).status == 422
                foreign = page.request.post(url + '/api/kbs', data={'name':'Other'}).json()['id']
                assert page.request.post(url + f'/api/flashcards/{reviewed["id"]}/answer', headers={'X-KB-ID':foreign}, data={'result':'correct','expected_reviews':1}).status == 404
                assert not errors, errors
                print('PASS 加载故障可恢复、参数和版本校验、跨知识库隔离，无前端脚本异常', flush=True)
                browser.close()
        finally:
            process.terminate(); process.wait(timeout=10)
