"""向量化提供方: 智谱embedding-3(云端) / mock(离线哈希向量, 测试用)"""
import hashlib
import math
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
        # 中文再加bigram提升区分度
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
    if config.EMBED_PROVIDER == "mock" or not config.ZHIPU_KEY:
        return _mock_embed(texts)
    return _zhipu_embed(texts)


def _zhipu_embed(texts: list[str]) -> list[list[float]]:
    url = "https://open.bigmodel.cn/api/paas/v4/embeddings"
    headers = {"Authorization": f"Bearer {config.ZHIPU_KEY}"}
    vectors: list[list[float]] = []
    # 智谱单次最多64条
    for i in range(0, len(texts), 64):
        batch = texts[i:i + 64]
        r = httpx.post(
            url,
            headers=headers,
            json={"model": config.ZHIPU_EMBED_MODEL, "input": batch},
            timeout=60,
        )
        r.raise_for_status()
        data = sorted(r.json()["data"], key=lambda x: x["index"])
        vectors.extend(d["embedding"] for d in data)
    return vectors
