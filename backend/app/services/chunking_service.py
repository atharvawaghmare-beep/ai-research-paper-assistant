from __future__ import annotations

import re
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from statistics import median

import pymupdf

# Section headings we look for when deciding where to split a paper. Matched
# case-insensitively, optionally preceded by numbering ("1.", "II.", "3.2").
SECTION_HEADING_KEYWORDS = [
    "abstract",
    "introduction",
    "background",
    "related work",
    "motivation",
    "problem statement",
    "methodology",
    "methods",
    "materials and methods",
    "approach",
    "system design",
    "implementation",
    "experiments",
    "experimental setup",
    "experimental results",
    "results",
    "evaluation",
    "discussion",
    "analysis",
    "limitations",
    "conclusion",
    "conclusions",
    "future work",
    "acknowledgments",
    "acknowledgements",
    "references",
    "bibliography",
    "appendix",
]

_NUMBERING_PREFIX = r"(?:[IVXLC]+\.|\d+(?:\.\d+)*\.?|[A-Z]\.)?\s*"
_HEADING_RE = re.compile(
    rf"^\s*{_NUMBERING_PREFIX}(" + "|".join(re.escape(keyword) for keyword in SECTION_HEADING_KEYWORDS) + r")\s*:?\s*$",
    re.IGNORECASE,
)

# PyMuPDF span "flags" bit field; bit 4 (value 16) marks a bold span.
_BOLD_FLAG = 1 << 4
_MAX_HEADING_LINE_LENGTH = 60
_HEADING_SIZE_RATIO = 1.05  # heading font must be at least 5% larger than the body, or bold

PAGE_SEPARATOR = "\n\n"
DEFAULT_CHUNK_CHAR_TARGET = 1800  # ~400-450 tokens at ~4 chars/token
DEFAULT_CHUNK_CHAR_OVERLAP = 240  # ~60 tokens
MIN_CHUNK_CHARS = 200
_WHITESPACE_LOOKAHEAD = 50


@dataclass
class ChunkResult:
    chunk_index: int
    content: str
    character_start: int
    character_end: int
    page_start: int
    page_end: int
    token_count: int
    chunk_hash: str


def _page_line_spans(page: "pymupdf.Page") -> list[dict]:
    """Flatten a page's structured text into one entry per visual line, keeping
    the max font size and bold-ness needed for heading detection."""
    raw = page.get_text("dict")
    lines: list[dict] = []
    for block in raw.get("blocks", []):
        for line in block.get("lines", []):
            spans = line.get("spans", [])
            if not spans:
                continue
            text = "".join(span.get("text", "") for span in spans).strip()
            if not text:
                continue
            max_size = max(span.get("size", 0.0) for span in spans)
            is_bold = any(int(span.get("flags", 0)) & _BOLD_FLAG for span in spans)
            lines.append({"text": text, "size": max_size, "bold": is_bold})
    return lines


def _is_heading(line: dict, body_size: float) -> bool:
    text = line["text"].strip()
    if not text or len(text) > _MAX_HEADING_LINE_LENGTH:
        return False
    if not _HEADING_RE.match(text):
        return False
    return line["size"] >= body_size * _HEADING_SIZE_RATIO or line["bold"]


def _extract_pages_and_headings(pdf_path: Path) -> tuple[list[dict], list[tuple[int, str]]]:
    """Open the PDF once and return (pages, headings).

    pages: [{"page_number": int, "text": str}] — plain per-page text, same shape
    as paper_service.extract_pdf_page_text so chunk content matches what a user
    would see via the /extract endpoint.

    headings: [(page_number, heading_text)] — candidate section headings found
    via font-size/bold heuristics on that page.
    """
    document = pymupdf.open(pdf_path)
    pages: list[dict] = []
    page_lines: list[tuple[int, list[dict]]] = []
    all_sizes: list[float] = []
    try:
        for page in document:
            page_number = page.number + 1
            lines = _page_line_spans(page)
            page_lines.append((page_number, lines))
            all_sizes.extend(line["size"] for line in lines)
            pages.append({"page_number": page_number, "text": page.get_text("text").strip()})
    finally:
        document.close()

    body_size = median(all_sizes) if all_sizes else 10.0
    headings = [
        (page_number, line["text"].strip())
        for page_number, lines in page_lines
        for line in lines
        if _is_heading(line, body_size)
    ]
    return pages, headings


def _build_full_text(pages: list[dict]) -> tuple[str, list[tuple[int, int, int]]]:
    """Concatenate page texts into one string; return (full_text, page_offsets)
    where page_offsets is [(page_number, start, end)] in full_text coordinates."""
    parts: list[str] = []
    offsets: list[tuple[int, int, int]] = []
    cursor = 0
    for page in pages:
        text = page["text"]
        start = cursor
        parts.append(text)
        cursor += len(text)
        offsets.append((page["page_number"], start, cursor))
        parts.append(PAGE_SEPARATOR)
        cursor += len(PAGE_SEPARATOR)
    return "".join(parts), offsets


def _heading_offsets(
    headings: list[tuple[int, str]],
    pages: list[dict],
    page_offsets: list[tuple[int, int, int]],
) -> list[int]:
    """Map each detected heading back to a character offset in the full-text
    coordinate space, by locating the heading's text within its page's text."""
    page_text_by_number = {page["page_number"]: page["text"] for page in pages}
    page_start_by_number = {number: start for number, start, _ in page_offsets}

    offsets: list[int] = []
    for page_number, heading_text in headings:
        page_text = page_text_by_number.get(page_number, "")
        local_index = page_text.find(heading_text)
        if local_index == -1:
            # Whitespace/encoding mismatch between the structured and plain text
            # extraction for this line — skip rather than mis-split the document.
            continue
        offsets.append(page_start_by_number[page_number] + local_index)
    return sorted(set(offsets))


def _pages_for_range(start: int, end: int, page_offsets: list[tuple[int, int, int]]) -> tuple[int, int]:
    covering = [number for number, p_start, p_end in page_offsets if p_start < end and p_end > start]
    if not covering:
        covering = [page_offsets[0][0]] if page_offsets else [1]
    return min(covering), max(covering)


def _split_into_spans(full_text: str, start: int, end: int, target: int, overlap: int) -> list[tuple[int, int]]:
    """Fixed-size splitting with overlap over full_text[start:end], nudged to
    whitespace boundaries so chunks don't end mid-word."""
    spans: list[tuple[int, int]] = []
    pos = start
    while pos < end:
        span_end = min(pos + target, end)
        if span_end < end:
            # Bound the lookahead by the section end so we never bleed a chunk
            # into the next section while nudging off a mid-word cut.
            lookahead = full_text[span_end : min(span_end + _WHITESPACE_LOOKAHEAD, end)]
            whitespace_index = lookahead.find(" ")
            if whitespace_index != -1:
                span_end += whitespace_index
        spans.append((pos, span_end))
        if span_end >= end:
            break
        pos = max(span_end - overlap, pos + 1)  # always make forward progress

    # Fold a too-small trailing fragment into the previous span rather than
    # emitting a near-empty chunk.
    if len(spans) > 1 and (spans[-1][1] - spans[-1][0]) < MIN_CHUNK_CHARS:
        prev_start, _ = spans[-2]
        _, last_end = spans[-1]
        spans[-2] = (prev_start, last_end)
        spans.pop()

    return spans


def chunk_paper_text(
    pdf_path: Path,
    paper_id: int,
    target_chars: int = DEFAULT_CHUNK_CHAR_TARGET,
    overlap_chars: int = DEFAULT_CHUNK_CHAR_OVERLAP,
) -> tuple[list[ChunkResult], int]:
    """Chunk a PDF's text for storage as DocumentChunk rows.

    Section-aware: splits at detected section headings (Abstract, Introduction,
    Methods, Results, Conclusion, References, ...) found via PyMuPDF's
    structured text (font size + bold heuristics vs. the document's median body
    font size), then applies fixed-size chunking with overlap *within* each
    section so no single chunk spans unrelated sections.

    Falls back to a single fixed-size-with-overlap pass over the whole document
    when no headings are detected (e.g. a paper with no distinguishable heading
    styling, or a non-paper PDF).

    Returns (chunks, page_count).
    """
    pages, headings = _extract_pages_and_headings(pdf_path)
    full_text, page_offsets = _build_full_text(pages)
    doc_length = len(full_text)

    boundaries = _heading_offsets(headings, pages, page_offsets)
    section_starts = sorted({0, *[b for b in boundaries if 0 < b < doc_length]})
    section_bounds = [
        (section_starts[i], section_starts[i + 1] if i + 1 < len(section_starts) else doc_length)
        for i in range(len(section_starts))
    ]

    results: list[ChunkResult] = []
    chunk_index = 0
    for section_start, section_end in section_bounds:
        if section_end - section_start < 1:
            continue
        for span_start, span_end in _split_into_spans(full_text, section_start, section_end, target_chars, overlap_chars):
            raw_span = full_text[span_start:span_end]
            content = raw_span.strip()
            if not content:
                continue

            leading_offset = raw_span.find(content[0])
            tight_start = span_start + max(leading_offset, 0)
            tight_end = tight_start + len(content)

            page_start, page_end = _pages_for_range(tight_start, tight_end, page_offsets)
            results.append(
                ChunkResult(
                    chunk_index=chunk_index,
                    content=content,
                    character_start=tight_start,
                    character_end=tight_end,
                    page_start=page_start,
                    page_end=page_end,
                    token_count=len(content.split()),
                    # Namespaced by paper_id + chunk_index so identical text in two
                    # different papers (or two spots in the same paper) never
                    # collides with the global-unique chunk_hash column.
                    chunk_hash=sha256(f"{paper_id}:{chunk_index}:{content}".encode("utf-8")).hexdigest(),
                )
            )
            chunk_index += 1

    return results, len(pages)
