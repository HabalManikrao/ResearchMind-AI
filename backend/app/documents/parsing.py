"""Parse PDF (pypdf) and DOCX (python-docx) into a uniform block structure.

Text-based documents only — no OCR (out of scope). Extraction is deterministic and
offline. Publication dates come from document metadata, never from the upload time.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from pypdf import PdfReader
from pypdf.errors import PdfReadError


class DocumentParseError(RuntimeError):
    """Raised when a document cannot be parsed (corrupt, encrypted, empty, scanned)."""


@dataclass
class ParsedBlock:
    text: str
    page_number: int | None = None
    section: str | None = None
    is_heading: bool = False


@dataclass
class ParsedDoc:
    blocks: list[ParsedBlock] = field(default_factory=list)
    page_count: int = 0
    word_count: int = 0
    meta: dict = field(default_factory=dict)  # title, published_date, etc.


def _word_count(blocks: list[ParsedBlock]) -> int:
    return sum(len(b.text.split()) for b in blocks)


def _iso_date(value) -> str | None:
    """Best-effort ISO date string from a datetime/date/str metadata value."""
    if value is None:
        return None
    try:
        return value.date().isoformat()  # datetime
    except AttributeError:
        try:
            return value.isoformat()  # date
        except AttributeError:
            return str(value)[:10] or None


def parse_pdf(path: str) -> ParsedDoc:
    try:
        reader = PdfReader(path)
        if reader.is_encrypted:
            # Try an empty-password decrypt; real encryption raises.
            if reader.decrypt("") == 0:  # 0 = failed
                raise DocumentParseError("PDF is password-protected.")
        pages = reader.pages
    except DocumentParseError:
        raise
    except (PdfReadError, Exception) as exc:  # noqa: BLE001
        raise DocumentParseError(f"Could not read PDF: {exc}") from exc

    blocks: list[ParsedBlock] = []
    for pnum, page in enumerate(pages, start=1):
        try:
            text = page.extract_text() or ""
        except Exception:  # noqa: BLE001 - one bad page shouldn't kill the doc
            text = ""
        for para in _split_paragraphs(text):
            blocks.append(ParsedBlock(text=para, page_number=pnum))

    if not blocks:
        raise DocumentParseError(
            "No extractable text found (the PDF may be scanned images — OCR is not supported)."
        )

    meta: dict = {}
    try:
        info = reader.metadata
        if info:
            if info.title:
                meta["title"] = str(info.title)
            pub = _iso_date(info.creation_date) or _iso_date(info.modification_date)
            if pub:
                meta["published_date"] = pub
    except Exception:  # noqa: BLE001 - metadata is best-effort
        pass

    return ParsedDoc(
        blocks=blocks, page_count=len(pages), word_count=_word_count(blocks), meta=meta
    )


def parse_docx(path: str) -> ParsedDoc:
    try:
        from docx import Document as DocxDocument

        doc = DocxDocument(path)
    except Exception as exc:  # noqa: BLE001
        raise DocumentParseError(f"Could not read DOCX: {exc}") from exc

    blocks: list[ParsedBlock] = []
    current_section: str | None = None
    for para in doc.paragraphs:
        text = (para.text or "").strip()
        if not text:
            continue
        style = (para.style.name if para.style else "") or ""
        is_heading = style.lower().startswith("heading") or style.lower() == "title"
        if is_heading:
            current_section = text
        blocks.append(
            ParsedBlock(text=text, page_number=None, section=current_section, is_heading=is_heading)
        )

    # Tables: flatten each row to a line, grouped under the current section.
    for table in doc.tables:
        rows: list[str] = []
        for row in table.rows:
            cells = [c.text.strip() for c in row.cells]
            line = " | ".join(c for c in cells if c)
            if line:
                rows.append(line)
        if rows:
            blocks.append(
                ParsedBlock(text="\n".join(rows), page_number=None, section=current_section)
            )

    if not blocks:
        raise DocumentParseError("No extractable text found in the DOCX.")

    meta: dict = {}
    try:
        props = doc.core_properties
        if props.title:
            meta["title"] = str(props.title)
        pub = _iso_date(props.created) or _iso_date(props.modified)
        if pub:
            meta["published_date"] = pub
    except Exception:  # noqa: BLE001
        pass

    return ParsedDoc(blocks=blocks, page_count=0, word_count=_word_count(blocks), meta=meta)


def _split_paragraphs(text: str) -> list[str]:
    """Split a page's text into paragraph-ish blocks on blank lines, collapsing
    single newlines (PDF line wrapping) into spaces."""
    out: list[str] = []
    for chunk in text.replace("\r\n", "\n").split("\n\n"):
        collapsed = " ".join(line.strip() for line in chunk.split("\n") if line.strip())
        collapsed = collapsed.strip()
        if collapsed:
            out.append(collapsed)
    return out


def parse_document(path: str, ext: str) -> ParsedDoc:
    ext = ext.lower().lstrip(".")
    if ext == "pdf":
        return parse_pdf(path)
    if ext == "docx":
        return parse_docx(path)
    raise DocumentParseError(f"Unsupported document type: .{ext}")
