"""临时数据、模拟供应商的设置保存与故障保护浏览器回归。"""
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
    from app.main import app
    import httpx
    class Response:
        def raise_for_status(self):
            pass
        def json(self):
            return {'choices':[{'message':{'content':'ok'}}], 'data':[{'index':0, 'embedding':[.1,.2]}]}
    def post(*args, **kwargs):
        if kwargs.get('json', {}).get('model') == 'bad-model':
            raise OSError('test-secret-key-123456')
        return Response()
    httpx.post = post
    import uvicorn
    uvicorn.Server(uvicorn.Config(app, log_level='error')).run(sockets=[sock])
    sys.exit()

from playwright.sync_api import sync_playwright, expect

with tempfile.TemporaryDirectory(prefix='memory-settings-browser-') as temporary:
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
                page = browser.new_page(viewport={'width':1400,'height':1000})
                errors = []
                page.on('pageerror', lambda error: errors.append(str(error)))
                for _ in range(100):
                    try:
                        if page.request.get(url + '/api/health', timeout=1000).ok:
                            break
                    except Exception:
                        pass
                    time.sleep(.1)
                else:
                    raise RuntimeError((base / 'server.log').read_text()[-2000:])
                health = page.request.get(url + '/api/health').json()
                assert set(health) == {'product','status','instance'}
                page.goto(url)
                def settings():
                    page.locator('.nav button').nth(4).click()
                    expect(page.locator('.settings .save')).to_be_enabled()
                settings()
                expect(page.locator('input[type=radio][value=offline]')).to_be_checked()
                review = page.locator('.group').nth(3)
                review.locator('input').first.fill('0,2,4,7,14')
                review.locator('input').nth(1).fill('3')
                page.locator('.group').first.locator('input[type=password]').fill('test-secret-key-123456')
                page.locator('.save').click()
                expect(page.locator('.msg.ok')).to_be_visible()
                expect(page.locator('.group').first.locator('input[type=password]')).to_have_value('')
                saved = page.request.get(url + '/api/config').json()
                assert saved['NET_MODE'] == 'offline' and saved['FC_MASTER_BOX'] == 3
                assert saved['FC_INTERVALS'] == '0,2,4,7,14'
                assert saved['DEEPSEEK_KEY'] == {'set':True}
                assert 'test-secret-key' not in json.dumps(saved)
                page.reload(); settings()
                expect(page.locator('input[type=radio][value=offline]')).to_be_checked()
                expect(review.locator('input').first).to_have_value('0,2,4,7,14')
                expect(review.locator('input').nth(1)).to_have_value('3')
                print('PASS 离线和复习参数刷新后保持，数字类型正确，密钥只显示是否设置', flush=True)

                review.locator('input').nth(1).fill('20')
                page.locator('.save').click()
                expect(page.locator('.msg.bad')).to_contain_text('FC_MASTER_BOX')
                assert page.request.get(url + '/api/config').json()['FC_MASTER_BOX'] == 3
                review.locator('input').nth(1).fill('3')
                before = (base / 'backend/data/settings.json').read_bytes()
                page.locator('.group').first.locator('button.test').click()
                expect(page.locator('.msg.bad')).to_contain_text('离线模式')
                page.locator('input[type=radio][value=online]').check()
                page.locator('.group').first.locator('button.test').click()
                expect(page.locator('.msg.ok')).to_contain_text('连通')
                assert (base / 'backend/data/settings.json').read_bytes() == before
                page.locator('.group').first.locator('input').nth(1).fill('bad-model')
                page.locator('.group').first.locator('button.test').click()
                expect(page.locator('.msg.bad')).to_contain_text('连接失败')
                assert 'test-secret-key' not in page.locator('.msg.bad').inner_text()
                assert (base / 'backend/data/settings.json').read_bytes() == before
                print('PASS 无效配置不写入，离线阻止在线测试，草稿测试不保存且连接错误不泄露密钥', flush=True)

                def broken(route):
                    if route.request.method == 'GET':
                        route.fulfill(status=500, content_type='application/json', body='{}')
                    else:
                        route.continue_()
                page.route('**/api/config', broken)
                page.reload()
                page.locator('.nav button').nth(4).click()
                expect(page.locator('.settings [role=alert]')).to_contain_text('已禁用保存')
                expect(page.locator('.save')).to_be_disabled()
                page.unroute('**/api/config', broken)
                page.locator('.settings [role=alert] button').click()
                expect(page.locator('.save')).to_be_enabled()
                expect(page.locator('input[type=radio][value=offline]')).to_be_checked()
                print('PASS 配置读取失败时禁止覆盖保存，重新加载后恢复已保存设置', flush=True)

                for endpoint, data in [('/api/config', {'patch':{'NET_MODE':'online'}}),
                                       ('/api/config/test', {'patch':{'type':'chat'}}),
                                       ('/api/index/rebuild', {})]:
                    assert page.request.post(url + endpoint, data=data, headers={'Origin':'https://evil.test'}).status == 403
                assert page.request.post(url + '/api/config', data={'patch':{'CHAT_BASE_URL':'https://example.test?key=secret'}}).status == 400
                assert page.request.post(url + '/api/config', data={'patch':{'UNKNOWN':'value'}}).status == 400
                print('PASS 配置、连接测试与索引重建拒绝跨站写入，接口地址和未知配置校验生效', flush=True)

                def unavailable(route):
                    route.fulfill(status=503, content_type='application/json', body='{"status":"unavailable"}')
                page.route('**/api/health', unavailable)
                page.reload(); settings()
                expect(page.locator('.health-status')).to_contain_text('暂时无法连接')
                page.unroute('**/api/health', unavailable)
                assert not errors, errors
                print('PASS 健康检查失败有明确状态，无前端未处理异常', flush=True)
                browser.close()
        finally:
            process.terminate(); process.wait(timeout=10)
