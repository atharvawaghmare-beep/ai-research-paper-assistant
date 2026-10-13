from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from sqlalchemy.orm import Session

from app.config.database import SessionLocal
from app.config.settings import get_settings
from app.models.uploaded_paper import UploadedPaper
from app.services import chunking_service, format_review_service

logger = logging.getLogger("app.translation")
settings = get_settings()

# Bumped whenever a cached translation entry's shape changes — same role as
# SUMMARY_FORMAT_VERSION / FORMAT_REVIEW_VERSION: a cached entry whose version
# doesn't match is treated as a cache miss and regenerated.
TRANSLATION_FORMAT_VERSION = 1

# Phase 18 language whitelist — same pattern as ARXIV_CATEGORIES, exposed via
# an endpoint so the frontend doesn't hardcode a second copy. Only Hindi has
# actually been tested end-to-end; per this phase's own instruction, a language
# is added here only once it's been verified, not just because the underlying
# model happens to support it.
SUPPORTED_LANGUAGES: dict[str, str] = {"hi": "Hindi"}
_NLLB_LANGUAGE_CODES: dict[str, str] = {"hi": "hin_Deva"}


def _get_translation_model():
    """Lazily loads the translation model once per process (cached on the
    settings-derived model name, so tests that swap settings still get a fresh
    model rather than a stale cached one from a previous name).

    Deliberately NOT routed through `llm_service`/Ollama: the chat model's
    Hindi output had real quality problems in testing — e.g. "state-of-the-art"
    came back as the nonsensical "राज्य-शीर्ष" instead of "अत्याधुनिक", and
    "generator"/"generated" were mistranslated as "पीढ़ी" (a generation of
    people). NLLB-200-distilled-600M, tried next on the exact same sentence,
    got both right and read naturally overall — so translation uses this
    dedicated model instead, per this phase's own instruction to check quality
    first rather than assume the existing LLM is good enough for every task.
    """
    from transformers import AutoModelForSeq2SeqLM, AutoTokenizer

    cache = _get_translation_model._cache
    if cache.get("name") != settings.translation_model_name:
        tokenizer = AutoTokenizer.from_pretrained(settings.translation_model_name, src_lang="eng_Latn")
        model = AutoModelForSeq2SeqLM.from_pretrained(settings.translation_model_name)
        model.eval()
        cache["name"] = settings.translation_model_name
        cache["tokenizer"] = tokenizer
        cache["model"] = model
    return cache["tokenizer"], cache["model"]


_get_translation_model._cache = {}


# --- Protecting what must never be altered by translation --------------------
# Citation markers ([12], [S1]), URLs, and standalone numbers must pass through
# a translation unchanged. NLLB did preserve these correctly in testing without
# any masking at all, but "usually correct" isn't good enough for a citation
# marker silently turning into the wrong number — masked before translation
# and restored after, per this phase's own instruction not to rely on the
# model's own judgment alone.
#
# The placeholder itself had to be chosen carefully: this is a *generative*
# model, not a literal find-and-replace, so an arbitrary OOV token isn't
# guaranteed to survive unchanged. An earlier letter-based scheme
# ("QQQ0QQQ") was tested and failed — repeated identical characters got
# corrupted by generation in a 2-of-3 test sentences (an extra "Q" appended
# in one case, a "Q" dropped entirely — silently breaking the restore regex
# — in another). A bare number in a reserved, implausible-in-real-prose range
# was tested next and survived perfectly across every multi-placeholder test
# sentence tried, which makes sense: NLLB already passes real numbers through
# untouched (confirmed separately), so reusing that same reliable path for
# placeholders too, instead of inventing a new token class, is what actually
# works here.
_PROTECTED_SPAN_RE = re.compile(
    r"\[S?\d+\]"  # [12] or [S1]
    r"|https?://\S+"  # URLs
    r"|\b\d+(?:\.\d+)?%?\b"  # numbers, decimals, percentages
)
_PLACEHOLDER_BASE = 9000000  # 7 digits, chosen to be implausible as a real number in a paper's prose
_PLACEHOLDER_RE = re.compile(r"\b9000\d{3}\b")  # indices 0-999 per chunk — ample for one paragraph/sentence


def _mask_protected_spans(text: str) -> tuple[str, list[str]]:
    # Built manually via finditer rather than a single .sub() call so a space
    # can be inserted between two placeholders that would otherwise land
    # directly adjacent — e.g. "[S1][S2]" (this app's own standard multi-
    # citation style, see citation_utils.CITATION_INSTRUCTION) masks to two
    # touching numbers that the model then regenerates as one ambiguous
    # digit blob, which the unmask regex can no longer tell apart. The one
    # cosmetic side effect — "[S1] [S2]" instead of "[S1][S2]" post-restore —
    # is an acceptable trade for both markers surviving at all.
    originals: list[str] = []
    pieces: list[str] = []
    cursor = 0
    previous_end: int | None = None
    for match in _PROTECTED_SPAN_RE.finditer(text):
        pieces.append(text[cursor : match.start()])
        if previous_end == match.start():
            pieces.append(" ")
        originals.append(match.group(0))
        pieces.append(str(_PLACEHOLDER_BASE + len(originals) - 1))
        cursor = match.end()
        previous_end = cursor
    pieces.append(text[cursor:])
    return "".join(pieces), originals


def _unmask_protected_spans(text: str, originals: list[str]) -> str:
    def _restore(match: re.Match) -> str:
        index = int(match.group(0)) - _PLACEHOLDER_BASE
        return originals[index] if 0 <= index < len(originals) else match.group(0)

    return _PLACEHOLDER_RE.sub(_restore, text)


# NLLB's practical per-call comfort zone on CPU — long text (the "translate
# this section of the paper" feature) is split on paragraph breaks first, then
# sentence boundaries within an over-long paragraph, so no single generate()
# call gets an input long enough to be truncated or to blow up latency.
_MAX_CHUNK_CHARS = 400
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")


def _split_into_sentence_chunks(paragraph: str) -> list[str]:
    if len(paragraph) <= _MAX_CHUNK_CHARS:
        return [paragraph]
    sentences = _SENTENCE_SPLIT_RE.split(paragraph)
    chunks: list[str] = []
    current = ""
    for sentence in sentences:
        if current and len(current) + len(sentence) + 1 > _MAX_CHUNK_CHARS:
            chunks.append(current.strip())
            current = sentence
        else:
            current = f"{current} {sentence}".strip()
    if current:
        chunks.append(current.strip())
    return chunks


def _translate_chunk(chunk: str, nllb_code: str, tokenizer, model) -> str:
    masked, originals = _mask_protected_spans(chunk)
    try:
        import torch

        inputs = tokenizer(masked, return_tensors="pt", truncation=True, max_length=512)
        with torch.inference_mode():
            generated = model.generate(
                **inputs,
                forced_bos_token_id=tokenizer.convert_tokens_to_ids(nllb_code),
                max_length=512,
                # Greedy decoding (the default, num_beams=1) was observed to
                # stop generating early and silently drop a trailing sentence
                # on some masked-placeholder inputs — beam search reliably
                # produced the complete translation in every case tried, for
                # ~1.3x the latency (CPU), which is well worth it for
                # correctness in a background task with no hard time budget.
                num_beams=4,
            )
        translated = tokenizer.batch_decode(generated, skip_special_tokens=True)[0]
        return _unmask_protected_spans(translated, originals)
    except Exception as error:  # one bad chunk shouldn't sink the whole translation
        logger.warning("translate_chunk_failed error=%s", error)
        return chunk  # fall back to the English chunk, untranslated


def translate_text(text: str, target_lang: str) -> str:
    """Translates `text` into `target_lang`, paragraph-by-paragraph (preserving
    blank-line structure) and sentence-chunked within any over-long paragraph.
    Returns the input unchanged for empty/whitespace-only text. Raises
    ValueError for an unsupported language — callers validate `target_lang`
    against SUPPORTED_LANGUAGES themselves before calling this, at the API
    boundary, so this is a defensive check, not the primary validation path.
    """
    if not text or not text.strip():
        return text
    if target_lang not in SUPPORTED_LANGUAGES:
        raise ValueError(f"Unsupported translation language: {target_lang!r}")

    nllb_code = _NLLB_LANGUAGE_CODES[target_lang]
    tokenizer, model = _get_translation_model()

    translated_paragraphs = []
    for paragraph in text.split("\n\n"):
        if not paragraph.strip():
            translated_paragraphs.append(paragraph)
            continue
        pieces = [_translate_chunk(chunk, nllb_code, tokenizer, model) for chunk in _split_into_sentence_chunks(paragraph)]
        translated_paragraphs.append(" ".join(pieces))
    return "\n\n".join(translated_paragraphs)


# --- Generic nested paper_metadata cache helpers ------------------------------
# Translations are cached several levels deep (paper_metadata -> translations
# -> lang -> summary/sections/{index}, or format_review -> {template} ->
# translations -> lang) — these two helpers read/write along an arbitrary path,
# always reassigning each dict along the way (never mutating in place), which
# is what SQLAlchemy's JSONB change detection needs to see the write, the same
# requirement every other JSONB-caching service in this codebase follows.
def _get_nested(metadata: dict, path: list[str]) -> dict:
    node = metadata
    for key in path:
        if not isinstance(node, dict) or key not in node:
            return {}
        node = node[key]
    return node if isinstance(node, dict) else {}


def _set_nested(metadata: dict, path: list[str], value: dict) -> dict:
    new_metadata = dict(metadata)
    if len(path) == 1:
        new_metadata[path[0]] = value
        return new_metadata
    key = path[0]
    child = dict(new_metadata.get(key) or {})
    new_metadata[key] = _set_nested(child, path[1:], value)
    return new_metadata


def _run_translation_job(paper_id: int, path: list[str], build_value: Callable[[Session, UploadedPaper], dict]) -> None:
    """Shared runner for every translation background task below: loads the
    paper in its own session (a FastAPI BackgroundTask's request-scoped session
    is already closed by the time this runs, same as every other background
    task in this codebase), calls `build_value(db, paper)` to produce the
    ready-state value, and writes it — or, on any exception, writes
    status=failed with the error instead. Factored out once rather than
    repeated for summary/format-review/section translation jobs, which
    otherwise differ only in what `build_value` actually computes.
    """
    db = SessionLocal()
    try:
        paper = db.get(UploadedPaper, paper_id)
        if paper is None:
            logger.warning("translation job: paper %s not found", paper_id)
            return

        try:
            value = build_value(db, paper)
            paper.paper_metadata = _set_nested(paper.paper_metadata or {}, path, value)
            db.commit()
        except Exception as error:
            logger.exception("translation_job_failed paper_id=%s path=%s", paper_id, path)
            db.rollback()
            failed_paper = db.get(UploadedPaper, paper_id)
            if failed_paper is not None:
                existing = _get_nested(failed_paper.paper_metadata or {}, path)
                value = {**existing, "status": "failed", "error": str(error)}
                failed_paper.paper_metadata = _set_nested(failed_paper.paper_metadata or {}, path, value)
                db.commit()
    finally:
        db.close()


def mark_translation_generating(db: Session, paper: UploadedPaper, path: list[str]) -> None:
    existing = _get_nested(paper.paper_metadata or {}, path)
    value = {**existing, "status": "generating", "error": None}
    paper.paper_metadata = _set_nested(paper.paper_metadata or {}, path, value)
    db.commit()


# --- Summary translation (Phase 16 content) -----------------------------------
def summary_translation_path(lang: str) -> list[str]:
    return ["translations", lang, "summary"]


def get_summary_translation_entry(paper: UploadedPaper, lang: str) -> dict:
    return _get_nested(paper.paper_metadata or {}, summary_translation_path(lang))


def is_summary_translation_current(paper: UploadedPaper, entry: dict) -> bool:
    source_version = paper.summary_generated_at.isoformat() if paper.summary_generated_at else None
    return (
        bool(entry)
        and entry.get("format_version") == TRANSLATION_FORMAT_VERSION
        and entry.get("status") == "ready"
        and entry.get("source_version") == source_version
    )


def start_summary_translation(paper_id: int, lang: str) -> None:
    def build(_db: Session, paper: UploadedPaper) -> dict:
        structured = paper.structured_summary or {}
        overall_summary = translate_text(structured.get("overall_summary") or "", lang)
        section_summaries = [
            {
                "heading": translate_text(section["heading"], lang),
                "page_start": section["page_start"],
                "page_end": section["page_end"],
                "summary": translate_text(section["summary"], lang),
            }
            for section in structured.get("section_summaries", [])
        ]
        # Positional list matching structured["equations"] order — only the
        # explanation is ever translated; raw_text/latex are never touched at
        # all (not even passed to the translator), since they're the equation
        # itself, not prose about it.
        equation_explanations = [translate_text(eq.get("explanation") or "", lang) for eq in structured.get("equations", [])]

        return {
            "format_version": TRANSLATION_FORMAT_VERSION,
            "status": "ready",
            "error": None,
            "source_version": paper.summary_generated_at.isoformat() if paper.summary_generated_at else None,
            "overall_summary": overall_summary,
            "section_summaries": section_summaries,
            "equation_explanations": equation_explanations,
            "translated_at": datetime.now(timezone.utc).isoformat(),
        }

    _run_translation_job(paper_id, summary_translation_path(lang), build)


def apply_summary_translation(structured: dict, translation: dict) -> dict:
    """Overlays a ready translation entry onto the English structured summary:
    swaps overall_summary/section headings+summaries/equation explanations for
    their translated text, while every other field (page ranges, raw_text,
    latex, confidence, and the methods list — proper nouns like "Transformer"
    or "Adam optimizer" that mostly have no meaningful Hindi equivalent, so
    deliberately left as-is) passes through unchanged.
    """
    translated_sections = translation.get("section_summaries", [])
    section_summaries = [
        {**section, "heading": translated.get("heading", section["heading"]), "summary": translated.get("summary", section["summary"])}
        for section, translated in zip(structured.get("section_summaries", []), translated_sections)
    ]
    translated_explanations = translation.get("equation_explanations", [])
    equations = [
        {**equation, "explanation": explanation}
        for equation, explanation in zip(structured.get("equations", []), translated_explanations)
    ]
    return {
        **structured,
        "overall_summary": translation.get("overall_summary", structured.get("overall_summary")),
        "section_summaries": section_summaries,
        "equations": equations,
    }


# --- Format-review translation (Phase 17 content) -----------------------------
def review_translation_path(template_id: str, lang: str) -> list[str]:
    return ["format_review", template_id, "translations", lang]


def get_review_translation_entry(paper: UploadedPaper, template_id: str, lang: str) -> dict:
    return _get_nested(paper.paper_metadata or {}, review_translation_path(template_id, lang))


def is_review_translation_current(review_entry: dict, translation_entry: dict) -> bool:
    return (
        bool(translation_entry)
        and translation_entry.get("format_version") == TRANSLATION_FORMAT_VERSION
        and translation_entry.get("status") == "ready"
        and translation_entry.get("source_version") == review_entry.get("generated_at")
    )


def start_review_translation(paper_id: int, template_id: str, lang: str) -> None:
    def build(_db: Session, paper: UploadedPaper) -> dict:
        review_entry = format_review_service.get_review_entry(paper, template_id)
        translated_findings = [
            {
                "section": translate_text(finding.get("section") or "", lang),
                "message": translate_text(finding.get("message") or "", lang),
                "fix": translate_text(finding["fix"], lang) if finding.get("fix") else None,
            }
            for finding in review_entry.get("findings", [])
        ]
        return {
            "format_version": TRANSLATION_FORMAT_VERSION,
            "status": "ready",
            "error": None,
            "source_version": review_entry.get("generated_at"),
            "findings": translated_findings,
            "translated_at": datetime.now(timezone.utc).isoformat(),
        }

    _run_translation_job(paper_id, review_translation_path(template_id, lang), build)


def apply_review_translation(findings: list[dict], translation: dict) -> list[dict]:
    """Overlays translated section/message/fix onto the English findings list
    (positional match) — severity and page are structural/numeric, left as-is.
    """
    translated = translation.get("findings", [])
    return [
        {
            **finding,
            "section": item.get("section", finding["section"]),
            "message": item.get("message", finding["message"]),
            "fix": item.get("fix", finding["fix"]),
        }
        for finding, item in zip(findings, translated)
    ]


# --- Paper section translation (the paper's own text, Phase 18's 3rd target) --
def section_translation_path(lang: str, section_index: int) -> list[str]:
    return ["translations", lang, "sections", str(section_index)]


def get_section_translation_entry(paper: UploadedPaper, lang: str, section_index: int) -> dict:
    return _get_nested(paper.paper_metadata or {}, section_translation_path(lang, section_index))


def _paper_source_version(paper: UploadedPaper) -> str | None:
    # Stable for as long as the paper's extracted text doesn't change — a
    # fresh re-processing (re-chunk/re-embed) is the only thing that would
    # ever invalidate a cached section translation.
    return paper.processed_at.isoformat() if paper.processed_at else None


def is_section_translation_current(paper: UploadedPaper, entry: dict) -> bool:
    return (
        bool(entry)
        and entry.get("format_version") == TRANSLATION_FORMAT_VERSION
        and entry.get("status") == "ready"
        and entry.get("source_version") == _paper_source_version(paper)
    )


def start_section_translation(paper_id: int, lang: str, section_index: int) -> None:
    def build(_db: Session, paper: UploadedPaper) -> dict:
        pdf_path = Path(paper.storage_path)
        if not pdf_path.exists():
            raise FileNotFoundError(f"Stored PDF not found for paper {paper.id}: {pdf_path}")

        outline, pages = chunking_service.extract_outline_and_pages(pdf_path)
        if section_index < 0 or section_index >= len(outline):
            raise ValueError(f"Section index {section_index} is out of range (paper has {len(outline)} sections)")

        section = outline[section_index]
        next_section = outline[section_index + 1] if section_index + 1 < len(outline) else None
        pages_by_number = {page["page_number"]: page["text"] for page in pages}

        match = {"heading": section.heading, "page_start": section.page_start, "page_end": section.page_end}
        next_match = (
            {"heading": next_section.heading, "page_start": next_section.page_start, "page_end": next_section.page_end}
            if next_section
            else None
        )
        section_text = format_review_service.slice_section_text(pages_by_number, match, next_match)
        if not section_text.strip():
            raise ValueError(f'Section {section_index} ("{section.heading}") has no extractable text')

        return {
            "format_version": TRANSLATION_FORMAT_VERSION,
            "status": "ready",
            "error": None,
            "source_version": _paper_source_version(paper),
            "heading": section.heading,
            "translated_heading": translate_text(section.heading, lang),
            "translated_text": translate_text(section_text, lang),
            "page_start": section.page_start,
            "page_end": section.page_end,
            "translated_at": datetime.now(timezone.utc).isoformat(),
        }

    _run_translation_job(paper_id, section_translation_path(lang, section_index), build)
