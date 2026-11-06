"""临时知识库、真实带空白页 PDF 与模拟 AI 的阅读器回归。"""
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
    import pymupdf
    with pymupdf.open() as pdf:
        for text in ['first page alpha original evidence', '',
                     'third page needle original evidence', 'fourth page needle original evidence']:
            page = pdf.new_page()
            if text:
                page.insert_text((72, 72), text)
        pdf.save(os.environ['MEMORY_READER_FIXTURE'])
    def chat(messages, **kwargs):
        if 'fail' in messages[-1]['content']:
            raise OSError('secret-api-key')
        return '核验回答 [1]'
    ingest.call_chat = chat
    import uvicorn
    uvicorn.Server(uvicorn.Config(app, log_level='error')).run(sockets=[sock])
    sys.exit()

from playwright.sync_api import sync_playwright, expect

with tempfile.TemporaryDirectory(prefix='memory-reader-browser-') as temp:
    base = Path(temp)
    with open(base / 'server.log', 'a') as log:
        process = subprocess.Popen(
            [str(BACKEND / '.venv/bin/python'), str(Path(__file__)), '--serve'],
            cwd=BACKEND, stdout=subprocess.PIPE, stderr=log, text=True,
            env={**os.environ, 'NEBULA_MEMORY_HOME': str(base / 'backend'),
                 'NEBULA_DISABLE_INBOX': '1', 'NET_MODE': 'offline', 'EMBED_PROVIDER': 'mock',
                 'MEMORY_READER_FIXTURE': str(base / 'fixture.pdf'), 'ANONYMIZED_TELEMETRY': 'False'})
        try:
            port = int(process.stdout.readline())
            url = f'http://127.0.0.1:{port}'
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True, executable_path=os.environ.get('CHROMIUM_PATH'),
                                            args=['--no-sandbox', '--disable-gpu'])
                page = browser.new_page(viewport={'width': 1500, 'height': 1000})
                errors = []
                page.on('pageerror', lambda error: errors.append(str(error)))
                for _ in range(100):
                    try:
                        if page.request.get(url + '/api/kbs', timeout=1000).ok:
                            break
                    except Exception:
                        pass
                    time.sleep(.1)
                else:
                    raise RuntimeError((base / 'server.log').read_text()[-2000:])
                def upload(name, content, mime='text/plain'):
                    response = page.request.post(url + '/api/import/jobs', multipart={
                        'files': {'name': name, 'mimeType': mime, 'buffer': content}})
                    assert response.ok, response.text()
                    for _ in range(100):
                        docs = page.request.get(url + '/api/docs').json()
                        found = next((doc for doc in docs if doc['filename'] == name), None)
                        if found:
                            return found
                        time.sleep(.1)
                    raise RuntimeError('import did not finish')
                pdf_doc = upload('reader.pdf', (base / 'fixture.pdf').read_bytes(), 'application/pdf')
                long_doc = upload('long.txt', ('<!-- 第5页 -->\n' + 'first section ' * 800 +
                                             '\n<!-- 第9页 -->\n' + 'last section ' * 800).encode())
                page.goto(url)
                page.locator('.nav button').nth(1).click()
                def open_pdf():
                    page.locator('.doc').filter(has_text='reader.pdf').click()
                    expect(page.locator('.reader .page-text')).to_be_visible()
                def jump(number):
                    page.locator('.jump').fill(str(number))
                    page.locator('.jump').press('Enter')
                def at(number):
                    expect(page.locator('.page-no')).to_have_text(str(number))
                open_pdf()
                at(1)
                page.locator('.pages').focus()
                page.locator('.pages').press('ArrowRight')
                at(3)
                page.locator('.ask-bar input').fill('editing text')
                page.locator('.ask-bar input').press('ArrowRight')
                at(3)
                jump(4)
                at(4)
                jump(2)
                at(4)
                expect(page.locator('.reader-notice')).to_contain_text('没有可读文字')
                jump(3)
                page.locator('.findbar input').fill('needle')
                expect(page.locator('.page-text mark.active')).to_have_text('needle')
                at(3)
                page.get_by_role('button', name='下一个匹配', exact=True).click()
                at(4)
                expect(page.locator('.page-text mark.active')).to_have_text('needle')
                page.get_by_role('button', name='上一个匹配', exact=True).click()
                at(3)
                page.locator('.findbar input').fill('[.*]')
                expect(page.locator('.page-text mark')).to_have_count(0)
                page.locator('.findbar input').fill('')
                print('PASS 空白页跳过与真实页码跳转，方向键只翻一页且不干扰输入，文内查找安全高亮', flush=True)

                page.locator('.back').click()
                open_pdf()
                at(3)
                page.reload()
                page.locator('.nav button').nth(1).click()
                open_pdf()
                at(3)
                page.locator('.back').click()
                page.locator('.search').fill('first page alpha')
                page.locator('.search').press('Enter')
                page.locator('.hit').filter(has_text='reader.pdf · 页1').click()
                at(1)
                print('PASS 本机阅读位置在重新打开及刷新后恢复，搜索引用页优先于旧进度', flush=True)

                page.get_by_role('button', name='原版', exact=True).click()
                page.wait_for_function("() => document.querySelector('.pdf-canvas')?.width > 0 && !document.querySelector('.rendering')")
                page.locator('.pages').focus()
                page.locator('.pages').press('ArrowRight')
                page.wait_for_function("() => !document.querySelector('.rendering')")
                expect(page.locator('.jump')).to_have_value('3')
                assert not page.locator('[role=alert]').count()
                page.get_by_role('button', name='文字', exact=True).click()
                at(3)
                print('PASS PDF 原件实际渲染并可跨空白页翻页、切回文字模式', flush=True)

                page.locator('.ask-bar input').fill('explain current page')
                page.locator('.ask-bar button').click()
                expect(page.locator('.ai-msgs .m.assistant .m-content').last).to_have_text('核验回答 [1]')
                expect(page.locator('.reader-source').last).to_contain_text('第3页')
                jump(4)
                page.locator('.reader-source').last.click()
                at(3)
                page.evaluate("""() => {
                    const range = document.createRange(); range.selectNodeContents(document.querySelector('.page-text'));
                    const selection = window.getSelection(); selection.removeAllRanges(); selection.addRange(range);
                }""")
                page.locator('.page').dispatch_event('mouseup')
                page.locator('.sel-float button').first.click()
                expect(page.locator('.ai-msgs .m.assistant')).to_have_count(2)
                page.locator('.ask-bar input').fill('fail')
                page.locator('.ask-bar button').click()
                expect(page.locator('.ai-msgs .m.assistant .m-content').last).to_contain_text('不是 AI 生成的结论')
                assert 'secret-api-key' not in page.locator('.ai-msgs').inner_text()
                print('PASS 页内问答、划词核验、来源跳转与 AI 失败的原文摘录降级', flush=True)

                payload = {'doc_id': pdf_doc['id'], 'question': 'explain', 'scope': 'page', 'page': 3}
                result = page.request.post(url + '/api/assist', data={**payload, 'passage': 'spoofed client text'}).json()
                assert result['sources'][0]['text'].startswith('third page')
                assert page.request.post(url + '/api/assist', data={**payload, 'scope':'selection', 'passage':'invented'}).status == 400
                assert page.request.post(url + '/api/assist', data={**payload, 'page':2}).status == 400
                assert page.request.post(url + '/api/assist', data={'question':'missing doc'}).status == 422
                foreign = page.request.post(url + '/api/kbs', data={'name':'Private'}).json()['id']
                assert page.request.post(url + '/api/assist', data=payload, headers={'X-KB-ID':foreign}).status == 404
                assert page.request.get(url + '/api/docs', headers={'X-KB-ID':'nonexistent'}).status == 404
                print('PASS 伪造段落、无效页码和跨知识库文档拒绝，失效知识库不回退默认库', flush=True)

                page.locator('.back').click()
                if page.locator('.hits').count():
                    page.locator('.hits .linkbtn').first.click()
                page.locator('.doc').filter(has_text='long.txt').click()
                at(5)
                jump(9)
                at(9)
                page.locator('.quick button').first.click()
                expect(page.locator('.scope-notice')).to_contain_text('不是完整全文')
                result = page.request.post(url + '/api/assist', data={
                    'doc_id':long_doc['id'], 'question':'summarize', 'scope':'document'}).json()
                assert result['used_chars'] == 12000 and result['truncated']
                assert result['total_chars'] > 12000
                print('PASS 长文摘要明确显示截断范围，非连续页码可正常跳转', flush=True)
                assert not errors, errors
                browser.close()
        finally:
            process.terminate()
            process.wait(timeout=10)
