from __future__ import annotations

import re
from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.document_chunk import DocumentChunk
from app.models.uploaded_paper import UploadedPaper
from app.services.llm_service import LLMGenerationError, generate_chat_completion

SYSTEM_PROMPT = (
    "You are a research paper assistant. Write a clear, standalone summary of the "
    "following research paper for someone who has not read it. Cover: the problem it "
    "addresses, the core approach or method, and the key result or contribution. Write "
    "3-5 short paragraphs of plain prose. Do not use citation markers like [S1] — this "
    "is a summary, not a sourced answer."
)

# Aggregating the *whole* paper's chunks into one prompt can get long for bigger
# papers; past this many chunks, sample evenly across the document (by index, not
# just truncating the front) so the summary still covers intro through conclusion
# rather than only the opening chunks.
MAX_SUMMARY_CONTEXT_CHUNKS = 20

# Section-aware chunking (Phase 1) starts a new chunk exactly at a detected
# heading, so a tail section's first chunk begins with its heading as the literal
# first line. Cut the reference list / acknowledgements / appendix before
# sampling — left in, a small model tends to anchor on the list-like reference
# text (easy to "summarize" item-by-item) instead of the paper's actual content,
# which is exactly what happened in testing: a Q&A-quality retrieval pipeline
# still produced a summary that was just annotated references.
_TAIL_SECTION_HEADINGS = {"references", "bibliography", "acknowledgments", "acknowledgements", "appendix"}


def _drop_tail_sections(chunks: list[DocumentChunk]) -> list[DocumentChunk]:
    for index, chunk in enumerate(chunks):
        stripped = chunk.content.strip()
        first_line = stripped.splitlines()[0].strip().lower() if stripped else ""
        if first_line in _TAIL_SECTION_HEADINGS and index > 0:
            return chunks[:index]
    return chunks


# Belt-and-braces for the case _drop_tail_sections misses: not every document's
# reference list starts with a clean standalone heading line — a textbook
# chapter's bibliography, for instance, can begin mid-page with no detectable
# heading at all, so a chunk boundary can land squarely inside it with no
# "References" line anywhere nearby. Instead of relying on structure, detect
# the content itself: a chunk dense with citation-list markers (years, page
# ranges, venue names, "vol."/"pp.") is almost certainly bibliography, not
# prose — a chunk of real discussion might cite one paper in passing, but
# won't rack up many of these in a single ~1800-char chunk.
_CITATION_SIGNAL_RE = re.compile(
    r"\b(19|20)\d{2}[a-z]?\.|"  # "2017." / "2021a." — year-dot, common at each entry's start
    r"\bpp\.\s*\d+|"
    r"\bvol\.\s*\d+|"
    r"\bIn Proceedings of\b|"
    r"\b(ACL|EMNLP|NeurIPS|NIPS|ICML|ACM|ArXiv|arXiv)\b|"
    r"\d+\(\d+\):\d+",  # "30(11):964" — volume(issue):page, a references-list staple
    re.IGNORECASE,
)
_CITATION_SIGNAL_THRESHOLD = 4


def _is_reference_heavy(content: str) -> bool:
    return len(_CITATION_SIGNAL_RE.findall(content)) >= _CITATION_SIGNAL_THRESHOLD


def _select_representative_chunks(chunks: list[DocumentChunk]) -> list[DocumentChunk]:
    if len(chunks) <= MAX_SUMMARY_CONTEXT_CHUNKS:
        return chunks

    step = len(chunks) / MAX_SUMMARY_CONTEXT_CHUNKS
    indices = sorted({int(i * step) for i in range(MAX_SUMMARY_CONTEXT_CHUNKS)})
    if indices[-1] != len(chunks) - 1:
        indices.append(len(chunks) - 1)  # always include the last content chunk (conclusion)
    return [chunks[i] for i in indices]


def _build_context(chunks: list[DocumentChunk]) -> str:
    content_chunks = _drop_tail_sections(chunks)
    content_chunks = [chunk for chunk in content_chunks if not _is_reference_heavy(chunk.content)]
    selected = _select_representative_chunks(content_chunks)
    return "\n\n".join(f"(p.{chunk.page_start}) {chunk.content}" for chunk in selected)


def get_or_generate_summary(db: Session, paper: UploadedPaper, force: bool = False) -> tuple[str, bool]:
    """Return (summary, was_cached). Generates and caches on `paper.summary` the
    first time (or whenever `force=True`); every other call just returns the
    cached text without touching the LLM."""
    if paper.summary and not force:
        return paper.summary, True

    if paper.processing_status != "ready":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Paper is not ready for summarization yet (status: {paper.processing_status})",
        )

    statement = select(DocumentChunk).where(DocumentChunk.paper_id == paper.id).order_by(DocumentChunk.chunk_index)
    chunks = list(db.scalars(statement))
    if not chunks:
        raise ValueError(f"Paper {paper.id} has no chunks to summarize")

    context = _build_context(chunks)
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f'Paper title: "{paper.title}"\n\nExcerpts from the paper, in order:\n\n{context}'},
    ]
    try:
        summary = generate_chat_completion(messages)
    except LLMGenerationError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"The AI assistant is unavailable right now: {error}",
        ) from error

    paper.summary = summary
    paper.summary_generated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(paper)
    return summary, False
