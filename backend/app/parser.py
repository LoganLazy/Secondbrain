"""文档解析: PDF(带页码)/DOCX/TXT/MD -> 统一结构 + 滑窗切块"""
from pathlib import Path

from . import config, ocr

IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".webp", ".bmp")


def parse(path: Path) -> list[tuple[str, int]]:
    """返回 [(文本, 页码)]; 页码从1, 非PDF恒为1"""
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return _parse_pdf(path)
    if suffix in IMAGE_EXTS:
        return _parse_image(path)
    if suffix == ".docx":
        return _parse_docx(path)
    if suffix in (".txt", ".md", ""):
        text = path.read_text(encoding="utf-8", errors="ignore")
        # 支持重建文件里的分页标记 <!-- 第N页 -->
        if "<!-- 第" in text and "页 -->" in text:
            import re

            parts = re.split(r"<!--\s*第(\d+)页\s*-->", text)
            pages_out = []
            for i in range(1, len(parts), 2):
                body = parts[i + 1].strip() if i + 1 < len(parts) else ""
                if body:
                    pages_out.append((body, int(parts[i])))
            if pages_out:
                return pages_out
        return [(text, 1)]
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
        # 无文字层 => 扫描版, 走OCR(需安装可选依赖)
        if not ocr.available():
            raise ValueError(
                "这是扫描版PDF(没有文字层)。请先安装OCR支持: "
                "pip install -r requirements-ocr.txt")
        pages = ocr.ocr_pdf(path)
        if not pages:
            raise ValueError("扫描件OCR后仍未识别到文字, 可能是图片清晰度不足")
    return pages


def _parse_image(path: Path) -> list[tuple[str, int]]:
    if not ocr.available():
        raise ValueError(
            "识别图片需要安装OCR支持: pip install -r requirements-ocr.txt")
    text = ocr.ocr_image_file(path)
    if not text.strip():
        raise ValueError("图片中没有识别到文字")
    return [(text.strip(), 1)]


def _parse_docx(path: Path) -> list[tuple[str, int]]:
    import docx

    d = docx.Document(str(path))
    paras = [p.text.strip() for p in d.paragraphs if p.text.strip()]
    return [("\n".join(paras), 1)]


def chunk_text(pages: list[tuple[str, int]]) -> list[dict]:
    """逐页滑窗切块，不丢长行文字，也不跨页复用重叠内容。"""
    size, overlap = int(config.get("CHUNK_SIZE")), int(config.get("CHUNK_OVERLAP"))
    if size <= 0 or overlap < 0 or overlap >= size:
        raise ValueError("切块参数无效：需满足 CHUNK_SIZE > CHUNK_OVERLAP >= 0")
    chunks = []
    for text, page in pages:
        # 仅整理行间空白；每一页独立推进窗口，末尾短片段也不能丢失。
        text = " ".join(line.strip() for line in text.splitlines() if line.strip())
        start = 0
        while start < len(text):
            end = min(start + size, len(text))
            chunks.append({"text": text[start:end], "page": page})
            if end == len(text):
                break
            start = end - overlap
    return chunks
