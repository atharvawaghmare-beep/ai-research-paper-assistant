from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config.database import SessionLocal
from app.models.document_chunk import DocumentChunk
from app.models.uploaded_paper import UploadedPaper
from app.services import chunking_service
from app.services.llm_service import LLMGenerationError, generate_chat_completion

logger = logging.getLogger("app.summary")

# Bumped whenever the structured_summary JSON shape changes. A cached summary
# whose format_version doesn't match this is treated as a cache miss and
# regenerated in the new shape rather than served stale (Phase 16 upgrades the
# Phase 3 plain-string summary in place; there is no reader left for the old
# shape to stay compatible with).
SUMMARY_FORMAT_VERSION = 2

MAX_SECTION_CONTEXT_CHUNKS = 6
MAX_EQUATIONS = 8
MAX_METHODS = 12

SECTION_SYSTEM_PROMPT = (
    "You are a research paper assistant. Write a concise 2-4 sentence summary of "
    "the following section of a research paper, covering only what this section "
    "itself says — do not reference other sections or guess at content you "
    "haven't been shown. Do not use citation markers like [S1]."
)

OVERALL_SYSTEM_PROMPT = (
    "You are a research paper assistant. Using only the section summaries provided "
    "below (not outside knowledge of the paper), write a clear, standalone 3-5 "
    "paragraph summary of the whole paper for someone who hasn't read it: the "
    "problem it addresses, its core approach, and its key result or contribution. "
    "Do not use citation markers like [S1]."
)

EQUATION_SYSTEM_PROMPT = (
    "You are a research paper assistant explaining one equation extracted from a "
    "PDF. The raw extracted text may be garbled or incomplete — PDF text "
    "extraction of mathematical notation is unreliable — so use the surrounding "
    "paragraph to infer what the equation actually says and means. "
    "Only describe variables, operators, and functions that actually appear in "
    "the raw text or are explicitly named in the surrounding context — never "
    "add a term (e.g. a sigmoid, softmax, or tanh) just because it would be "
    "plausible or typical for this kind of equation. If the raw text is too "
    "garbled to reconstruct with real confidence, it is better to say so and "
    'return "latex": null than to guess. '
    'Respond with JSON only: {"explanation": "plain-language explanation of what '
    'this equation computes and what its variables mean, grounded only in the '
    'surrounding text", "latex": "a best-effort LaTeX reconstruction of the '
    'equation, or null if you cannot confidently reconstruct it"}. '
    "Never imply the LaTeX is the paper's exact original formatting — it is your "
    "reconstruction, and the UI will label it as such."
)

METHODS_SYSTEM_PROMPT = (
    "List the key methods, algorithms, models, and datasets this paper uses, "
    "based only on the text provided. "
    'Respond with JSON only: {"methods": ["short name 1", "short name 2", ...]}. '
    "Only include things explicitly named in the text — do not invent or "
    "generalize. An empty list is fine if nothing is clearly named."
)

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


# --- Equation candidate detection --------------------------------------------
# PyMuPDF's plain-text extraction of math is lossy: a rendered fraction's
# numerator/operator/denominator often land on separate lines, and a numbered
# equation's "(3)" frequently ends up alone on its own line rather than at the
# end of the equation's text. Both patterns below account for that — a
# standalone or trailing number-in-parens is the strongest signal (the
# standard LaTeX-compiled convention), backed up by a short backward window to
# recover the equation body that preceded it.
_EQUATION_NUMBER_ONLY_RE = re.compile(r"^\(\s*\d{1,3}(?:\.\d+)?\s*\)$")
_EQUATION_NUMBER_TRAILING_RE = re.compile(r"\(\s*\d{1,3}(?:\.\d+)?\s*\)\s*$")
_MATH_SYMBOL_RE = re.compile(
    r"[=≈≠≤≥±×÷∑∏∫√"
    r"∂∇∞∈∉⊂⊆∪∩→⇒∀∃]|"
    r"[α-ωΑ-Ω]"  # Greek letters, upper and lower
)
_MATH_SYMBOL_THRESHOLD = 2
_MAX_EQUATION_BLOCK_LINES = 5
_MAX_EQUATION_LINE_LENGTH = 200


def _find_candidate_equations(pages: list[dict]) -> list[tuple[int, str, str]]:
    """Returns (page_number, raw_text, confidence) for lines that look like
    equations: "numbered" (a standalone or trailing "(3)"/"(3.1)" marker — the
    standard convention, high confidence) or "heuristic" (dense in math
    symbols/Greek letters with no sentence-ending punctuation — lower
    confidence, since plain text can't distinguish a true equation from a
    symbol-heavy prose line)."""
    candidates: list[tuple[int, str, str]] = []
    for page in pages:
        lines = page["text"].splitlines()
        for index, line in enumerate(lines):
            stripped = line.strip()
            if not stripped or len(stripped) > _MAX_EQUATION_LINE_LENGTH:
                continue

            is_number_only = bool(_EQUATION_NUMBER_ONLY_RE.match(stripped))
            has_trailing_number = bool(_EQUATION_NUMBER_TRAILING_RE.search(stripped)) and not is_number_only

            if is_number_only or has_trailing_number:
                block_lines: list[str] = []
                cursor = index - 1
                while cursor >= 0 and len(block_lines) < _MAX_EQUATION_BLOCK_LINES:
                    previous = lines[cursor].strip()
                    if not previous:
                        break
                    # A line ending in sentence-final punctuation is prose
                    # introducing the equation ("the matrix of outputs as:"),
                    # not part of it — stop backing up regardless of length.
                    # The old check only caught *long* lines ending in a
                    # period, so a short lead-in like "as follows:" or "then:"
                    # was still getting pulled into the equation body and fed
                    # to the LLM as if it were math, visibly degrading the
                    # reconstructed LaTeX and explanation.
                    if previous.endswith((".", ":", "!", "?")):
                        break
                    block_lines.insert(0, previous)
                    cursor -= 1

                if has_trailing_number:
                    main_text = _EQUATION_NUMBER_TRAILING_RE.sub("", stripped).strip()
                    if main_text:
                        block_lines.append(main_text)

                block_text = " ".join(block_lines).strip()
                # A trailing "(N)" isn't unique to equation numbering — a
                # multi-panel figure caption ("(a) Goldfish (1) (b) Bald
                # eagle (22) ...") matches the exact same shape and, without
                # this check, got slurped in (and re-slurped, once per
                # sub-label) as a growing "equation" containing no math at
                # all. A real equation always has an operator/relation
                # symbol or a Greek letter; a caption never does.
                if block_text and _MATH_SYMBOL_RE.search(block_text):
                    candidates.append((page["page_number"], block_text, "numbered"))
            elif len(_MATH_SYMBOL_RE.findall(stripped)) >= _MATH_SYMBOL_THRESHOLD and not stripped.endswith(
                (".", "?", "!")
            ):
                candidates.append((page["page_number"], stripped, "heuristic"))

    return candidates


def find_equation_candidates(pages: list[dict]) -> list[tuple[int, str, str]]:
    """Public wrapper around `_find_candidate_equations` — Phase 17's format-review
    "equations not numbered consistently" check reuses this exact detection logic
    rather than reimplementing it, so this exists purely to avoid a cross-module
    import of a underscore-prefixed function."""
    return _find_candidate_equations(pages)


def _select_equations(candidates: list[tuple[int, str, str]], limit: int = MAX_EQUATIONS) -> list[tuple[int, str, str]]:
    numbered = [c for c in candidates if c[2] == "numbered"]
    heuristic = [c for c in candidates if c[2] == "heuristic"]
    return (numbered + heuristic)[:limit]


def _context_for_page(chunks: list[DocumentChunk], page_number: int) -> str:
    for chunk in chunks:
        if chunk.page_start is not None and chunk.page_end is not None and chunk.page_start <= page_number <= chunk.page_end:
            return chunk.content
    return ""


def _explain_equation(page_number: int, raw_text: str, confidence: str, context: str) -> dict | None:
    try:
        raw_response = generate_chat_completion(
            [
                {"role": "system", "content": EQUATION_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": f'Raw extracted text (page {page_number}): "{raw_text}"\n\nSurrounding context:\n\n{context}',
                },
            ],
            json_mode=True,
            temperature=0.1,
        )
        parsed = json.loads(raw_response)
        explanation = str(parsed.get("explanation") or "").strip()
        latex = parsed.get("latex")
        latex = str(latex).strip() if latex else None
    except (LLMGenerationError, ValueError, TypeError) as error:
        logger.warning("equation_explanation_failed page=%s error=%s", page_number, error)
        return None

    if not explanation:
        return None

    return {
        "page": page_number,
        "raw_text": raw_text,
        "confidence": confidence,
        "explanation": explanation,
        "latex": latex,
    }


def _extract_methods(paper_title: str, section_summaries: list[dict]) -> list[str]:
    combined = "\n\n".join(f'{s["heading"]}: {s["summary"]}' for s in section_summaries)
    try:
        raw_response = generate_chat_completion(
            [
                {"role": "system", "content": METHODS_SYSTEM_PROMPT},
                {"role": "user", "content": f'Paper title: "{paper_title}"\n\n{combined}'},
            ],
            json_mode=True,
        )
        parsed = json.loads(raw_response)
        methods = parsed.get("methods") or []
    except (LLMGenerationError, ValueError, TypeError) as error:
        logger.warning("methods_extraction_failed error=%s", error)
        return []

    return [m.strip() for m in methods if isinstance(m, str) and m.strip()][:MAX_METHODS]


def _summarize_section(heading: str, page_start: int, page_end: int, chunks: list[DocumentChunk]) -> dict | None:
    if not chunks:
        return None
    text = "\n\n".join(chunk.content for chunk in chunks[:MAX_SECTION_CONTEXT_CHUNKS])
    try:
        summary_text = generate_chat_completion(
            [
                {"role": "system", "content": SECTION_SYSTEM_PROMPT},
                {"role": "user", "content": f'Section: "{heading}" (pages {page_start}-{page_end})\n\n{text}'},
            ]
        ).strip()
    except LLMGenerationError as error:
        logger.warning("section_summary_failed heading=%r error=%s", heading, error)
        return None

    if not summary_text:
        return None

    return {"heading": heading, "page_start": page_start, "page_end": page_end, "summary": summary_text}


def _generate_structured_summary(db: Session, paper: UploadedPaper) -> dict:
    pdf_path = Path(paper.storage_path)
    if not pdf_path.exists():
        raise FileNotFoundError(f"Stored PDF not found for paper {paper.id}: {pdf_path}")

    outline, pages = chunking_service.extract_outline_and_pages(pdf_path)
    if not pages:
        raise ValueError(f"Paper {paper.id} has no extractable pages")

    statement = select(DocumentChunk).where(DocumentChunk.paper_id == paper.id).order_by(DocumentChunk.chunk_index)
    all_chunks = list(db.scalars(statement))
    if not all_chunks:
        raise ValueError(f"Paper {paper.id} has no chunks to summarize")

    content_chunks = _drop_tail_sections(all_chunks)
    content_chunks = [chunk for chunk in content_chunks if not _is_reference_heavy(chunk.content)]

    section_summaries: list[dict] = []
    for section in outline:
        section_chunks = [
            chunk
            for chunk in content_chunks
            if chunk.page_start is not None
            and chunk.page_end is not None
            and chunk.page_start <= section.page_end
            and chunk.page_end >= section.page_start
        ]
        summarized = _summarize_section(section.heading, section.page_start, section.page_end, section_chunks)
        if summarized:
            section_summaries.append(summarized)

    if not section_summaries:
        raise ValueError(f"Could not summarize any section of paper {paper.id}")

    combined = "\n\n".join(
        f'{s["heading"]} (p.{s["page_start"]}-{s["page_end"]}): {s["summary"]}' for s in section_summaries
    )
    overall_summary = generate_chat_completion(
        [
            {"role": "system", "content": OVERALL_SYSTEM_PROMPT},
            {"role": "user", "content": f'Paper title: "{paper.title}"\n\nSection summaries:\n\n{combined}'},
        ]
    ).strip()
    if not overall_summary:
        raise ValueError(f"LLM returned an empty overall summary for paper {paper.id}")

    candidates = _find_candidate_equations(pages)
    selected = _select_equations(candidates)
    equations = []
    for page_number, raw_text, confidence in selected:
        context = _context_for_page(all_chunks, page_number)
        explained = _explain_equation(page_number, raw_text, confidence, context)
        if explained:
            equations.append(explained)

    methods = _extract_methods(paper.title, section_summaries)

    return {
        "format_version": SUMMARY_FORMAT_VERSION,
        "outline": [
            {"heading": section.heading, "page_start": section.page_start, "page_end": section.page_end}
            for section in outline
        ],
        "section_summaries": section_summaries,
        "overall_summary": overall_summary,
        "equations": equations,
        "methods": methods,
    }


def start_summary_generation(paper_id: int) -> None:
    """Runs the full structured-summary pipeline for one paper and writes the
    result (or failure) back to the DB. Intended as a FastAPI BackgroundTask
    (many LLM calls per paper — one per section, one overall, one per equation,
    one for methods — so this must never block a request), same pattern as
    `processing_service.process_uploaded_paper`: the request-scoped DB session
    is gone by the time a background task runs, so this opens its own.
    """
    db = SessionLocal()
    try:
        paper = db.get(UploadedPaper, paper_id)
        if paper is None:
            logger.warning("start_summary_generation: paper %s not found", paper_id)
            return

        try:
            structured = _generate_structured_summary(db, paper)
            paper.structured_summary = structured
            paper.summary_status = "ready"
            paper.summary_error = None
            paper.summary_generated_at = datetime.now(timezone.utc)
            db.commit()
        except Exception as error:
            logger.exception("summary_generation_failed paper_id=%s", paper_id)
            db.rollback()
            failed_paper = db.get(UploadedPaper, paper_id)
            if failed_paper is not None:
                failed_paper.summary_status = "failed"
                failed_paper.summary_error = str(error)
                db.commit()
    finally:
        db.close()


def get_or_generate_summary(db: Session, paper: UploadedPaper, force: bool = False) -> tuple[str, bool]:
    """Back-compat shim for Phase 10's Compare mode, which calls this directly
    and synchronously (no background-task polling) and only needs the plain
    overall-summary text — `/papers/compare` keeps working against the new
    structured shape with zero changes on its side.

    Returns (overall_summary, was_cached). On a cache miss this runs the full
    structured pipeline synchronously rather than just the overall-summary
    step — slower than the old single-LLM-call Phase 3 version the first time,
    but the full result (outline, equations, methods included) gets cached, so
    a later visit to the paper's own Summary tab doesn't redo any of this work.
    """
    current = paper.structured_summary
    if current and current.get("format_version") == SUMMARY_FORMAT_VERSION and not force:
        return current["overall_summary"], True

    if paper.processing_status != "ready":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Paper is not ready for summarization yet (status: {paper.processing_status})",
        )

    try:
        structured = _generate_structured_summary(db, paper)
    except LLMGenerationError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"The AI assistant is unavailable right now: {error}",
        ) from error

    paper.structured_summary = structured
    paper.summary_status = "ready"
    paper.summary_error = None
    paper.summary_generated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(paper)
    return structured["overall_summary"], False
