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


@dataclass
class OutlineSection:
    heading: str
    page_start: int
    page_end: int


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
            text = "".join(span.get("text", "") for span in spans).replace("\x00", "").strip()
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


# A broader heading predicate used only for the Phase 16 outline, not chunking:
# the fixed keyword list above is good enough to find chunk-split boundaries
# (missing a non-standard heading like "Model Architecture" just means that
# content stays folded into the preceding section's chunks, which is harmless
# for chunking) but not good enough for a real "Contents" view, which should
# show the paper's actual section titles. This accepts any visually-heading-
# shaped line, filtered to reject what's almost always *not* a section title:
# prose sentences, and figure/table/algorithm captions.
_OUTLINE_MIN_HEADING_LENGTH = 3
_OUTLINE_MAX_HEADING_LENGTH = 100
_SENTENCE_END_RE = re.compile(r"[a-z0-9][.!?]\s*$")
_STARTS_LOWERCASE_RE = re.compile(r"^[a-z]")
# A line that word-wraps mid-word ("the standard back-", "next embed-") is a
# PDF layout artifact of a justified paragraph, never a heading, however
# heading-sized its font happens to be — some templates set an opening
# "teaser" paragraph a point or two larger than body text, which otherwise
# passes the loose size-ratio check below and gets mistaken for a title.
_HYPHEN_WRAP_RE = re.compile(r"[a-z]-\s*$")
_CAPTION_LABEL_RE = re.compile(r"^(figure|table|algorithm|equation)\s*\d", re.IGNORECASE)
# A line that, once digits/whitespace/common math-and-table punctuation are
# stripped, has nothing left is a table value ("41.29", "3.3 x 10^18"), not a
# heading — table cells are frequently bold/large enough to pass the font check.
_PURE_NUMBER_OR_SYMBOL_RE = re.compile(r"^[\d\s.,·×x%±\-+]+$", re.IGNORECASE)
# A bare numbering fragment with no title text ("3.1", "5.2.1") — PyMuPDF's
# structured text sometimes splits a numbered heading's prefix onto its own
# visual line, ahead of the title text, which then correctly stands on its own.
_BARE_NUMBERING_RE = re.compile(r"^\d+(?:\.\d+)*\.?$")


def _looks_like_prose_or_caption(text: str) -> bool:
    if _CAPTION_LABEL_RE.match(text):
        return True
    if _PURE_NUMBER_OR_SYMBOL_RE.match(text):
        return True
    if _BARE_NUMBERING_RE.match(text):
        return True
    if text.endswith(":"):
        return True
    if _SENTENCE_END_RE.search(text):
        return True
    if _HYPHEN_WRAP_RE.search(text):
        return True
    if _STARTS_LOWERCASE_RE.match(text):
        return True
    # A section title is almost always short and never contains a comma (a
    # copyright footer or author/affiliation block mis-styled as heading-sized
    # text reliably does) — real headings in testing never tripped either of
    # these, so they're safe to use as a hard cutoff rather than a soft signal.
    # 8 was too tight: a real section title like "The challenges of a
    # principled approach to AI Ethics" (9 words) was being dropped as
    # "prose", which silently orphaned its own numbered subsections (no
    # parent heading left to fold their pages into) and corrupted the whole
    # outline downstream. 12 still rejects genuine prose/reference lines
    # (checked against real paper text — the only false positives it adds
    # are numbered recommendation-list items that were already getting
    # through at shorter lengths via the same bold+numbered pattern; it
    # doesn't let through anything resembling an actual sentence).
    word_count = len(text.split())
    return word_count > 12 or "," in text


def _is_outline_heading(line: dict, body_size: float) -> bool:
    text = line["text"].strip()
    if not (_OUTLINE_MIN_HEADING_LENGTH <= len(text) <= _OUTLINE_MAX_HEADING_LENGTH):
        return False
    if not (line["size"] >= body_size * _HEADING_SIZE_RATIO or line["bold"]):
        return False
    return not _looks_like_prose_or_caption(text)


def _extract_pages_and_headings(
    pdf_path: Path,
    heading_predicate=_is_heading,
) -> tuple[list[dict], list[tuple[int, str]]]:
    """Open the PDF once and return (pages, headings).

    pages: [{"page_number": int, "text": str}] — plain per-page text, same shape
    as paper_service.extract_pdf_page_text so chunk content matches what a user
    would see via the /extract endpoint.

    headings: [(page_number, heading_text)] — candidate section headings found
    via font-size/bold heuristics on that page, judged by `heading_predicate`
    (defaults to the keyword-restricted detector chunking uses; the Phase 16
    outline passes the broader `_is_outline_heading` instead).
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
            # Strip NUL (0x00) characters PyMuPDF emits for some embedded fonts —
            # Postgres TEXT columns reject them and the whole chunk insert fails.
            pages.append({"page_number": page_number, "text": page.get_text("text").replace("\x00", "").strip()})
    finally:
        document.close()

    body_size = median(all_sizes) if all_sizes else 10.0
    headings = [
        (page_number, line["text"].strip())
        for page_number, lines in page_lines
        for line in lines
        if heading_predicate(line, body_size)
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


_BARE_NUMBERING_CAPTURE_RE = re.compile(r"^(\d+(?:\.\d+)*)\.?$")
_INLINE_NUMBERING_CAPTURE_RE = re.compile(r"^(\d+(?:\.\d+)*)\.?\s+(?=\S)")


def _numbering_depth(numbering: str | None) -> int:
    return numbering.count(".") + 1 if numbering else 1


def extract_outline_and_pages(pdf_path: Path) -> tuple[list[OutlineSection], list[dict]]:
    """Returns (outline, pages) for the "Contents" view (Phase 16): the same
    low-level section detection chunk_paper_text() uses, reshaped into
    human-readable top-level sections with page ranges — "Introduction",
    "Method", "Experiments", not every numbered subsection underneath them.
    `pages` is returned alongside so callers that also need per-page text
    (e.g. scanning for equation candidates) don't open and parse the PDF a
    second time.

    A real paper's subsections ("3.1 Encoder and Decoder Stacks", "3.2.1
    Scaled Dot-Product Attention") pass the exact same visual-heading test as
    their parent ("3 Model Architecture") — font size/boldness alone doesn't
    reliably separate heading levels in most templates. Numbering depth does:
    PyMuPDF's structured text often splits a numbered heading's "3.1" onto its
    own line ahead of the title, so that's captured and attached to the next
    heading-shaped line, and only depth-1 numbering (or an unnumbered keyword
    match like Abstract/Conclusion/References, which is always top-level)
    makes it into the outline. A subsection's content isn't lost — it's just
    folded into its parent section's (now wider) page range, same as "Model
    Architecture" naturally absorbing pages that used to be split out as
    "Encoder and Decoder Stacks", "Attention", etc.

    Falls back to a single "Full text" section spanning the whole document when
    no headings are detected, rather than inventing section names.
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
            pages.append({"page_number": page_number, "text": page.get_text("text").replace("\x00", "").strip()})
    finally:
        document.close()

    if not pages:
        return [], []

    body_size = median(all_sizes) if all_sizes else 10.0

    # Collect heading candidates together with any numbering found for them —
    # either inline ("3.1 Encoder and Decoder Stacks" as one line) or from a
    # standalone numbering-only line immediately before the title line.
    candidates: list[tuple[int, str, bool]] = []  # (page_number, text, is_top_level)
    current_numbered_depth = 0  # 0 = no numbering scheme seen yet anywhere
    for page_number, lines in page_lines:
        pending_numbering: str | None = None
        for line in lines:
            text = line["text"].strip()
            bare_match = _BARE_NUMBERING_CAPTURE_RE.match(text)
            if bare_match:
                pending_numbering = bare_match.group(1)
                continue
            if _is_outline_heading(line, body_size):
                inline_match = _INLINE_NUMBERING_CAPTURE_RE.match(text)
                if inline_match:
                    numbering: str | None = inline_match.group(1)
                    text = text[inline_match.end() :].strip()
                else:
                    numbering = pending_numbering

                is_keyword = bool(_HEADING_RE.match(text))
                if is_keyword:
                    # A keyword match (Abstract/Introduction/Conclusion/...) is
                    # always top-level, but it does NOT establish a numbering
                    # *scheme* for the rest of the document — papers that never
                    # number their body sections (e.g. policy/ethics papers)
                    # would otherwise have every later unnumbered-but-genuinely
                    # top-level heading wrongly demoted as "one level deeper
                    # than Introduction". Only a real numbered heading (below)
                    # should start that tracking.
                    depth = 1
                elif numbering:
                    depth = _numbering_depth(numbering)
                    current_numbered_depth = depth
                elif current_numbered_depth > 0:
                    # No numbering of its own, but a numbered heading appeared
                    # earlier in the document — almost certainly an unnumbered
                    # sub-label one level deeper (e.g. "Residual Dropout" under
                    # a numbered "5.4 Regularization"), not a new top-level
                    # section with no number at all.
                    depth = current_numbered_depth + 1
                else:
                    # No numbering scheme detected anywhere yet in this paper —
                    # an unnumbered heading is how it denotes a section at all,
                    # so treat it as top-level rather than guessing it's nested.
                    depth = 1

                candidates.append((page_number, text, depth <= 1))
            pending_numbering = None  # only ever applies to the line immediately after it

    page_text_by_number = {page["page_number"]: page["text"] for page in pages}
    _full_text, page_offsets = _build_full_text(pages)
    page_start_by_number = {number: start for number, start, _ in page_offsets}

    # Map each candidate to its character offset so sections come out in true
    # document order. De-duplicate by heading text (keep the first occurrence
    # only): a running header/footer that prints the current section name on
    # every page would otherwise flood the outline with repeats of the same
    # entry — a genuine heading like "Conclusion" doesn't legitimately appear
    # twice in one paper.
    seen_text: set[str] = set()
    located: list[tuple[int, int, str, bool]] = []  # (offset, page_number, text, is_top_level)
    for page_number, text, is_top_level in candidates:
        key = text.strip().lower()
        if key in seen_text:
            continue
        page_text = page_text_by_number.get(page_number, "")
        local_index = page_text.find(text)
        if local_index == -1:
            continue
        seen_text.add(key)
        located.append((page_start_by_number[page_number] + local_index, page_number, text, is_top_level))

    located.sort(key=lambda item: item[0])

    # The title/author/affiliation block (short, bold or large-font lines, just
    # like real headings) always precedes the first real section — drop
    # anything detected before the first line that matches one of the known
    # top-level section keywords (Abstract, Introduction, ...), using that as
    # an anchor rather than a restriction on what counts as a heading from
    # there on.
    first_known_index = next(
        (i for i, (_offset, _page, text, _top) in enumerate(located) if _HEADING_RE.match(text.strip())),
        0,
    )
    located = located[first_known_index:]

    if not located:
        return [OutlineSection(heading="Full text", page_start=1, page_end=len(pages))], pages

    # Page ranges are computed from the full (unfiltered) list first, so a
    # top-level section's range correctly extends to the next *top-level*
    # section, absorbing every subsection page in between — then only the
    # top-level entries are kept for display.
    sections: list[OutlineSection] = []
    for index, (_offset, page_number, text, is_top_level) in enumerate(located):
        if not is_top_level:
            continue
        next_top = next(
            (located[j][1] for j in range(index + 1, len(located)) if located[j][3]),
            None,
        )
        page_end = len(pages) if next_top is None else max(next_top - 1, page_number)
        # Use the heading text as detected, not a normalized/title-cased
        # version: this is a generic visual-heading match (not the fixed
        # keyword list), so the paper's own casing is more faithful than
        # re-casing it ourselves.
        sections.append(OutlineSection(heading=text.strip(), page_start=page_number, page_end=page_end))

    if not sections:
        return [OutlineSection(heading="Full text", page_start=1, page_end=len(pages))], pages

    return sections, pages
