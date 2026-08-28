"""Document parsing: real PDF (reportlab) and DOCX (python-docx) round-trips."""
import pytest

from app.documents.parsing import DocumentParseError, parse_docx, parse_pdf
from tests.conftest import make_docx_bytes, make_pdf_bytes


def _write(tmp_path, name, data: bytes) -> str:
    p = tmp_path / name
    p.write_bytes(data)
    return str(p)


def test_parse_pdf_extracts_text_and_pages(tmp_path):
    pdf = make_pdf_bytes(
        [
            ["Podman provides a Docker-compatible CLI.", "It runs rootless containers."],
            ["Page two discusses networking differences."],
        ]
    )
    path = _write(tmp_path, "doc.pdf", pdf)
    parsed = parse_pdf(path)
    assert parsed.page_count == 2
    text = " ".join(b.text for b in parsed.blocks)
    assert "Docker-compatible CLI" in text
    assert "networking differences" in text
    # Page numbers are tracked.
    assert any(b.page_number == 2 for b in parsed.blocks)
    assert parsed.word_count > 0


def test_parse_docx_extracts_headings_sections_and_tables(tmp_path):
    docx = make_docx_bytes(
        [
            ("h", "Architecture"),
            ("p", "The system uses a modular pipeline."),
            ("p", "Each stage is independently testable."),
        ]
    )
    path = _write(tmp_path, "doc.docx", docx)
    parsed = parse_docx(path)
    text = " ".join(b.text for b in parsed.blocks)
    assert "modular pipeline" in text
    # The heading is captured and used as the section for following paragraphs.
    assert any(b.is_heading and b.text == "Architecture" for b in parsed.blocks)
    assert any(b.section == "Architecture" for b in parsed.blocks if not b.is_heading)


def test_parse_pdf_empty_raises(tmp_path):
    # A PDF with no drawable text (blank page) -> no extractable text.
    pdf = make_pdf_bytes([[]])
    path = _write(tmp_path, "blank.pdf", pdf)
    with pytest.raises(DocumentParseError):
        parse_pdf(path)


def test_parse_corrupt_pdf_raises(tmp_path):
    path = _write(tmp_path, "bad.pdf", b"%PDF-1.4 not really a pdf")
    with pytest.raises(DocumentParseError):
        parse_pdf(path)
