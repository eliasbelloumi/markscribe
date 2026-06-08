"""Core document-to-Markdown conversion."""

from pathlib import Path

from markitdown import MarkItDown

from .config import get_api_key

GEMINI_MODEL = "gemini-3.1-flash-lite"

OCR_PROMPT = (
    "Extract all content from this page as Markdown. "
    "Include text, tables, and describe diagrams/schemas "
    "preserving their logic and structure. "
    "For diagrams, use lists, arrows (→) or Markdown tables "
    "to represent relationships and flows."
)

SUPPORTED_EXTENSIONS = frozenset({
    "pdf", "docx", "pptx", "xlsx", "xls",
    "csv", "json", "xml", "html", "epub", "zip",
    "mp3", "wav", "jpg", "jpeg", "png", "gif", "webp",
})


def _get_client():
    key = get_api_key()
    if not key:
        return None
    from openai import OpenAI
    return OpenAI(
        api_key=key,
        base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
    )


def get_md(filepath: Path, ocr_mode: str = "auto") -> str:
    """Convert a single file to Markdown string."""
    client = _get_client()

    if client:
        md = MarkItDown(enable_plugins=True, llm_client=client, llm_model=GEMINI_MODEL)
    else:
        md = MarkItDown()

    ext = filepath.suffix.lower().lstrip(".")

    if ext == "pdf" and client and ocr_mode != "off":
        from .ocr import smart_ocr
        return smart_ocr(filepath, client, ocr_mode, GEMINI_MODEL, OCR_PROMPT)

    return md.convert(str(filepath)).text_content
