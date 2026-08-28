import pytest

from app.export import ExportError, export_report

REPORT = """# Research Report: Test

## Executive Summary
This is a **bold** summary with detail.

## Technology / Solution Comparison

| Option | Offline | Pros |
|--------|---------|------|
| Qdrant | strong  | fast |
| Chroma | strong  | simple |

## Implementation Roadmap
1. **Spike** — try it
2. **Benchmark** — measure recall
"""


def test_markdown_export_is_verbatim():
    out = export_report(REPORT, title="Test", fmt="md")
    assert out.decode("utf-8") == REPORT


def test_html_export_is_standalone_and_has_table():
    out = export_report(REPORT, title="Test", fmt="html").decode("utf-8")
    assert out.lstrip().lower().startswith("<!doctype")
    assert "<table" in out
    assert "<title>Test</title>" in out


def test_pdf_export_has_pdf_magic():
    out = export_report(REPORT, title="Test", fmt="pdf")
    assert out[:4] == b"%PDF"
    assert len(out) > 500


def test_docx_export_is_zip_and_contains_content():
    import io
    import zipfile

    out = export_report(REPORT, title="Test", fmt="docx")
    assert out[:2] == b"PK"  # zip/docx signature
    with zipfile.ZipFile(io.BytesIO(out)) as zf:
        doc_xml = zf.read("word/document.xml").decode("utf-8")
    assert "Executive Summary" in doc_xml
    assert "Qdrant" in doc_xml  # table cell text made it in


def test_unknown_format_and_empty_content_raise():
    with pytest.raises(ExportError):
        export_report(REPORT, title="Test", fmt="rtf")
    with pytest.raises(ExportError):
        export_report("", title="Test", fmt="md")
