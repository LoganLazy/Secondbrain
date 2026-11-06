"""Linux 后台服务控制：核验 PID 出生时间、命令和目录后才允许停止。"""
import argparse
from contextlib import contextmanager
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
import uuid

BACKEND = Path(__file__).resolve().parent
PYTHON = BACKEND / '.venv/bin/python'
RUNTIME = Path(os.environ.get('NEBULA_MEMORY_HOME') or os.environ.get('MEMORY_AI_HOME') or BACKEND)
PID_FILE = RUNTIME / '.pid'


def command(port):
    return [str(PYTHON), '-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', str(port)]


def identity(pid, port):
    if type(pid) is not int or pid <= 1 or type(port) is not int or not 1 <= port <= 65535:
        return None
    try:
        proc = Path('/proc') / str(pid)
        fields = (proc / 'stat').read_text().rsplit(')', 1)[1].split()
        if fields[0] == 'Z':
            return None
        argv = (proc / 'cmdline').read_bytes().rstrip(b'\0').split(b'\0')
        if [os.fsdecode(arg) for arg in argv] != command(port) or (proc / 'cwd').resolve() != BACKEND:
            return None
        return fields[19]  # /proc/PID/stat 的第 22 项 starttime，不受 PID 复用影响。
    except (OSError, ValueError, IndexError):
        return None


def read_record():
    try:
        value = json.loads(PID_FILE.read_text())
        if (not isinstance(value, dict) or type(value.get('pid')) is not int or value['pid'] <= 1 or
                type(value.get('port')) is not int or not 1 <= value['port'] <= 65535 or
                not isinstance(value.get('born'), str) or not value['born'].isdigit() or
                not isinstance(value.get('instance'), str) or len(value['instance']) != 32):
            raise ValueError()
        return value
    except FileNotFoundError:
        return None
    except (OSError, ValueError):
        raise ValueError('PID 记录为旧格式或已损坏，拒绝据此停止进程；请先人工核对 .pid 和运行进程') from None


def same_process(record):
    return identity(record['pid'], record['port']) == record['born']


def open_pidfd(pid):
    if hasattr(os, 'pidfd_open'):
        return os.pidfd_open(pid, 0)
    # 本机便携 Python 未编入 pidfd 包装，但系统 C 库可能提供同一接口。
    import ctypes
    library = ctypes.CDLL(None, use_errno=True)
    function = getattr(library, 'pidfd_open', None)
    if function is None:
        raise ValueError('系统不支持 pidfd 安全停止，请人工核对；不会退回仅按 PID 停止')
    function.argtypes, function.restype = [ctypes.c_int, ctypes.c_uint], ctypes.c_int
    descriptor = function(pid, 0)
    if descriptor < 0:
        code = ctypes.get_errno()
        raise OSError(code, os.strerror(code))
    return descriptor


def send_pidfd(descriptor):
    if hasattr(signal, 'pidfd_send_signal'):
        signal.pidfd_send_signal(descriptor, signal.SIGTERM)
        return
    import ctypes
    library = ctypes.CDLL(None, use_errno=True)
    function = getattr(library, 'pidfd_send_signal', None)
    if function is None:
        raise ValueError('系统不支持 pidfd 安全停止，请人工核对；不会退回仅按 PID 停止')
    function.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_void_p, ctypes.c_uint]
    function.restype = ctypes.c_int
    if function(descriptor, signal.SIGTERM, None, 0) < 0:
        code = ctypes.get_errno()
        raise OSError(code, os.strerror(code))


def signal_verified(record):
    descriptor = open_pidfd(record['pid'])
    try:
        # 绑定到进程后再核验，避免核验与发信号之间的 PID 复用竞态。
        if not same_process(record):
            raise ValueError('PID 身份已变化，拒绝停止任何进程')
        send_pidfd(descriptor)
    finally:
        os.close(descriptor)


def healthy(record):
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(f'http://127.0.0.1:{record["port"]}/api/health', timeout=1) as response:
            result = json.loads(response.read(16384))
        return (result.get('product') == 'Nebula Memory' and result.get('status') == 'ok'
                and result.get('instance') == record['instance'])
    except (OSError, ValueError, AttributeError):
        return False


def write_record(record):
    fd, name = tempfile.mkstemp(prefix='.pid-', dir=RUNTIME)
    temporary = Path(name)
    try:
        with os.fdopen(fd, 'w') as output:
            json.dump(record, output)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, PID_FILE)
    finally:
        temporary.unlink(missing_ok=True)


@contextmanager
def control_lock():
    import fcntl
    RUNTIME.mkdir(parents=True, exist_ok=True)
    with open(RUNTIME / '.service-control.lock', 'a+b') as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        yield


def status():
    record = read_record()
    if not record or not same_process(record):
        return {'status':'stopped', 'message':'未发现可核验的本服务进程；不会向其他进程发信号'}
    return {'status':'running' if healthy(record) else 'starting_or_unhealthy',
            'pid':record['pid'], 'port':record['port']}


def start(port=8787, timeout=40):
    record = read_record()
    if record:
        if same_process(record):
            if healthy(record):
                return {'status':'running', 'pid':record['pid'], 'port':record['port'], 'message':'服务已在运行，无需重复启动'}
            raise ValueError('已发现本服务进程但健康检查尚未通过，请检查日志，不会重复启动')
        # 无法核验的旧记录不能覆盖；可能是 PID 复用或人为修改。
        raise ValueError('现有 PID 记录已失效或不匹配，请人工核对后移走 .pid；不会覆盖记录或停止任何进程')
    if not PYTHON.is_file():
        raise ValueError('未找到 backend/.venv/bin/python，请先安装项目依赖')
    try:
        with socket.create_connection(('127.0.0.1', port), timeout=.3):
            raise ValueError('指定端口已被占用，不会接管或停止占用端口的服务')
    except ConnectionRefusedError:
        pass
    token = uuid.uuid4().hex
    with open(RUNTIME / 'last-run.log', 'ab', buffering=0) as log:
        process = subprocess.Popen(command(port), cwd=BACKEND, stdin=subprocess.DEVNULL,
            stdout=log, stderr=subprocess.STDOUT, start_new_session=True,
            env={**os.environ, 'NEBULA_MEMORY_HOME':str(RUNTIME), 'NEBULA_MEMORY_INSTANCE_ID':token})
    record = None
    try:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise ValueError('后端启动失败，请检查 last-run.log；未报告为运行成功')
            born = identity(process.pid, port)
            if born and record is None:
                record = {'pid':process.pid, 'port':port, 'born':born, 'instance':token}
                write_record(record)
            if record and healthy(record):
                return {'status':'running', 'pid':process.pid, 'port':port, 'message':f'服务已就绪：http://127.0.0.1:{port}'}
            time.sleep(.1)
        raise ValueError('启动等待超时，请检查 last-run.log')
    except BaseException:
        # 只清理由本次启动创建的子进程，不扫描或停止其他占用端口的进程。
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                raise ValueError('本次启动的进程尚未退出，已保留 PID 记录，请人工检查') from None
        if record and not same_process(record):
            PID_FILE.unlink(missing_ok=True)
        raise


def stop(timeout=15):
    record = read_record()
    if not record:
        return {'status':'stopped', 'message':'没有后台服务记录'}
    if not same_process(record):
        raise ValueError('PID 身份不匹配或记录已失效，拒绝停止任何进程；请人工核对 .pid')
    signal_verified(record)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not same_process(record):
            PID_FILE.unlink(missing_ok=True)
            return {'status':'stopped', 'message':'本服务已停止'}
        time.sleep(.1)
    raise ValueError('进程尚未退出，未强制结束；请检查日志后重试')


def main(argv=None):
    parser = argparse.ArgumentParser(description='Nebula Memory Linux 后台服务控制')
    sub = parser.add_subparsers(dest='action', required=True)
    launch = sub.add_parser('start')
    launch.add_argument('--port', type=int, default=8787, choices=range(1, 65536), metavar='PORT')
    sub.add_parser('status')
    sub.add_parser('stop')
    args = parser.parse_args(argv)
    if not sys.platform.startswith('linux'):
        print('此后台控制器仅支持 Linux；其他平台请使用前台服务或桌面入口', file=sys.stderr)
        return 1
    try:
        with control_lock():
            result = start(args.port) if args.action == 'start' else stop() if args.action == 'stop' else status()
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except (ValueError, OSError) as exc:
        print(json.dumps({'status':'error', 'message':str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
