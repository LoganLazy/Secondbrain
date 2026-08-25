"""轻量BM25关键词检索, 与向量检索互补(精确命令/编号/专有名词场景)"""
import math
import re
from collections import Counter


def tokenize(text: str) -> list[str]:
    """中文按字+bigram, 英文按词(与mock分词策略一致)"""
    text = text.lower()
    toks = re.findall(r"[a-z0-9]+|[\u4e00-\u9fff]", text)
    for run in re.findall(r"[\u4e00-\u9fff]+", text):
        toks += [run[i:i + 2] for i in range(len(run) - 1)]
    return toks


class BM25Index:
    def __init__(self, k1: float = 1.5, b: float = 0.75):
        self.k1, self.b = k1, b
        self.docs: dict[str, dict] = {}   # cid -> {tf: Counter, len: int, meta}
        self.df: Counter = Counter()      # 词 -> 出现文档数
        self.total_len = 0

    def clear(self):
        self.docs.clear()
        self.df.clear()
        self.total_len = 0

    def add(self, cid: str, text: str, meta: dict):
        if cid in self.docs:
            self.remove(cid)
        toks = tokenize(text)
        tf = Counter(toks)
        self.docs[cid] = {"tf": tf, "len": len(toks), "meta": meta}
        self.total_len += len(toks)
        for w in tf:
            self.df[w] += 1

    def remove(self, cid: str):
        d = self.docs.pop(cid, None)
        if not d:
            return
        self.total_len -= d["len"]
        for w in d["tf"]:
            self.df[w] -= 1
            if self.df[w] <= 0:
                del self.df[w]

    @property
    def avgdl(self) -> float:
        return (self.total_len / len(self.docs)) if self.docs else 0.0

    def _score(self, query_toks: list[str], d: dict) -> float:
        score = 0.0
        dl = d["len"] or 1
        avgdl = self.avgdl or 1.0
        for w in query_toks:
            f = d["tf"].get(w, 0)
            if not f:
                continue
            n = len(self.docs)
            idf = math.log((n - self.df[w] + 0.5) / (self.df[w] + 0.5) + 1)
            score += idf * f * (self.k1 + 1) / (
                f + self.k1 * (1 - self.b + self.b * dl / avgdl)
            )
        return score

    def search(self, query: str, top_k: int = 20) -> list[tuple[str, float, dict]]:
        qtoks = tokenize(query)
        if not qtoks or not self.docs:
            return []
        scored = [(cid, self._score(qtoks, d), d["meta"])
                  for cid, d in self.docs.items()]
        scored = [x for x in scored if x[1] > 0]
        scored.sort(key=lambda x: -x[1])
        return [(cid, s, m) for cid, s, m in scored[:top_k]]


INDEX = BM25Index()
