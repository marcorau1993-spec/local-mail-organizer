"""Local text extraction for mail attachments, with Qwen Vision OCR for images."""

from __future__ import annotations

import base64
import io
from pathlib import Path

import httpx
import pymupdf  # type: ignore[import-untyped]
from pypdf import PdfReader
from pypdf.errors import PdfReadError

TEXT_TYPES = {"text/plain", "text/csv", "application/json", "application/xml", "text/xml"}
IMAGE_TYPES = {"image/png", "image/jpeg", "image/webp", "image/gif", "image/tiff"}


def extract_attachment_text(
    content: bytes,
    filename: str,
    content_type: str,
    ollama_base_url: str,
    vision_model: str,
) -> tuple[str, str]:
    suffix = Path(filename).suffix.casefold()
    if content_type in TEXT_TYPES or suffix in {".txt", ".csv", ".json", ".xml", ".md"}:
        return content.decode("utf-8", errors="replace")[:200_000].strip(), "local_text"
    if content_type == "application/pdf" or suffix == ".pdf":
        try:
            reader = PdfReader(io.BytesIO(content))
            text = "\n\n".join(page.extract_text() or "" for page in reader.pages)[:200_000].strip()
        except PdfReadError:
            text = ""
        if text:
            return text, "pdf_text"
        document = pymupdf.open(stream=content, filetype="pdf")  # type: ignore[no-untyped-call]
        pages: list[str] = []
        for page in document[:5]:
            image = page.get_pixmap(
                matrix=pymupdf.Matrix(1.5, 1.5),  # type: ignore[no-untyped-call]
                alpha=False,
            ).tobytes(  # type: ignore[no-untyped-call]
                "png"
            )
            pages.append(_qwen_ocr(image, ollama_base_url, vision_model))
        return "\n\n".join(pages)[:200_000].strip(), "qwen_vision_pdf_ocr"
    if content_type in IMAGE_TYPES or suffix in {
        ".png",
        ".jpg",
        ".jpeg",
        ".webp",
        ".gif",
        ".tif",
        ".tiff",
    }:
        return _qwen_ocr(content, ollama_base_url, vision_model), "qwen_vision_ocr"
    return "", "unsupported"


def _qwen_ocr(content: bytes, ollama_base_url: str, vision_model: str) -> str:
    encoded = base64.b64encode(content).decode()
    response = httpx.post(
        f"{ollama_base_url.rstrip('/')}/api/chat",
        json={
            "model": vision_model,
            "stream": False,
            "messages": [
                {
                    "role": "user",
                    "content": "Transcribe all visible text exactly. Return text only. Do not infer missing text.",
                    "images": [encoded],
                }
            ],
            "options": {"temperature": 0},
        },
        timeout=180,
    )
    response.raise_for_status()
    return str(response.json().get("message", {}).get("content", ""))[:200_000].strip()
