"""配置校验与原子保存：默认值 < 环境变量 < settings.json。"""
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import threading
from urllib.parse import urlsplit

_home = os.environ.get("NEBULA_MEMORY_HOME") or os.environ.get("MEMORY_AI_HOME")
if _home:
    BASE_DIR = Path(_home)
elif getattr(sys, "frozen", False):
    BASE_DIR = Path(sys.executable).resolve().parent
else:
    BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
UPLOAD_DIR = DATA_DIR / "uploads"
INBOX_DIR = BASE_DIR.parent / "知识库文件夹"
SETTINGS_FILE = DATA_DIR / "settings.json"
for d in (DATA_DIR, UPLOAD_DIR, INBOX_DIR):
    d.mkdir(parents=True, exist_ok=True)

DEFAULTS = {
    "CHAT_BASE_URL": "https://api.deepseek.com",
    "CHAT_MODEL": "deepseek-chat",
    "EMBED_BASE_URL": "https://open.bigmodel.cn/api/paas/v4",
    "EMBED_MODEL": "embedding-3",
    "EMBED_PROVIDER": "zhipu",
    "NET_MODE": "auto",
    "FC_INTERVALS": "0,1,2,4,7,15,30",
    "FC_MASTER_BOX": 4,
    "CHUNK_SIZE": 500,
    "CHUNK_OVERLAP": 80,
    "TOP_K": 5,
}
SECRET_KEYS = {"DEEPSEEK_KEY", "ZHIPU_KEY"}
LABELS = {
    "CHAT_BASE_URL": "对话接口地址", "CHAT_MODEL": "对话模型名",
    "EMBED_BASE_URL": "向量化接口地址", "EMBED_MODEL": "向量模型名",
}
SETTINGS = {}
WARNINGS = []
_SETTINGS_LOCK = threading.RLock()
INTEGER_LIMITS = {
    "FC_MASTER_BOX": (1, 9), "CHUNK_SIZE": (64, 8000),
    "CHUNK_OVERLAP": (0, 2000), "TOP_K": (1, 30),
}


def _text(value, key, limit=200):
    if not isinstance(value, str):
        raise ValueError(f"{key} 必须为文字")
    value = value.strip()
    if len(value) > limit or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise ValueError(f"{key} 长度或字符无效")
    return value


def _value(key, value):
    if key in INTEGER_LIMITS:
        if type(value) is not int and not (isinstance(value, str) and re.fullmatch(r"\d+", value.strip())):
            raise ValueError(f"{key} 必须为整数")
        value = int(value)
        low, high = INTEGER_LIMITS[key]
        if not low <= value <= high:
            raise ValueError(f"{key} 必须在 {low}～{high} 之间")
        return value
    value = _text(value, key, 4096 if key in SECRET_KEYS else 500)
    if key in SECRET_KEYS:
        if any(c.isspace() for c in value):
            raise ValueError(f"{key} 不能包含空白字符")
        return value
    if not value:
        raise ValueError(f"{key} 不能为空")
    if key.endswith("BASE_URL"):
        try:
            parsed = urlsplit(value)
            valid_port = parsed.port is None or 1 <= parsed.port <= 65535
            if (parsed.scheme not in ("http", "https") or not parsed.hostname or not valid_port or
                    parsed.username is not None or parsed.password is not None or
                    parsed.query or parsed.fragment or any(c.isspace() for c in value)):
                raise ValueError()
        except ValueError:
            raise ValueError(f"{key} 必须为不含账号、查询参数和片段的 http/https 地址") from None
        return value.rstrip("/")
    if key == "NET_MODE" and value not in ("auto", "online", "offline"):
        raise ValueError("NET_MODE 必须为 auto、online 或 offline")
    if key == "FC_INTERVALS":
        parts = value.split(",")
        if not 2 <= len(parts) <= 20 or any(not re.fullmatch(r"\d+", p.strip()) for p in parts):
            raise ValueError("FC_INTERVALS 需要 2～20 个逗号分隔的非负整数")
        days = [int(p) for p in parts]
        if max(days) > 36500 or days != sorted(days):
            raise ValueError("复习间隔需递增或相等，且不超过 36500 天")
        return ",".join(map(str, days))
    return value


def _relations(values):
    if values["CHUNK_OVERLAP"] >= values["CHUNK_SIZE"]:
        raise ValueError("CHUNK_OVERLAP 必须小于 CHUNK_SIZE")
    if values["FC_MASTER_BOX"] >= len(values["FC_INTERVALS"].split(",")):
        raise ValueError("掌握等级必须小于复习间隔数量")


def validate_patch(patch, base=None):
    if not isinstance(patch, dict) or set(patch) - (set(DEFAULTS) | SECRET_KEYS):
        raise ValueError("配置项格式无效或包含未知配置项")
    clean = {key: _value(key, value) for key, value in patch.items()}
    effective = {**DEFAULTS, **(base if base is not None else SETTINGS), **clean}
    _relations(effective)
    return clean


def _read_file():
    if not SETTINGS_FILE.exists():
        return {}
    try:
        value = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ValueError()
        return value
    except (ValueError, OSError):
        raise ValueError("settings.json 无法读取或格式损坏；原文件未修改，请先备份并修复") from None


def _load_env_file():
    for path in (BASE_DIR / ".env", BASE_DIR.parent / ".env"):
        if path.exists():
            for line in path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    os.environ.setdefault(key.strip(), value.strip())


def reload():
    global SETTINGS, WARNINGS
    with _SETTINGS_LOCK:
        result = {**DEFAULTS, **{key: "" for key in SECRET_KEYS}}
        warnings = []
        try:
            file_settings = _read_file()
        except ValueError:
            file_settings = {}
            warnings.append("配置文件无法读取，已使用环境变量及默认值；原文件未修改。")
        for key in result:
            candidates = []
            if os.environ.get(key):
                candidates.append(os.environ[key])
            if key in file_settings and (key not in SECRET_KEYS or file_settings[key]):
                candidates.append(file_settings[key])
            for value in candidates:
                try:
                    result[key] = _value(key, value)
                except ValueError:
                    warnings.append(f"{key} 配置无效，已保留有效值或默认值。")
        if result["CHUNK_OVERLAP"] >= result["CHUNK_SIZE"]:
            for key in ("CHUNK_SIZE", "CHUNK_OVERLAP"):
                result[key] = DEFAULTS[key]
            warnings.append("切块参数组合无效，已使用默认值。")
        if result["FC_MASTER_BOX"] >= len(result["FC_INTERVALS"].split(",")):
            for key in ("FC_INTERVALS", "FC_MASTER_BOX"):
                result[key] = DEFAULTS[key]
            warnings.append("复习参数组合无效，已使用默认值。")
        if warnings:
            result['NET_MODE'] = 'offline'
            warnings.append('检测到无效配置，已安全切换离线模式；请检查原配置、修复并保存后再启用在线模式。')
        SETTINGS, WARNINGS = result, list(dict.fromkeys(warnings))


def save(patch):
    from .lifecycle import MUTATION_LOCK
    from .restore import pending_path
    with MUTATION_LOCK, _SETTINGS_LOCK:
        if pending_path().exists():
            raise BlockingIOError("已有等待重启的恢复任务，请先重启知识库服务")
        clean = validate_patch(patch)
        existing = _read_file()  # 损坏文件不能静默覆盖。
        clean = {key: value for key, value in clean.items() if key not in SECRET_KEYS or value}
        combined = {**existing, **clean}
        SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(prefix=".settings-", suffix=".tmp", dir=SETTINGS_FILE.parent)
        temporary = Path(name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as output:
                json.dump(combined, output, ensure_ascii=False, indent=2)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, SETTINGS_FILE)
        finally:
            temporary.unlink(missing_ok=True)
        reload()


def get(key):
    return SETTINGS.get(key, DEFAULTS.get(key))


_load_env_file()
reload()
