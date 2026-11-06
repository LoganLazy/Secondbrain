"""真实后台启动/停止测试：仅控制独立临时目录内由本脚本创建的服务。"""
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import urllib.request

BACKEND = Path(__file__).resolve().parents[1]
PYTHON = BACKEND / '.venv/bin/python'


def free_port():
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0))
        return listener.getsockname()[1]


with tempfile.TemporaryDirectory(prefix='memory-service-smoke-') as temporary:
    base = Path(temporary)
    runtime = base / 'backend'
    env = {**os.environ, 'NEBULA_MEMORY_HOME':str(runtime), 'NEBULA_DISABLE_INBOX':'1',
           'NET_MODE':'offline', 'EMBED_PROVIDER':'mock', 'ANONYMIZED_TELEMETRY':'False'}
    def command(*args, alternate=None):
        return subprocess.run([str(PYTHON), 'service_control.py', *args], cwd=BACKEND,
            env={**env, **({'NEBULA_MEMORY_HOME':str(alternate)} if alternate else {})},
            text=True, capture_output=True, timeout=55)
    record = None
    try:
        port = free_port()
        first = subprocess.run([str(PYTHON), 'start_daemon.py', '--port', str(port)],
            cwd=BACKEND, env=env, text=True, capture_output=True, timeout=55)
        assert first.returncode == 0, first.stderr
        launched = json.loads(first.stdout)
        assert launched['status'] == 'running'
        record = json.loads((runtime / '.pid').read_text())
        with urllib.request.urlopen(f'http://127.0.0.1:{port}/api/health', timeout=2) as response:
            health = json.load(response)
        assert health == {'product':'Nebula Memory', 'status':'ok', 'instance':record['instance']}
        status = command('status')
        assert status.returncode == 0 and json.loads(status.stdout)['status'] == 'running'
        second = command('start', '--port', str(port))
        assert second.returncode == 0 and json.loads(second.stdout)['pid'] == launched['pid']
        print('PASS 真实后台服务健康检查、状态查询与重复启动保护', flush=True)

        wrong = {**record, 'born':str(int(record['born']) + 1)}
        (runtime / '.pid').write_text(json.dumps(wrong))
        refused = command('stop')
        assert refused.returncode != 0 and '拒绝停止' in refused.stderr
        (runtime / '.pid').write_text(json.dumps(record))
        assert json.loads(command('status').stdout)['status'] == 'running'
        print('PASS 启动时间不匹配时拒绝停止，真实测试服务仍运行', flush=True)

        occupied_home = base / 'occupied'
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', 0))
            listener.listen(2)
            occupied = command('start', '--port', str(listener.getsockname()[1]), alternate=occupied_home)
            assert occupied.returncode != 0 and '端口已被占用' in occupied.stderr
            assert not (occupied_home / '.pid').exists()
        print('PASS 端口被其他服务占用时拒绝接管，不生成成功记录', flush=True)

        foreign_home = base / 'foreign'
        foreign_home.mkdir()
        helper = subprocess.Popen([str(PYTHON), '-c', 'import time; time.sleep(30)'])
        try:
            ticks = (Path('/proc') / str(helper.pid) / 'stat').read_text().rsplit(')', 1)[1].split()[19]
            (foreign_home / '.pid').write_text(json.dumps({**record, 'pid':helper.pid, 'born':ticks}))
            assert command('stop', alternate=foreign_home).returncode != 0
            assert helper.poll() is None
            (foreign_home / '.pid').write_text(str(helper.pid))
            assert command('stop', alternate=foreign_home).returncode != 0
            assert helper.poll() is None
        finally:
            helper.terminate()
            helper.wait(timeout=5)
        print('PASS 无关进程及旧版数字 PID 均不会被停止', flush=True)
    finally:
        if record:
            (runtime / '.pid').write_text(json.dumps(record))
            result = command('stop')
            assert result.returncode == 0, result.stderr
            assert json.loads(command('status').stdout)['status'] == 'stopped'
            print('PASS 已核验服务正常停止，测试未操作实际知识库或其他服务', flush=True)
