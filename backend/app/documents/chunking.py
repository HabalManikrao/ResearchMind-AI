"""Structure-aware chunking of a parsed document.

Groups blocks into chunks that respect heading and paragraph boundaries and a token
budget, with block-level overlap between size-forced chunks (headings start clean
section breaks). Every chunk keeps page/section/char-offset metadata so a retrieved
passage can be located in the original document. Deterministic — no LLM, no network.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.documents.parsing import ParsedBlock, ParsedDoc

_SEP = "\n\n"


@dataclass
class Chunk:
    chunk_index: int
    text: str
    page_number: int | None
    section: str | None
    char_start: int
    char_end: int
    token_count: int


def _tokens(text: str) -> int:
    # Whitespace word count — a stable, offline proxy for token budget.
    return max(1, len(text.split()))


def _full_text_and_spans(blocks: list[ParsedBlock]) -> tuple[str, list[tuple[int, int]]]:
    parts: list[str] = []
    spans: list[tuple[int, int]] = []
    pos = 0
    for i, b in enumerate(blocks):
        if i > 0:
            parts.append(_SEP)
            pos += len(_SEP)
        start = pos
        parts.append(b.text)
        pos += len(b.text)
        spans.append((start, pos))
    return "".join(parts), spans


def chunk_document(
    parsed: ParsedDoc, *, target_tokens: int = 350, overlap_tokens: int = 60
) -> list[Chunk]:
    blocks = parsed.blocks
    if not blocks:
        return []
    full_text, spans = _full_text_and_spans(blocks)

    groups: list[list[int]] = []
    cur: list[int] = []
    cur_tok = 0
    for i, b in enumerate(blocks):
        btok = _tokens(b.text)
        if b.is_heading and cur:
            # A heading opens a new section chunk (clean break, no overlap).
            groups.append(cur)
            cur, cur_tok = [], 0
        elif cur and cur_tok + btok > target_tokens:
            # Size-forced flush: carry the last block into the next chunk for overlap.
            groups.append(cur)
            prev_last = cur[-1]
            if overlap_tokens > 0 and _tokens(blocks[prev_last].text) < target_tokens:
                cur, cur_tok = [prev_last], _tokens(blocks[prev_last].text)
            else:
                cur, cur_tok = [], 0
        cur.append(i)
        cur_tok += btok
    if cur:
        groups.append(cur)

    chunks: list[Chunk] = []
    for idx, group in enumerate(groups):
        first, last = group[0], group[-1]
        char_start, char_end = spans[first][0], spans[last][1]
        text = full_text[char_start:char_end]
        # page = first block's page that has one; section = leading heading or its section.
        page_number = next((blocks[j].page_number for j in group if blocks[j].page_number), None)
        head = blocks[first]
        section = head.text if head.is_heading else head.section
        chunks.append(
            Chunk(
                chunk_index=idx,
                text=text,
                page_number=page_number,
                section=section,
                char_start=char_start,
                char_end=char_end,
                token_count=_tokens(text),
            )
        )
    return chunks
