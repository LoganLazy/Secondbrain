"""Input hardening helpers for local HTTP endpoints."""

import ipaddress
import re
import shutil
import socket
from pathlib import Path
from urllib.parse import urlparse


MAX_UPLOAD_BYTES = 100 * 1024 * 1024


def kb_inbox_path(name: str, inbox_dir: Path) -> Path:
    """Resolve a knowledge-base's inbox folder.

    Refuses names that would resolve to inbox_dir itself or outside it
    (e.g. '.'/'..' or names smuggling in separators), so no caller can
    ever rmtree/mkdir outside the inbox.
    """
    root = inbox_dir.resolve()
    target = (inbox_dir / name).resolve()
    if target == root or not target.is_relative_to(root):
        raise ValueError("知识库名称无效")
    return target


def safe_rmtree(path: Path, root: Path) -> bool:
    """Remove a directory only if it lies strictly inside root.

    Returns True when something was removed. Anything resolving to root
    itself or outside it is refused (legacy rows with bad names included).
    """
    try:
        base = root.resolve()
        target = path.resolve()
    except (OSError, RuntimeError):
        return False
    if target == base or not target.is_relative_to(base):
        return False
    shutil.rmtree(target, ignore_errors=True)
    return True


def safe_upload_name(value: str | None) -> str:
    """Strip client-supplied paths/control chars and return a plain filename."""
    name = (value or "").replace("\\", "/")
    name = Path(name).name
    name = re.sub(r"[\x00-\x1f\x7f]", "", name).strip()
    if not name or name in {".", ".."}:
        raise ValueError("文件名无效")
    # Keep enough room for the hash prefix and common filesystem limits.
    if len(name.encode("utf-8")) > 200:
        suffix = Path(name).suffix[:20]
        stem = Path(name).stem
        while len((stem + suffix).encode("utf-8")) > 200:
            stem = stem[:-1]
        name = stem + suffix
    return name


def copy_limited(source, destination: Path, limit: int = MAX_UPLOAD_BYTES) -> int:
    """Copy a binary file object, removing partial output when it is too large."""
    written = 0
    try:
        with open(destination, "wb") as output:
            while True:
                chunk = source.read(1024 * 1024)
                if not chunk:
                    break
                written += len(chunk)
                if written > limit:
                    raise ValueError(f"文件不能超过 {limit // 1048576}MB")
                output.write(chunk)
    except Exception:
        destination.unlink(missing_ok=True)
        raise
    return written


def _public_ip(value: str) -> bool:
    try:
        return ipaddress.ip_address(value).is_global
    except ValueError:
        return False


def validate_public_url(url: str, resolver=socket.getaddrinfo) -> str:
    """Reject local/private destinations before the web importer connects.

    每次请求前都要重新调用: 校验只针对解析时刻的地址, httpx 连接时还会再
    解析一次 DNS, 两者之间仍有 DNS 重绑窗口(攻击方控制的域名可在两次解析
    之间把解析结果换成内网地址)。彻底消除需要传输层固定已校验的 IP
    (自定义 httpx transport), 在本机单用户场景下暂不实现; 调用方
    (_extract_web) 已做到每跳重定向都重新校验、校验后立即请求, 把窗口压到最小。
    """
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("只支持有效的 http/https 链接")
    if parsed.username or parsed.password:
        raise ValueError("链接不能包含用户名或密码")
    host = parsed.hostname.rstrip(".").lower()
    if host == "localhost" or host.endswith((".localhost", ".local", ".internal")):
        raise ValueError("为保护本机数据，不能导入本地或内网地址")
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None
    if literal is not None:
        if not literal.is_global:
            raise ValueError("为保护本机数据，不能导入本地或内网地址")
        return url
    try:
        addresses = {item[4][0] for item in resolver(host, parsed.port or 443)}
    except OSError as exc:
        raise ValueError(f"域名解析失败: {exc}") from exc
    if not addresses or any(not _public_ip(address) for address in addresses):
        raise ValueError("为保护本机数据，不能导入本地或内网地址")
    return url
