"""Input hardening helpers for local HTTP endpoints."""

import ipaddress
import re
import socket
from pathlib import Path
from urllib.parse import urlparse


MAX_UPLOAD_BYTES = 100 * 1024 * 1024


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
    """Reject local/private destinations before the web importer connects."""
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
