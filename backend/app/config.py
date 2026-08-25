"""配置管理: 默认值 < 环境变量(.env) < 界面设置(settings.json), 支持运行时热更新"""
import json
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
UPLOAD_DIR = DATA_DIR / "uploads"
INBOX_DIR = BASE_DIR.parent / "知识库文件夹"
SETTINGS_FILE = DATA_DIR / "settings.json"
for d in (DATA_DIR, UPLOAD_DIR, INBOX_DIR):
    d.mkdir(parents=True, exist_ok=True)

DEFAULTS = {
    # 对话模型(OpenAI兼容)
    "CHAT_BASE_URL": "https://api.deepseek.com",
    "CHAT_MODEL": "deepseek-chat",
    # 向量模型(OpenAI兼容embeddings)
    "EMBED_BASE_URL": "https://open.bigmodel.cn/api/paas/v4",
    "EMBED_MODEL": "embedding-3",
    "EMBED_PROVIDER": "zhipu",      # zhipu=远程 | mock=离线测试
    "NET_MODE": "auto",             # auto自动降级 | online强制在线 | offline强制离线
    "FC_INTERVALS": "0,1,2,4,7,15,30",
    "FC_MASTER_BOX": 4,
    # 检索参数
    "CHUNK_SIZE": 500,
    "CHUNK_OVERLAP": 80,
    "TOP_K": 5,
}
SECRET_KEYS = {"DEEPSEEK_KEY", "ZHIPU_KEY"}
# 键名 -> 说明(用于设置界面)
LABELS = {
    "CHAT_BASE_URL": "对话接口地址",
    "CHAT_MODEL": "对话模型名",
    "EMBED_BASE_URL": "向量化接口地址",
    "EMBED_MODEL": "向量化模型名",
}

SETTINGS: dict = {}


def _load_env_file() -> None:
    for env_path in (BASE_DIR / ".env", BASE_DIR.parent / ".env"):
        if not env_path.exists():
            continue
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


def reload() -> None:
    global SETTINGS
    s = dict(DEFAULTS)
    for k in list(DEFAULTS) + list(SECRET_KEYS):
        # 环境变量(.env) > 默认值
        if os.environ.get(k):
            s[k] = os.environ[k]
    for k in SECRET_KEYS:
        s.setdefault(k, "")
    # 界面设置 > 环境
    file_settings = {}
    if SETTINGS_FILE.exists():
        try:
            file_settings = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    for k, v in file_settings.items():
        if k in SECRET_KEYS:
            if v:
                os.environ[k] = v
                s[k] = v
        else:
            s[k] = v
    SETTINGS = s


def save(patch: dict) -> None:
    file_settings = {}
    if SETTINGS_FILE.exists():
        try:
            file_settings = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    for k, v in patch.items():
        if k in SECRET_KEYS:
            if v:  # 空值=不修改密钥
                file_settings[k] = v
                os.environ[k] = v
        elif k in DEFAULTS:
            file_settings[k] = v
    SETTINGS_FILE.write_text(
        json.dumps(file_settings, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    reload()


def get(key: str):
    return SETTINGS.get(key, DEFAULTS.get(key))


_load_env_file()
reload()
