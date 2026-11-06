"""本机数据写入协调与服务实例锁。"""
from functools import wraps
import os
import threading
from . import config

MUTATION_LOCK = threading.RLock()
SERVICE_LEASE = None


def serialized(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        with MUTATION_LOCK:
            return function(*args, **kwargs)
    return wrapped


def acquire_service_lease():
    global SERVICE_LEASE
    if SERVICE_LEASE is not None:
        return
    config.BASE_DIR.mkdir(parents=True, exist_ok=True)
    lease = open(config.BASE_DIR / '.memory-server.lock', 'a+b')
    try:
        if os.name == 'nt':
            import msvcrt
            if lease.seek(0, 2) == 0:
                lease.write(b'0'); lease.flush()
            lease.seek(0)
            msvcrt.locking(lease.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(lease.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as exc:
        lease.close()
        raise RuntimeError('此知识库数据目录已有服务运行，请关闭重复实例') from exc
    SERVICE_LEASE = lease
