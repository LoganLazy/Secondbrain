"""文档解析: PDF(带页码)/DOCX/TXT/MD -> 统一结构 + 滑窗切块"""
from pathlib import Path

from . import config


def parse(path: Path) -> list[tuple[str, int]]:
    """返回 [(文本, 页码)]; 页码从1, 非PDF恒为1"""
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return _parse_pdf(path)
    if suffix == ".docx":
        return _parse_docx(path)
    if suffix in (".txt", ".md", ""):
        return [(path.read_text(encoding="utf-8", errors="ignore"), 1)]
    raise ValueError(f"暂不支持的格式: {suffix}")


def _parse_pdf(path: Path) -> list[tuple[str, int]]:
    import pymupdf

    pages = []
    with pymupdf.open(path) as doc:
        for i, page in enumerate(doc):
            text = page.get_text("text").strip()
            if text:
                pages.append((text, i + 1))
    if not pages:
        raise ValueError("这个PDF没有可提取的文字(可能是扫描件), 暂不支持")
    return pages


def _parse_docx(path: Path) -> list[tuple[str, int]]:
    import docx

    d = docx.Document(str(path))
    paras = [p.text.strip() for p in d.paragraphs if p.text.strip()]
    return [("\n".join(paras), 1)]


def chunk_text(pages: list[tuple[str, int]]) -> list[dict]:
    """段落聚合+滑窗切块. 返回 [{text, page}]"""
    size, overlap = config.CHUNK_SIZE, config.CHUNK_OVERLAP
    chunks: list[dict] = []
    buf, buf_page = "", pages[0][1] if pages else 1

    def emit():
        nonlocal buf
        t = buf.strip()
        if len(t) >= 20:
            chunks.append({"text": t, "page": buf_page})
        # 留尾巴做重叠
        buf = t[-overlap:] if len(t) > overlap else ""

    for para, page in pages:
        for line in [p.strip() for p in para.split("\n") if p.strip()]:
            if page != buf_page:
                emit()
                buf_page = page
            while len(buf) + len(line) >= size:
                buf += " " + line[: size - len(buf)]
                emit()
                line = line[max(0, len(line) - overlap):]
                if not line:
                    break
            if line:
                buf += (" " if buf else "") + line
    emit()
    return chunks
