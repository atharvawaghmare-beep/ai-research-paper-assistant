from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config.settings import get_settings
from app.models.document_chunk import DocumentChunk
from app.models.uploaded_paper import UploadedPaper
from app.services.llm_service import LLMGenerationError, generate_chat_completion

logger = logging.getLogger("app.paper_insight")

# The abstract and the key terminology live in the opening of a paper; the
# first few section-aware chunks cover title/abstract/introduction for
# essentially every paper format, and keeping the prompt short keeps the local
# model fast (this runs in the upload pipeline, so latency is user-visible).
MAX_INSIGHT_CHUNKS = 4
MAX_INSIGHT_CHARS = 6000
MAX_ABSTRACT_CHARS = 1500
FALLBACK_ABSTRACT_CHARS = 1200
MIN_KEY_PHRASES = 3
MAX_KEY_PHRASES = 6

SYSTEM_PROMPT = (
    "You extract structured metadata from research papers. Reply with a single JSON "
    "object and nothing else — no prose, no markdown fences."
)

USER_PROMPT_TEMPLATE = (
    'Paper title: "{title}"\n\n'
    "Opening text of the paper:\n\n{context}\n\n"
    "Return JSON with exactly these keys:\n"
    "  \"title\": the paper's full title exactly as printed on its first page.\n"
    '  "abstract": the paper\'s abstract, verbatim if one is present in the text; otherwise '
    "3-5 sentences stating the problem, the method, and the main result.\n"
    '  "key_phrases": a list of {min_phrases}-{max_phrases} short technical phrases (1-4 words each) '
    "that someone would type into a literature search to find closely related papers. Use the "
    "paper's own specific terminology (methods, model names, task names, domains) — not generic "
    'words like "deep learning", "neural network", "results", or "paper".'
)


def opening_text(db: Session, paper: UploadedPaper) -> str:
    """The first few chunks of the paper (title page, abstract, intro)."""
    statement = (
        select(DocumentChunk)
        .where(DocumentChunk.paper_id == paper.id)
        .order_by(DocumentChunk.chunk_index)
        .limit(MAX_INSIGHT_CHUNKS)
    )
    chunks = list(db.scalars(statement))
    text = "\n\n".join(chunk.content for chunk in chunks)
    return text[:MAX_INSIGHT_CHARS]


def _coerce_text(value: object) -> str:
    """The model occasionally returns the abstract as a list of sentences or a
    {problem, method, result} object instead of one string; flatten either."""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return " ".join(_coerce_text(item) for item in value)
    if isinstance(value, dict):
        return " ".join(_coerce_text(item) for item in value.values())
    return ""


def _parse_insight_json(raw: str, fallback_abstract: str = "") -> dict | None:
    """Small local models usually honour "JSON only" but sometimes wrap it in
    fences or a leading sentence; pull out the first {...} block and validate
    its shape rather than trusting it blindly."""
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if not match:
        return None
    try:
        payload = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None

    abstract = _coerce_text(payload.get("abstract"))
    phrases = payload.get("key_phrases")
    if not isinstance(phrases, list):
        return None

    # Slide decks, lecture notes and reports often have no abstract, and the
    # model correctly answers null. The downstream consumers (classifier,
    # related-paper search) just need representative text, so the opening of
    # the document stands in — flagged so the UI/report can tell the two apart.
    abstract_source = "llm"
    if not abstract.strip():
        abstract = fallback_abstract
        abstract_source = "opening_text"
    if not abstract.strip():
        return None

    cleaned_phrases: list[str] = []
    for phrase in phrases:
        if not isinstance(phrase, str):
            continue
        phrase = " ".join(phrase.split()).strip(" .,;:\"'")
        if 2 <= len(phrase) <= 60 and phrase.lower() not in {p.lower() for p in cleaned_phrases}:
            cleaned_phrases.append(phrase)
    if len(cleaned_phrases) < MIN_KEY_PHRASES:
        return None

    title = " ".join(_coerce_text(payload.get("title")).split()).strip(" .\"'")
    return {
        "title": title if 8 <= len(title) <= 250 else None,
        "abstract": " ".join(abstract.split())[:MAX_ABSTRACT_CHARS],
        "abstract_source": abstract_source,
        "key_phrases": cleaned_phrases[:MAX_KEY_PHRASES],
    }


def _filename_derived_title(paper: UploadedPaper) -> str:
    # Mirrors paper_service's fallback so we can tell "still the filename" apart
    # from a title the user or an import supplied.
    return Path(paper.original_filename or "").stem.replace("_", " ").replace("-", " ").strip()


def _maybe_adopt_extracted_title(paper: UploadedPaper, extracted_title: str | None) -> bool:
    """Manual uploads are titled after their filename ("2304.02643", "paper",
    "segment_anything"). If the LLM read a real title off the first page and
    the stored title is still the filename one, adopt it. Imports and papers
    the user renamed are left alone."""
    if not extracted_title:
        return False
    if (paper.paper_metadata or {}).get("source") != "pdf-upload":
        return False
    if paper.title.strip().lower() != _filename_derived_title(paper).lower():
        return False
    if extracted_title == paper.title.strip():
        return False
    paper.title = extracted_title[:255]
    return True


def get_cached_insight(paper: UploadedPaper) -> dict | None:
    insight = (paper.paper_metadata or {}).get("insight")
    if isinstance(insight, dict) and insight.get("status") == "ready":
        return insight
    return None


def extract_paper_insight(db: Session, paper: UploadedPaper, force: bool = False) -> dict | None:
    """Ask the LLM for the paper's abstract and search key-phrases, cache the
    result on `paper.paper_metadata['insight']` (same cache-on-the-paper
    pattern as the summary and citation graph), and return it.

    This is enrichment, not a hard dependency: on any failure it records a
    `failed` marker with the reason (so it's visible, not silent) and returns
    None, and callers fall back to whatever they did before Phase 14b.
    """
    cached = get_cached_insight(paper)
    if cached and not force:
        return cached

    settings = get_settings()
    metadata = dict(paper.paper_metadata or {})

    def _record(payload: dict) -> None:
        paper.paper_metadata = {**metadata, "insight": payload}
        db.commit()
        db.refresh(paper)

    context = opening_text(db, paper)
    if not context.strip():
        _record({"status": "failed", "error": "no chunk text available"})
        return None

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": USER_PROMPT_TEMPLATE.format(
                title=paper.title,
                context=context,
                min_phrases=MIN_KEY_PHRASES,
                max_phrases=MAX_KEY_PHRASES,
            ),
        },
    ]
    try:
        raw = generate_chat_completion(messages, json_mode=True)
    except LLMGenerationError as error:
        logger.warning("paper_insight_llm_failed paper_id=%s error=%s", paper.id, error)
        _record({"status": "failed", "error": f"LLM unavailable: {error}"})
        return None

    parsed = _parse_insight_json(raw, fallback_abstract=context[:FALLBACK_ABSTRACT_CHARS])
    if parsed is None:
        logger.warning("paper_insight_unparsable paper_id=%s raw=%r", paper.id, raw[:200])
        _record({"status": "failed", "error": "LLM response was not valid insight JSON"})
        return None

    payload = {
        "status": "ready",
        **parsed,
        "model": settings.ollama_model,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    if _maybe_adopt_extracted_title(paper, parsed.get("title")):
        logger.info("paper_title_adopted paper_id=%s title=%r", paper.id, paper.title)
    _record(payload)
    logger.info("paper_insight_ready paper_id=%s key_phrases=%r", paper.id, parsed["key_phrases"])
    return payload
