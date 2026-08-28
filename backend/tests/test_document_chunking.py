"""Structure-aware chunking: boundaries, metadata, determinism, overlap."""
from app.documents.chunking import chunk_document
from app.documents.parsing import ParsedBlock, ParsedDoc


def _doc(blocks: list[ParsedBlock]) -> ParsedDoc:
    return ParsedDoc(blocks=blocks, page_count=1, word_count=0, meta={})


def test_headings_start_new_chunks():
    blocks = [
        ParsedBlock("Intro", is_heading=True),
        ParsedBlock("The intro paragraph."),
        ParsedBlock("Details", is_heading=True),
        ParsedBlock("The details paragraph."),
    ]
    chunks = chunk_document(_doc(blocks), target_tokens=1000, overlap_tokens=0)
    assert len(chunks) == 2
    assert chunks[0].section == "Intro" and "intro paragraph" in chunks[0].text
    assert chunks[1].section == "Details" and "details paragraph" in chunks[1].text


def test_size_forces_split_with_metadata():
    words = " ".join(f"w{i}" for i in range(40))
    blocks = [
        ParsedBlock(words, page_number=1),
        ParsedBlock(words, page_number=1),
        ParsedBlock(words, page_number=2),
    ]
    chunks = chunk_document(_doc(blocks), target_tokens=50, overlap_tokens=0)
    assert len(chunks) >= 2
    # char offsets are consistent and within range.
    for c in chunks:
        assert 0 <= c.char_start < c.char_end
        assert c.token_count > 0
    assert any(c.page_number == 2 for c in chunks)


def test_overlap_shares_a_block_between_chunks():
    words = " ".join(f"w{i}" for i in range(40))
    blocks = [ParsedBlock(words), ParsedBlock(words), ParsedBlock(words)]
    no_overlap = chunk_document(_doc(blocks), target_tokens=50, overlap_tokens=0)
    with_overlap = chunk_document(_doc(blocks), target_tokens=50, overlap_tokens=20)
    # Overlap re-includes the boundary block, so total chunked tokens are higher.
    assert sum(c.token_count for c in with_overlap) >= sum(c.token_count for c in no_overlap)


def test_chunking_is_deterministic():
    blocks = [ParsedBlock(f"Paragraph number {i} with some text.") for i in range(10)]
    a = chunk_document(_doc(blocks), target_tokens=20, overlap_tokens=5)
    b = chunk_document(_doc(blocks), target_tokens=20, overlap_tokens=5)
    assert [(c.text, c.char_start, c.char_end) for c in a] == [
        (c.text, c.char_start, c.char_end) for c in b
    ]


def test_empty_document_yields_no_chunks():
    assert chunk_document(_doc([]), target_tokens=100) == []
