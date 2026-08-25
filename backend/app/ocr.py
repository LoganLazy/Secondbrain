"""OCR模块(可选): 未安装rapidocr时优雅降级"""
from pathlib import Path

_ocr = None
_available: bool | None = None


def available() -> bool:
    global _available
    if _available is None:
        try:
            import rapidocr_onnxruntime  # noqa
            _available = True
        except Exception:
            _available = False
    return _available


def _get():
    global _ocr
    if _ocr is None:
        from rapidocr_onnxruntime import RapidOCR
        _ocr = RapidOCR()
    return _ocr


def ocr_image_file(path: Path) -> str:
    """识别图片文件, 返回按行拼接的文本"""
    result, _ = _get()(str(path))
    if not result:
        return ""
    return "\n".join(line[1] for line in result)


def ocr_pdf(path: Path) -> list[tuple[str, int]]:
    """逐页渲染PDF为图片再OCR, 返回[(文本, 页码)]"""
    import pymupdf

    out = []
    with pymupdf.open(str(path)) as doc:
        for i, page in enumerate(doc):
            pix = page.get_pixmap(dpi=180)
            img_path = Path(path).with_suffix(f".ocr_tmp_{i}.png")
            pix.save(img_path)
            try:
                text = ocr_image_file(img_path)
            finally:
                img_path.unlink(missing_ok=True)
            if text.strip():
                out.append((text.strip(), i + 1))
    return out
