"""PDF -> text.

PyMuPDF handles born-digital PDFs, which is what the government portals serve. Older
judgments and most scanned question papers are images, so there is an OCR fallback.

OCR is opt-in per page, not per document: a paper can be half digital text and half a
scanned annexure, and running OCR over the whole file when 90% of it has a text layer
is slow for no gain.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import fitz  # PyMuPDF

# Below this many characters, a page is assumed to be a scan rather than text.
_OCR_THRESHOLD_CHARS = 40


@dataclass
class Page:
    number: int  # 1-indexed, matches what a reader sees
    text: str
    ocr: bool


@dataclass
class ExtractedDoc:
    path: Path
    pages: list[Page]

    @property
    def text(self) -> str:
        return "\n\n".join(p.text for p in self.pages)

    @property
    def ocr_pages(self) -> int:
        return sum(1 for p in self.pages if p.ocr)


def _configure_tesseract(pytesseract) -> None:
    """Point pytesseract at the binary.

    On Windows the installer drops tesseract.exe in Program Files and does not add it
    to PATH, so the default lookup fails even though OCR is installed. Honour an
    explicit setting first, then try the standard install locations.
    """
    from backend.app.config import settings

    if settings.tesseract_cmd:
        pytesseract.pytesseract.tesseract_cmd = settings.tesseract_cmd
        return
    for candidate in (
        r"C:\Program Files\Tesseract-OCR\tesseract.exe",
        r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
    ):
        if Path(candidate).exists():
            pytesseract.pytesseract.tesseract_cmd = candidate
            return


def _ocr_page(page: fitz.Page) -> str:
    try:
        import pytesseract
        from PIL import Image
    except ImportError:  # pragma: no cover - optional at runtime
        return ""

    _configure_tesseract(pytesseract)

    # 300 DPI is the usual sweet spot for legal text: enough for 8pt footnotes,
    # not so much that OCR crawls.
    pix = page.get_pixmap(dpi=300)
    img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    try:
        return pytesseract.image_to_string(img)
    except Exception:  # pragma: no cover - tesseract missing or failing
        return ""


def clean_text(text: str) -> str:
    """Normalise the whitespace damage typical of government PDFs."""
    # Join words broken across a line by a hyphen.
    text = re.sub(r"(\w)-\n(\w)", r"\1\2", text)
    # Collapse runs of spaces, but keep paragraph breaks meaningful.
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    # Strip page-number-only lines, which otherwise become their own chunks.
    text = re.sub(r"\n\s*\d{1,4}\s*\n", "\n", text)
    return text.strip()


def extract(path: Path, *, allow_ocr: bool = True) -> ExtractedDoc:
    pages: list[Page] = []
    with fitz.open(path) as doc:
        for index, page in enumerate(doc, start=1):
            raw = page.get_text("text") or ""
            used_ocr = False
            if allow_ocr and len(raw.strip()) < _OCR_THRESHOLD_CHARS:
                ocr_text = _ocr_page(page)
                if len(ocr_text.strip()) > len(raw.strip()):
                    raw = ocr_text
                    used_ocr = True
            pages.append(Page(number=index, text=clean_text(raw), ocr=used_ocr))
    return ExtractedDoc(path=path, pages=pages)
