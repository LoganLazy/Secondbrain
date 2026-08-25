"""向量化提供方: 任意OpenAI兼容embeddings接口(智谱/硅基流动/Ollama...) / mock(离线测试)"""
import hashlib
import math
import os
import re

import httpx

from . import config


def _mock_embed(texts: list[str]) -> list[list[float]]:
    """确定性哈希词袋向量(256维), 仅用于无Key时的离线联调.
    中文按单字切分+相邻二字组词, 英文按单词."""
    dim = 256
    out = []
    for text in texts:
        vec = [0.0] * dim
        text = text.lower()
        toks = re.findall(r"[a-z0-9]+|[\u4e00-\u9fff]", text)
        cjk_runs = re.findall(r"[\u4e00-\u9fff]+", text)
        bigrams = []
        for run in cjk_runs:
            bigrams += [run[i:i + 2] for i in range(len(run) - 1)]
        for tok in toks + bigrams:
            h = int(hashlib.md5(tok.encode()).hexdigest(), 16)
            vec[h % dim] += 1.0 + (h % 7) / 10
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        out.append([v / norm for v in vec])
    return out


def embed(texts: list[str]) -> list[list[float]]:
    if config.get("EMBED_PROVIDER") == "mock" or config.get("NET_MODE") == "offline":
        return _mock_embed(texts)
    return _remote_embed(texts)


def _remote_embed(texts: list[str]) -> list[list[float]]:
    """调用 OpenAI 兼容 /embeddings 接口.
    通过环境变量切换供应商(注意: 切换后需重建知识库):
      智谱     EMBED_BASE_URL=https://open.bigmodel.cn/api/paas/v4  EMBED_MODEL=embedding-3
      硅基流动  EMBED_BASE_URL=https://api.siliconflow.cn/v1        EMBED_MODEL=BAAI/bge-m3 (免费)
      ollama   EMBED_BASE_URL=http://127.0.0.1:11434/v1             EMBED_MODEL=bge-m3
    """
    base = (os.environ.get("EMBED_BASE_URL") or config.get("EMBED_BASE_URL")).rstrip("/")
    key = os.environ.get("EMBED_KEY") or config.get("ZHIPU_KEY")
    model = os.environ.get("EMBED_MODEL", config.get("EMBED_MODEL"))
    headers = {"Authorization": f"Bearer {key}"}
    vectors: list[list[float]] = []
    # 分批请求(多数服务单次上限64条)
    for i in range(0, len(texts), 32):
        batch = texts[i:i + 32]
        r = httpx.post(
            f"{base.rstrip('/')}/embeddings",
            headers=headers,
            json={"model": model, "input": batch},
            timeout=60,
        )
        r.raise_for_status()
        data = sorted(r.json()["data"], key=lambda x: x["index"])
        vectors.extend(d["embedding"] for d in data)
    return vectors
