from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy.orm import Session

from app.config.database import SessionLocal
from app.models.uploaded_paper import UploadedPaper
from app.services import chunking_service, summary_service
from app.services.format_templates import FORMAT_REVIEW_VERSION, FormatTemplate, TemplateSection, get_template
from app.services.llm_service import LLMGenerationError, generate_chat_completion

logger = logging.getLogger("app.format_review")

# A matched section's own word_range (currently only Abstract) already covers
# "too short"; Index Terms/Keywords is expected to be short by nature. Every
# other present section gets the generic near-empty check below.
_SKIP_NEAR_EMPTY_CHECK = {"abstract", "keywords"}
_MIN_SECTION_WORDS = 40

# A page-1 section (almost always the Abstract) is routinely followed, on that
# same page, by footnote-marker text (author-contribution notes, "Work done
# while at ...", the venue/arXiv line) rather than another detected heading —
# nothing in the plain-text extraction marks a paragraph boundary there, but a
# line starting with one of these footnote glyphs reliably marks where the
# actual section prose ends.
_FOOTNOTE_START_RE = re.compile(r"(?m)^\s*[∗†‡*]")

_CAPTION_RE = re.compile(r"(?m)^(Figure|Fig\.?|Table)\s+(\d+)\b", re.IGNORECASE)
_MAX_FIGURE_TABLE_FINDINGS = 5

# Only attempted when the reference list actually uses numbered-bracket style
# ("[12] Vaswani et al. ...") — an author-year paper ("(Smith et al., 2020)")
# has no reliable way to cross-check this way, so it's skipped silently rather
# than producing noisy false positives.
_REFERENCE_ENTRY_RE = re.compile(r"(?m)^\s*\[?(\d{1,3})\]?[.)]\s+\S")
_IN_TEXT_CITATION_RE = re.compile(r"\[(\d{1,3}(?:\s*,\s*\d{1,3})*)\]")
_MIN_REFERENCE_ENTRIES_FOR_CROSSCHECK = 3
_MAX_CITATION_FINDINGS = 5

FORMAT_FINDING_SYSTEM_PROMPT = (
    "You are reviewing one section of a research paper for a structural/quality "
    "check — NOT a missing-section or length check, those are already handled "
    "separately. Base your judgment only on the text provided; do not assume "
    "anything about sections you have not been shown, and do not invent a "
    "problem that isn't genuinely there just to have something to say. "
    "{question} "
    'Respond with JSON only: {{"issue": true or false, "message": "a specific, '
    'one-sentence description of the problem, or null if issue is false", '
    '"fix": "a concrete one-sentence suggestion to address it, or null if issue '
    'is false"}}.'
)

QUALITATIVE_QUESTIONS: dict[str, str] = {
    "abstract": (
        "Does this abstract state the paper's problem, its approach, AND a concrete "
        "result or contribution? Flag it only if one of these three is genuinely "
        "absent, not just brief."
    ),
    "introduction": (
        "Does the introduction state a clear problem statement or motivation — why "
        "this work matters? Flag it only if that's genuinely missing or so generic "
        "it could apply to almost any paper."
    ),
    "methodology": (
        "Is this methodology description detailed enough that another researcher "
        "could understand the actual approach taken (not necessarily reproduce "
        "every implementation detail)? Flag it only if key steps are vague or "
        "simply asserted with no explanation."
    ),
    "conclusion": (
        "Compare this conclusion against the paper's abstract, given as context. "
        "Does the conclusion introduce any new claim, result, or number that isn't "
        "already established by the abstract/rest of the paper? Flag it only if "
        "there's a genuinely new, unsupported claim — restating or elaborating on "
        "existing claims is fine."
    ),
}


def _match_sections(outline: list[dict], template: FormatTemplate) -> dict[str, dict | None]:
    """Greedily matches each template section to the first (in document order)
    outline heading whose text contains one of its aliases, consuming that
    outline entry so it can't also satisfy a different template section.
    Returns {section_id: {"heading", "page_start", "page_end"} | None}.
    """
    remaining: dict[str, TemplateSection] = {section.id: section for section in template.sections}
    matches: dict[str, dict | None] = {section.id: None for section in template.sections}

    for entry in outline:
        heading_lower = entry["heading"].strip().lower()
        matched_id = next(
            (section_id for section_id, section in remaining.items() if any(alias in heading_lower for alias in section.aliases)),
            None,
        )
        if matched_id:
            matches[matched_id] = {
                "heading": entry["heading"],
                "page_start": entry["page_start"],
                "page_end": entry["page_end"],
            }
            del remaining[matched_id]

    return matches


def _build_checklist(template: FormatTemplate, matches: dict[str, dict | None]) -> list[dict]:
    checklist = []
    for section in template.sections:
        match = matches.get(section.id)
        checklist.append(
            {
                "id": section.id,
                "name": section.name,
                "required": section.required,
                "present": match is not None,
                "heading": match["heading"] if match else None,
                "page_start": match["page_start"] if match else None,
                "page_end": match["page_end"] if match else None,
            }
        )
    return checklist


def _ordered_matches(matches: dict[str, dict | None]) -> list[dict]:
    """Matched sections in actual document order (by page_start) — used to find
    what immediately follows a given section, for trimming its text."""
    return sorted((match for match in matches.values() if match is not None), key=lambda match: match["page_start"])


def _next_match_after(match: dict, ordered: list[dict]) -> dict | None:
    index = ordered.index(match)
    return ordered[index + 1] if index + 1 < len(ordered) else None


def slice_section_text(pages_by_number: dict[int, str], match: dict, next_match: dict | None) -> str:
    """The section's own text, trimmed to start at its heading (so a page-1
    section doesn't pull in the title/author/affiliation block that precedes
    "Abstract" on the same page) and, when the following section starts on
    that same last page, to end before that next heading. Pages fully inside
    the range (not the first or last) are used whole — there's nothing else
    on them to trim around.
    """
    start_page, end_page = match["page_start"], match["page_end"]
    parts = []
    for page_number in range(start_page, end_page + 1):
        text = pages_by_number.get(page_number, "")
        if page_number == start_page:
            heading_index = text.find(match["heading"])
            if heading_index != -1:
                text = text[heading_index + len(match["heading"]) :]
        if page_number == end_page and next_match is not None and next_match["page_start"] == end_page:
            next_heading_index = text.find(next_match["heading"])
            if next_heading_index != -1:
                text = text[:next_heading_index]
        if page_number == end_page:
            footnote_match = _FOOTNOTE_START_RE.search(text)
            if footnote_match:
                text = text[: footnote_match.start()]
        parts.append(text)
    return "\n\n".join(parts).strip()


def _section_word_count(pages_by_number: dict[int, str], match: dict, next_match: dict | None) -> int:
    return len(slice_section_text(pages_by_number, match, next_match).split())


def _section_text(pages_by_number: dict[int, str], match: dict, next_match: dict | None, max_chars: int = 6000) -> str:
    return slice_section_text(pages_by_number, match, next_match)[:max_chars]


def _check_missing_and_order(template: FormatTemplate, matches: dict[str, dict | None]) -> list[dict]:
    findings = []
    for section in template.sections:
        if section.required and matches.get(section.id) is None:
            findings.append(
                {
                    "severity": "missing",
                    "section": section.name,
                    "page": None,
                    "message": f"Required section \"{section.name}\" was not found in the paper.",
                    "fix": f"Add a clearly labeled \"{section.name}\" section.",
                }
            )

    # Document order of the sections that WERE matched, by page position —
    # compared against the template's declared order_index to catch inversions.
    present = [(section, matches[section.id]) for section in template.sections if matches.get(section.id) is not None]
    present.sort(key=lambda pair: pair[1]["page_start"])
    for previous, current in zip(present, present[1:]):
        if current[0].order_index < previous[0].order_index:
            findings.append(
                {
                    "severity": "issue",
                    "section": current[0].name,
                    "page": current[1]["page_start"],
                    "message": f"\"{current[0].name}\" appears after \"{previous[0].name}\", but is conventionally expected before it.",
                    "fix": f"Consider moving \"{current[0].name}\" earlier, before \"{previous[0].name}\".",
                }
            )
    return findings


def _check_word_ranges(
    template: FormatTemplate, matches: dict[str, dict | None], pages_by_number: dict[int, str], ordered: list[dict]
) -> list[dict]:
    findings = []
    for section in template.sections:
        if section.word_range is None:
            continue
        match = matches.get(section.id)
        if match is None:
            continue
        min_words, max_words = section.word_range
        word_count = _section_word_count(pages_by_number, match, _next_match_after(match, ordered))
        if word_count < min_words:
            findings.append(
                {
                    "severity": "issue",
                    "section": section.name,
                    "page": match["page_start"],
                    "message": f"\"{section.name}\" is {word_count} words, shorter than the typical {min_words}-{max_words} word range.",
                    "fix": f"Expand \"{section.name}\" to cover the problem, approach, and result more fully.",
                }
            )
        elif word_count > max_words:
            findings.append(
                {
                    "severity": "issue",
                    "section": section.name,
                    "page": match["page_start"],
                    "message": f"\"{section.name}\" is {word_count} words, longer than the typical {min_words}-{max_words} word range.",
                    "fix": f"Tighten \"{section.name}\" to the essential problem, approach, and result.",
                }
            )
    return findings


def _check_near_empty_sections(
    template: FormatTemplate, matches: dict[str, dict | None], pages_by_number: dict[int, str], ordered: list[dict]
) -> list[dict]:
    findings = []
    for section in template.sections:
        if section.id in _SKIP_NEAR_EMPTY_CHECK:
            continue
        match = matches.get(section.id)
        if match is None:
            continue
        word_count = _section_word_count(pages_by_number, match, _next_match_after(match, ordered))
        if word_count < _MIN_SECTION_WORDS:
            findings.append(
                {
                    "severity": "issue",
                    "section": section.name,
                    "page": match["page_start"],
                    "message": f"\"{section.name}\" appears to be very short (~{word_count} words) for its role.",
                    "fix": f"Expand \"{section.name}\" with more detail, or confirm the heading was detected correctly.",
                }
            )
    return findings


def _check_figures_and_tables(pages: list[dict]) -> list[dict]:
    findings = []
    seen: set[tuple[str, str]] = set()
    full_text = "\n".join(page["text"] for page in pages)

    for page in pages:
        for match in _CAPTION_RE.finditer(page["text"]):
            label = "Figure" if match.group(1).lower().startswith("fig") else "Table"
            number = match.group(2)
            key = (label, number)
            if key in seen:
                continue
            seen.add(key)

            mention_pattern = rf"\b(?:Figure|Fig\.?)\s*{number}\b" if label == "Figure" else rf"\bTable\s*{number}\b"
            mention_count = len(re.findall(mention_pattern, full_text, re.IGNORECASE))
            if mention_count <= 1:  # only the caption itself
                findings.append(
                    {
                        "severity": "issue",
                        "section": label,
                        "page": page["page_number"],
                        "message": f"{label} {number} is captioned but never referenced elsewhere in the text.",
                        "fix": f'Reference it explicitly in the body (e.g. "as shown in {label} {number}"), or remove it if unused.',
                    }
                )
            if len(findings) >= _MAX_FIGURE_TABLE_FINDINGS:
                return findings
    return findings


def _check_citations(
    matches: dict[str, dict | None], pages_by_number: dict[int, str], pages: list[dict], ordered: list[dict]
) -> list[dict]:
    references_match = matches.get("references")
    if references_match is None:
        return []  # can't cross-check without a located reference list

    reference_text = _section_text(
        pages_by_number, references_match, _next_match_after(references_match, ordered), max_chars=50_000
    )
    reference_numbers = {int(n) for n in _REFERENCE_ENTRY_RE.findall(reference_text)}
    if len(reference_numbers) < _MIN_REFERENCE_ENTRIES_FOR_CROSSCHECK:
        return []  # not a numbered-bracket reference style (or too few to be confident) — skip rather than guess

    body_pages = [page for page in pages if not (references_match["page_start"] <= page["page_number"] <= references_match["page_end"])]
    body_text = "\n".join(page["text"] for page in body_pages)
    cited_numbers: set[int] = set()
    for match in _IN_TEXT_CITATION_RE.finditer(body_text):
        for part in match.group(1).split(","):
            part = part.strip()
            if part.isdigit():
                cited_numbers.add(int(part))

    findings = []
    for number in sorted(cited_numbers - reference_numbers)[:_MAX_CITATION_FINDINGS]:
        findings.append(
            {
                "severity": "issue",
                "section": "Citations",
                "page": None,
                "message": f"In-text citation [{number}] has no matching entry in the reference list.",
                "fix": "Add the missing reference entry, or correct the citation number if it's a typo.",
            }
        )
    for number in sorted(reference_numbers - cited_numbers)[:_MAX_CITATION_FINDINGS]:
        findings.append(
            {
                "severity": "suggestion",
                "section": "References",
                "page": references_match["page_start"],
                "message": f"Reference [{number}] is listed but never cited in the body text.",
                "fix": "Cite it where relevant, or remove it if it isn't actually used.",
            }
        )
    return findings


def _check_equation_numbering(pages: list[dict]) -> list[dict]:
    candidates = summary_service.find_equation_candidates(pages)
    numbered = [c for c in candidates if c[2] == "numbered"]
    heuristic = [c for c in candidates if c[2] == "heuristic"]
    if not numbered or not heuristic:
        return []  # either none detected, or every detected equation agrees on style — nothing inconsistent to report

    return [
        {
            "severity": "suggestion",
            "section": "Equations",
            "page": heuristic[0][0],
            "message": f"Equations are not consistently numbered — {len(heuristic)} equation(s) have no visible numbering while {len(numbered)} do.",
            "fix": "Number every displayed equation consistently (e.g. with a trailing \"(N)\"), or confirm this is intentional for inline expressions.",
        }
    ]


def _run_llm_checks(
    template: FormatTemplate, matches: dict[str, dict | None], pages_by_number: dict[int, str], ordered: list[dict]
) -> list[dict]:
    findings: list[dict] = []
    abstract_match = matches.get("abstract")
    abstract_text = (
        _section_text(pages_by_number, abstract_match, _next_match_after(abstract_match, ordered)) if abstract_match else ""
    )

    for section_id, question in QUALITATIVE_QUESTIONS.items():
        match = matches.get(section_id)
        if match is None:
            continue  # already flagged as missing by the deterministic check

        section_text = _section_text(pages_by_number, match, _next_match_after(match, ordered))
        if not section_text.strip():
            continue

        user_content = f"Section text:\n\n{section_text}"
        if section_id == "conclusion" and abstract_text:
            user_content = f"Abstract (context):\n\n{abstract_text}\n\n---\n\nConclusion:\n\n{section_text}"

        try:
            raw_response = generate_chat_completion(
                [
                    {"role": "system", "content": FORMAT_FINDING_SYSTEM_PROMPT.format(question=question)},
                    {"role": "user", "content": user_content},
                ],
                json_mode=True,
                temperature=0.2,
            )
            parsed = json.loads(raw_response)
            if not parsed.get("issue"):
                continue
            message = str(parsed.get("message") or "").strip()
            if not message:
                continue
            fix = parsed.get("fix")
            fix = str(fix).strip() if fix else None
        except (LLMGenerationError, ValueError, TypeError) as error:
            logger.warning("format_review_llm_check_failed section=%s error=%s", section_id, error)
            continue

        template_section = next(section for section in template.sections if section.id == section_id)
        findings.append(
            {
                "severity": "suggestion",
                "section": template_section.name,
                "page": match["page_start"],
                "message": message,
                "fix": fix,
            }
        )

    return findings


_SEVERITY_RANK = {"missing": 0, "issue": 1, "suggestion": 2}


def _run_review(db: Session, paper: UploadedPaper, template_id: str) -> dict:
    template = get_template(template_id)
    pdf_path = Path(paper.storage_path)
    if not pdf_path.exists():
        raise FileNotFoundError(f"Stored PDF not found for paper {paper.id}: {pdf_path}")

    outline, pages = chunking_service.extract_outline_and_pages(pdf_path)
    if not pages:
        raise ValueError(f"Paper {paper.id} has no extractable pages")

    outline_dicts = [{"heading": section.heading, "page_start": section.page_start, "page_end": section.page_end} for section in outline]
    matches = _match_sections(outline_dicts, template)
    pages_by_number = {page["page_number"]: page["text"] for page in pages}
    ordered = _ordered_matches(matches)

    findings: list[dict] = []
    findings += _check_missing_and_order(template, matches)
    findings += _check_word_ranges(template, matches, pages_by_number, ordered)
    findings += _check_near_empty_sections(template, matches, pages_by_number, ordered)
    findings += _check_figures_and_tables(pages)
    findings += _check_citations(matches, pages_by_number, pages, ordered)
    findings += _check_equation_numbering(pages)
    findings += _run_llm_checks(template, matches, pages_by_number, ordered)

    findings.sort(key=lambda finding: _SEVERITY_RANK.get(finding["severity"], 3))

    return {
        "format_version": FORMAT_REVIEW_VERSION,
        "template_id": template.id,
        "template_name": template.name,
        "checklist": _build_checklist(template, matches),
        "findings": findings,
    }


def get_review_entry(paper: UploadedPaper, template_id: str) -> dict:
    metadata = paper.paper_metadata or {}
    reviews = metadata.get("format_review") or {}
    return reviews.get(template_id) or {}


def is_review_current(entry: dict) -> bool:
    return bool(entry) and entry.get("format_version") == FORMAT_REVIEW_VERSION and entry.get("status") == "ready"


def mark_review_generating(db: Session, paper: UploadedPaper, template_id: str) -> None:
    metadata = paper.paper_metadata or {}
    reviews = dict(metadata.get("format_review") or {})
    reviews[template_id] = {**(reviews.get(template_id) or {}), "status": "generating", "error": None}
    paper.paper_metadata = {**metadata, "format_review": reviews}
    db.commit()


def start_format_review_generation(paper_id: int, template_id: str) -> None:
    """Runs the full format-review pipeline for one (paper, template) pair and
    writes the result back to `paper_metadata['format_review'][template_id]`.
    Intended as a FastAPI BackgroundTask (several LLM calls), same pattern as
    `summary_service.start_summary_generation` — opens its own DB session since
    the request-scoped one is gone by the time a background task runs.
    """
    db = SessionLocal()
    try:
        paper = db.get(UploadedPaper, paper_id)
        if paper is None:
            logger.warning("start_format_review_generation: paper %s not found", paper_id)
            return

        try:
            result = _run_review(db, paper, template_id)
            metadata = paper.paper_metadata or {}
            reviews = dict(metadata.get("format_review") or {})
            reviews[template_id] = {
                **result,
                "status": "ready",
                "error": None,
                "generated_at": datetime.now(timezone.utc).isoformat(),
            }
            paper.paper_metadata = {**metadata, "format_review": reviews}
            db.commit()
        except Exception as error:
            logger.exception("format_review_generation_failed paper_id=%s template=%s", paper_id, template_id)
            db.rollback()
            failed_paper = db.get(UploadedPaper, paper_id)
            if failed_paper is not None:
                metadata = failed_paper.paper_metadata or {}
                reviews = dict(metadata.get("format_review") or {})
                reviews[template_id] = {
                    **(reviews.get(template_id) or {}),
                    "status": "failed",
                    "error": str(error),
                }
                failed_paper.paper_metadata = {**metadata, "format_review": reviews}
                db.commit()
    finally:
        db.close()
