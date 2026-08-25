"""配置与密钥管理: 优先读环境变量, 其次 backend/.env"""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
UPLOAD_DIR = DATA_DIR / "uploads"
for d in (DATA_DIR, UPLOAD_DIR):
    d.mkdir(parents=True, exist_ok=True)


def _load_env_file() -> None:
    # 项目根 和 backend/ 都尝试加载
    for env_path in (BASE_DIR / ".env", BASE_DIR.parent / ".env"):
        if not env_path.exists():
            continue
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


_load_env_file()

# ---- 对话模型(OpenAI兼容) ----
CHAT_BASE_URL = os.environ.get("CHAT_BASE_URL", "https://api.deepseek.com")
CHAT_KEY = os.environ.get("DEEPSEEK_KEY", "")
CHAT_MODEL = os.environ.get("CHAT_MODEL", "deepseek-chat")

# ---- 向量模型(OpenAI兼容embeddings接口) ----
# provider: zhipu/任意兼容=云端 | mock=本地哈希向量(离线测试用)
EMBED_PROVIDER = os.environ.get("EMBED_PROVIDER", "zhipu")
ZHIPU_KEY = os.environ.get("ZHIPU_KEY", "")
EMBED_BASE_URL = os.environ.get("EMBED_BASE_URL", "https://open.bigmodel.cn/api/paas/v4")
ZHIPU_EMBED_MODEL = os.environ.get("EMBED_MODEL", os.environ.get("ZHIPU_EMBED_MODEL", "embedding-3"))

# ---- 检索参数 ----
CHUNK_SIZE = int(os.environ.get("CHUNK_SIZE", "500"))
CHUNK_OVERLAP = int(os.environ.get("CHUNK_OVERLAP", "80"))
TOP_K = int(os.environ.get("TOP_K", "5"))
