"""Upload validation & filename safety (untrusted input)."""
import pytest

from app.documents.service import (
    DocumentValidationError,
    sanitize_filename,
    validate_upload,
)

PDF_HEAD = b"%PDF-1.7\n"
DOCX_HEAD = b"PK\x03\x04zipzip"


def test_valid_pdf_and_docx():
    assert validate_upload("report.pdf", 1000, PDF_HEAD) == "pdf"
    assert validate_upload("notes.docx", 1000, DOCX_HEAD) == "docx"


def test_rejects_unsupported_extension():
    with pytest.raises(DocumentValidationError) as e:
        validate_upload("evil.exe", 1000, b"MZ")
    assert e.value.status_code == 400


def test_rejects_mime_content_mismatch():
    # .pdf extension but not PDF bytes -> client-declared type is not trusted.
    with pytest.raises(DocumentValidationError):
        validate_upload("fake.pdf", 1000, DOCX_HEAD)


def test_rejects_empty_and_oversize():
    with pytest.raises(DocumentValidationError):
        validate_upload("a.pdf", 0, PDF_HEAD)
    with pytest.raises(DocumentValidationError) as e:
        validate_upload("a.pdf", 999 * 1024 * 1024, PDF_HEAD)
    assert e.value.status_code == 413


def test_sanitize_filename_strips_paths_and_traversal():
    assert sanitize_filename("../../etc/passwd") == "passwd"
    assert sanitize_filename("C:\\Windows\\evil.docx").endswith("evil.docx")
    assert sanitize_filename("../../../x.pdf") == "x.pdf"
    assert "/" not in sanitize_filename("a/b/c.pdf")
    assert sanitize_filename("") == "document"
