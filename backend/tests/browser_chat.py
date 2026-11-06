"""独立临时知识库 + 离线向量 + 模拟 AI 的真实流式浏览器回归。"""
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
        if any('keywordonly' in text for text in texts):
            raise OSError('secret-api-key')
        return original_embed(texts)
    ingest.providers.embed = embed
    def chat_stream(messages, **kwargs):
        question = messages[-1]['content']
        if 'slow' in question:
            for _ in range(30):
                yield '慢速片段 '
                time.sleep(.1)
            return
        yield '测试'
        time.sleep(.1)
        if 'fail' in question:
            raise OSError('secret-api-key')
        yield '回答 [1]'
    ingest.call_chat_stream = chat_stream
    import uvicorn
    uvicorn.Server(uvicorn.Config(app, log_level='error')).run(sockets=[sock])
    sys.exit()

from playwright.sync_api import sync_playwright, expect

with tempfile.TemporaryDirectory(prefix='memory-chat-browser-') as temp:
    base = Path(temp)
    with open(base / 'server.log', 'a') as log:
        process = subprocess.Popen(
            [str(BACKEND / '.venv/bin/python'), str(Path(__file__)), '--serve'],
            cwd=BACKEND, stdout=subprocess.PIPE, stderr=log, text=True,
            env={**os.environ, 'NEBULA_MEMORY_HOME': str(base / 'backend'),
                 'NEBULA_DISABLE_INBOX': '1', 'NET_MODE': 'offline',
                 'EMBED_PROVIDER': 'mock', 'ANONYMIZED_TELEMETRY': 'False'})
        try:
            port = int(process.stdout.readline())
            url = f'http://127.0.0.1:{port}'
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True, executable_path=os.environ.get('CHROMIUM_PATH'),
                                            args=['--no-sandbox', '--disable-gpu'])
                page = browser.new_page(viewport={'width': 1380, 'height': 1000})
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
                response = page.request.post(url + '/api/import/jobs', multipart={
                    'files': {'name': 'manual.txt', 'mimeType': 'text/plain',
                              'buffer': b'alpha original reference evidence for browser regression'}})
                assert response.ok, response.text()
                for _ in range(100):
                    if page.request.get(url + '/api/docs').json():
                        break
                    time.sleep(.1)
                assert page.request.get(url + '/api/docs').json()
                page.goto(url)
                expect(page.locator('.inputbar input')).to_be_enabled()
                def send(question):
                    page.locator('.inputbar input').fill(question)
                    page.locator('.inputbar input').press('Enter')
                def finished():
                    expect(page.locator('.inputbar input')).to_be_enabled(timeout=10000)
                send('alpha')
                finished()
                expect(page.locator('.msg.assistant')).to_have_count(1)
                expect(page.locator('.msg.assistant .content')).to_have_text('测试回答 [1]')
                expect(page.locator('.chip')).to_contain_text('相关度')
                expect(page.locator('.chip')).to_be_enabled()
                page.locator('.cite-details summary').click()
                expect(page.locator('.cite-item')).to_contain_text('alpha original')
                page.reload()
                finished()
                expect(page.locator('.msg.assistant')).to_have_count(1)
                expect(page.locator('.chip')).to_be_enabled()
                assert 'NaN' not in page.locator('.messages').inner_text()
                page.locator('.cite-details summary').click()
                expect(page.locator('.cite-item')).to_contain_text('alpha original')
                page.locator('.chip').click()
                expect(page.locator('.reader .page-text')).to_contain_text('alpha original')
                page.locator('.nav button').first.click()
                finished()
                print('PASS 流式只有一个回答气泡，刷新保留完整引用，可打开原文', flush=True)

                send('alpha fail')
                finished()
                expect(page.locator('.msg.assistant')).to_have_count(2)
                latest = page.locator('.msg.assistant .content').last
                expect(latest).to_contain_text('不是 AI 生成的结论')
                assert 'secret-api-key' not in latest.inner_text()
                assert '测试' not in latest.inner_text()
                page.reload()
                finished()
                expect(page.locator('.msg.assistant .content').last).to_contain_text('原文摘录')
                print('PASS AI 中断后替换半截回答为明确标记的原文摘录，刷新一致且不泄露错误', flush=True)

                send('alpha keywordonly')
                finished()
                expect(page.locator('.msg.assistant .content').last).to_contain_text('已降级为关键词检索')
                expect(page.locator('.msg.assistant .chip').last).to_be_enabled()
                print('PASS 向量接口异常时关键词检索仍能回答且提示降级', flush=True)

                send('alpha slow')
                expect(page.locator('.stop-answer')).to_be_visible()
                expect(page.locator('.sess-bar select')).to_be_disabled()
                expect(page.locator('.sb-new')).to_be_disabled()
                page.locator('.stop-answer').click()
                finished()
                expect(page.locator('.msg.assistant .content').last).to_contain_text('已停止接收')
                expect(page.locator('.sess-bar select')).to_be_enabled()
                expect(page.locator('.msg.assistant')).to_have_count(4)
                print('PASS 停止接收立即恢复输入，会话操作在回答中锁定，不生成重复气泡', flush=True)

                def truncated(route):
                    route.fulfill(status=200, content_type='text/event-stream', body='data: {"type":"delta","text":"partial"}\n\n')
                page.route('**/api/chat/stream', truncated)
                send('alpha transport')
                finished()
                expect(page.locator('.msg.assistant .content').last).to_contain_text('回答可能不完整')
                page.unroute('**/api/chat/stream', truncated)
                assert not errors, errors
                print('PASS 未收到完成事件时提示回答不完整，无前端脚本异常', flush=True)
                browser.close()
        finally:
            process.terminate()
            process.wait(timeout=10)
