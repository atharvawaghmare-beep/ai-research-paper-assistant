import logging
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Query, Request, UploadFile, status
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.config.database import get_db
from app.config.settings import get_settings
from app.models.user import User
from app.rate_limit import limiter
from app.schemas.paper import (
    ConceptExplanationRequest,
    ConceptExplanationResponse,
    ExternalPaperResult,
    ExtractedPdfResponse,
    FormatReviewResponse,
    FormatTemplateInfo,
    PaperCitationsResponse,
    PaperSectionTranslationResponse,
    PaperCompareEntry,
    PaperCompareResponse,
    PaperImportRequest,
    PaperRecommendationResponse,
    PaperSearchResponse,
    PaperSummaryResponse,
    UploadedPaperRead,
)
from app.services import (
    citation_graph_service,
    concept_service,
    external_paper_service,
    format_review_service,
    recommendation_service,
    summary_service,
    translation_service,
)
from app.services.external_paper_service import ARXIV_CATEGORIES, ExternalPaperError
from app.services.format_templates import list_templates as list_format_templates
from app.services.paper_service import (
    delete_uploaded_paper,
    extract_pdf_page_text,
    get_user_paper_by_id,
    list_user_uploaded_papers,
    mark_paper_viewed,
    save_imported_pdf,
    save_uploaded_pdf,
)
from app.services.processing_service import process_uploaded_paper


router = APIRouter(prefix="/papers")
settings = get_settings()
logger = logging.getLogger("app.papers")


@router.post("/upload", response_model=UploadedPaperRead, status_code=status.HTTP_201_CREATED)
async def upload_paper(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    is_user_authored: bool = Form(False),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> UploadedPaperRead:
    """`is_user_authored=true` marks this as the user's own paper/draft (Phase 17's
    format review), distinct from an ordinary library paper. Citation-graph
    prefetch (Phase 9) already only ever runs on an import, never a manual
    upload, so marking a paper this way doesn't need to change anything else
    about how it's processed — it stays exactly as private as any other upload.
    """
    if not file.filename:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="A PDF filename is required")

    paper = await save_uploaded_pdf(
        db=db, current_user=current_user, upload_file=file, settings=settings, is_user_authored=is_user_authored
    )
    background_tasks.add_task(process_uploaded_paper, paper.id)
    return paper


@router.get("/", response_model=list[UploadedPaperRead])
def list_papers(
    sort: Literal["uploaded_at", "last_viewed_at"] = "uploaded_at",
    limit: int | None = Query(default=None, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[UploadedPaperRead]:
    return list_user_uploaded_papers(db, current_user, sort=sort, limit=limit)


@router.get("/search", response_model=PaperSearchResponse)
@limiter.limit("20/minute")
def search_external_papers(
    request: Request,
    q: str | None = None,
    category: list[str] = Query(default=[]),
    sort: Literal["relevance", "recent"] = "relevance",
    limit: int = 10,
    current_user: User = Depends(get_current_user),
) -> PaperSearchResponse:
    query = (q or "").strip() or None
    unknown_categories = [c for c in category if c not in ARXIV_CATEGORIES]
    if unknown_categories:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown category: {', '.join(unknown_categories)}",
        )
    if not query and not category:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Provide a search query, select a category, or both",
        )

    bounded_limit = max(1, min(limit, 25))
    results, warnings = external_paper_service.search_papers(
        query, bounded_limit, settings, categories=category or None, sort=sort
    )
    return PaperSearchResponse(query=query or "", results=results, warnings=warnings)


@router.get("/categories", response_model=dict[str, str])
def list_discover_categories() -> dict[str, str]:
    """The curated arXiv category whitelist the /search category filter accepts —
    exposed so the frontend doesn't hardcode a second copy of this list."""
    return ARXIV_CATEGORIES


@router.get("/format-templates", response_model=list[FormatTemplateInfo])
def list_format_review_templates() -> list[FormatTemplateInfo]:
    """The format-review templates (Phase 17) available to check a paper against —
    exposed so the frontend's template picker doesn't hardcode a second copy."""
    return [FormatTemplateInfo(**template) for template in list_format_templates()]


@router.get("/languages", response_model=dict[str, str])
def list_translation_languages() -> dict[str, str]:
    """The translation language whitelist (Phase 18) — same pattern as
    /papers/categories, so the frontend's language selector doesn't hardcode a
    second copy. Only languages actually verified end-to-end are listed here."""
    return translation_service.SUPPORTED_LANGUAGES


@router.post("/import", response_model=UploadedPaperRead, status_code=status.HTTP_201_CREATED)
@limiter.limit("10/minute")
def import_external_paper(
    request: Request,
    payload: PaperImportRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> UploadedPaperRead:
    """Downloads the PDF for an external search result server-side and feeds it into
    the exact same upload pipeline as a manual upload (same dedupe/size checks, same
    background chunk -> embed -> ready processing) — the user never handles the file.
    """
    max_size_bytes = settings.max_pdf_upload_size_mb * 1024 * 1024
    try:
        contents = external_paper_service.download_pdf(payload.pdf_url, max_size_bytes, settings)
    except ExternalPaperError as error:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(error)) from error

    paper = save_imported_pdf(
        db=db,
        current_user=current_user,
        settings=settings,
        contents=contents,
        title=(payload.title or payload.external_id).strip(),
        source=payload.source,
        external_id=payload.external_id,
        external_url=payload.external_url,
        categories=[category for category in payload.categories if category in ARXIV_CATEGORIES],
    )
    background_tasks.add_task(process_uploaded_paper, paper.id)

    # Best-effort: warm the citation-graph cache now so the paper's detail page
    # doesn't have to wait on a live Semantic Scholar call the first time it's
    # opened. A failure here (rate-limited, not indexed yet, ...) must never fail
    # the import itself — the /citations endpoint will just fetch it lazily later.
    try:
        citation_graph_service.get_or_refresh_citation_graph(db, paper)
    except Exception:
        logger.exception("citation_graph_prefetch_failed paper_id=%s", paper.id)

    return paper


@router.get("/recommendations", response_model=PaperRecommendationResponse)
@limiter.limit("10/minute")
def get_paper_recommendations(
    request: Request,
    limit: int = Query(default=10, ge=1, le=25),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> PaperRecommendationResponse:
    recommendations, interest_profile, warnings, message = recommendation_service.get_recommendations(
        db, current_user, limit=limit, settings=settings
    )
    return PaperRecommendationResponse(
        recommendations=recommendations,
        interest_profile=interest_profile,
        warnings=warnings,
        message=message,
    )


@router.get("/compare", response_model=PaperCompareResponse)
@limiter.limit("10/minute")
def compare_papers(
    request: Request,
    paper_ids: list[int] = Query(..., min_length=2, max_length=5),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> PaperCompareResponse:
    """Fetches (generating + caching, same as the single-paper summary endpoint)
    each paper's summary in one response shaped for side-by-side display — no new
    summarization logic, just reshaping the existing per-paper summary call across
    several papers. The actual comparison Q&A reuses the Phase 4 multi-paper chat
    endpoint directly; this only feeds the side-by-side summary view.
    """
    unique_ids = list(dict.fromkeys(paper_ids))  # de-dupe, preserve requested order
    entries = []
    for paper_id in unique_ids:
        paper = get_user_paper_by_id(db, current_user, paper_id)
        summary, cached = summary_service.get_or_generate_summary(db, paper)
        entries.append(
            PaperCompareEntry(paper=paper, summary=summary, cached=cached, generated_at=paper.summary_generated_at)
        )
    return PaperCompareResponse(papers=entries)


@router.get("/{paper_id}", response_model=UploadedPaperRead)
def get_paper(
    paper_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> UploadedPaperRead:
    paper = get_user_paper_by_id(db, current_user, paper_id)
    return mark_paper_viewed(db, paper)


@router.delete("/{paper_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_paper(
    paper_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    delete_uploaded_paper(db, current_user, paper_id)


@router.get("/{paper_id}/extract", response_model=ExtractedPdfResponse)
def extract_paper_text(
    paper_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ExtractedPdfResponse:
    paper = get_user_paper_by_id(db, current_user, paper_id)
    metadata, pages = extract_pdf_page_text(paper)
    return ExtractedPdfResponse(metadata=metadata, pages=pages)


@router.get("/{paper_id}/summary", response_model=PaperSummaryResponse)
@limiter.limit("30/minute")
def get_paper_summary(
    request: Request,
    paper_id: int,
    background_tasks: BackgroundTasks,
    refresh: bool = False,
    lang: str | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> PaperSummaryResponse:
    """Structured summary (Phase 16): outline, per-section summaries, overall
    summary, equations, and methods — generated as a background task (many LLM
    calls per paper) with a status field the frontend polls, same pattern as
    paper processing. A cached summary whose format_version is stale is treated
    as a cache miss and regenerated, never served as-is.

    Rate limit is looser than the other LLM-calling endpoints (30/minute, not
    10) because most calls here are cheap polls during a multi-minute
    background generation, not synchronous LLM calls — the one actually
    expensive action (triggering generation) is already self-throttled by the
    `summary_status == "generating"` guard below, independent of this limit.

    `lang` (Phase 18) triggers a second, independent background job that
    translates the already-generated English summary — it never substitutes
    for English generation, so a paper whose own summary isn't ready yet just
    reports `translation_status: "pending"` with nothing to translate from.
    """
    paper = get_user_paper_by_id(db, current_user, paper_id)
    if paper.processing_status != "ready":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Paper is not ready for summarization yet (status: {paper.processing_status})",
        )

    structured = paper.structured_summary or {}
    is_current = bool(paper.structured_summary) and structured.get("format_version") == summary_service.SUMMARY_FORMAT_VERSION

    if refresh:
        # An explicit request always (re)triggers — including unsticking a
        # "generating" row orphaned by a server restart/crash mid-task, which
        # would otherwise be stuck forever: nothing else ever flips it back.
        should_trigger = True
    elif paper.summary_status == "generating":
        should_trigger = False  # implicit poll, already in progress — don't start a second concurrent run
    else:
        # A previous failure only retries on an explicit refresh, not on every
        # plain page view — otherwise a persistently broken Ollama gets hammered
        # on every poll instead of surfacing the error once.
        should_trigger = not is_current and paper.summary_status != "failed"

    if should_trigger:
        paper.summary_status = "generating"
        paper.summary_error = None
        db.commit()
        background_tasks.add_task(summary_service.start_summary_generation, paper.id)

    output_overall_summary = structured.get("overall_summary")
    output_section_summaries = structured.get("section_summaries", [])
    output_equations = structured.get("equations", [])
    language = "en"
    translation_status: str | None = None

    if lang:
        if lang not in translation_service.SUPPORTED_LANGUAGES:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Unsupported language: {lang}")

        if paper.summary_status != "ready" or not is_current:
            translation_status = "pending"  # nothing ready to translate from yet
        else:
            translation_entry = translation_service.get_summary_translation_entry(paper, lang)
            translation_is_current = translation_service.is_summary_translation_current(paper, translation_entry)

            if refresh:
                translation_should_trigger = True
            elif translation_entry.get("status") == "generating":
                translation_should_trigger = False
            else:
                translation_should_trigger = not translation_is_current and translation_entry.get("status") != "failed"

            if translation_should_trigger:
                translation_service.mark_translation_generating(db, paper, translation_service.summary_translation_path(lang))
                background_tasks.add_task(translation_service.start_summary_translation, paper.id, lang)
                translation_entry = translation_service.get_summary_translation_entry(paper, lang)

            translation_status = translation_entry.get("status", "pending")
            if translation_status == "ready":
                merged = translation_service.apply_summary_translation(structured, translation_entry)
                output_overall_summary = merged["overall_summary"]
                output_section_summaries = merged["section_summaries"]
                output_equations = merged["equations"]
                language = lang

    return PaperSummaryResponse(
        status=paper.summary_status,
        cached=is_current and not refresh,
        generated_at=paper.summary_generated_at,
        outline=structured.get("outline", []),
        section_summaries=output_section_summaries,
        overall_summary=output_overall_summary,
        equations=output_equations,
        methods=structured.get("methods", []),
        error=paper.summary_error,
        language=language,
        translation_status=translation_status,
    )


def _handle_format_review_request(
    db: Session,
    background_tasks: BackgroundTasks,
    paper_id: int,
    template: str,
    refresh: bool,
    lang: str | None,
    current_user: User,
) -> FormatReviewResponse:
    """Shared by the poll (GET) and explicit-run (POST) endpoints — POST just
    forces `refresh=True`. Mirrors the trigger logic in `get_paper_summary`:
    an explicit refresh always (re)triggers, including unsticking a
    "generating" entry orphaned by a server restart mid-task; a plain poll
    triggers only on first-ever request or a stale format_version, and a
    previous failure only retries on an explicit refresh. `lang` (Phase 18)
    works the same way as on the summary endpoint: a second, independent
    background job that translates whatever English findings already exist.
    """
    paper = get_user_paper_by_id(db, current_user, paper_id)
    if paper.processing_status != "ready":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Paper is not ready for a format review yet (status: {paper.processing_status})",
        )

    try:
        template_info = format_review_service.get_template(template)
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)) from error

    entry = format_review_service.get_review_entry(paper, template)
    is_current = format_review_service.is_review_current(entry)

    if refresh:
        should_trigger = True
    elif entry.get("status") == "generating":
        should_trigger = False
    else:
        should_trigger = not is_current and entry.get("status") != "failed"

    if should_trigger:
        format_review_service.mark_review_generating(db, paper, template)
        background_tasks.add_task(format_review_service.start_format_review_generation, paper.id, template)
        entry = format_review_service.get_review_entry(paper, template)

    output_findings = entry.get("findings", [])
    language = "en"
    translation_status: str | None = None

    if lang:
        if lang not in translation_service.SUPPORTED_LANGUAGES:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Unsupported language: {lang}")

        if entry.get("status") != "ready" or not is_current:
            translation_status = "pending"
        else:
            translation_entry = translation_service.get_review_translation_entry(paper, template, lang)
            translation_is_current = translation_service.is_review_translation_current(entry, translation_entry)

            if refresh:
                translation_should_trigger = True
            elif translation_entry.get("status") == "generating":
                translation_should_trigger = False
            else:
                translation_should_trigger = not translation_is_current and translation_entry.get("status") != "failed"

            if translation_should_trigger:
                translation_service.mark_translation_generating(
                    db, paper, translation_service.review_translation_path(template, lang)
                )
                background_tasks.add_task(translation_service.start_review_translation, paper.id, template, lang)
                translation_entry = translation_service.get_review_translation_entry(paper, template, lang)

            translation_status = translation_entry.get("status", "pending")
            if translation_status == "ready":
                output_findings = translation_service.apply_review_translation(output_findings, translation_entry)
                language = lang

    return FormatReviewResponse(
        status=entry.get("status", "pending"),
        cached=is_current and not refresh,
        template_id=template_info.id,
        template_name=template_info.name,
        checklist=entry.get("checklist", []),
        findings=output_findings,
        generated_at=entry.get("generated_at"),
        error=entry.get("error"),
        language=language,
        translation_status=translation_status,
    )


@router.get("/{paper_id}/format-review", response_model=FormatReviewResponse)
@limiter.limit("30/minute")
def get_format_review(
    request: Request,
    paper_id: int,
    background_tasks: BackgroundTasks,
    template: str = "imrad",
    refresh: bool = False,
    lang: str | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> FormatReviewResponse:
    """Format review (Phase 17): checks a paper's structure against a template
    (missing/out-of-order sections, abstract length, uncited figures/tables,
    dangling citations, inconsistent equation numbering) plus LLM-graded
    qualitative findings, generated as a background task with a status the
    frontend polls — same pattern as Phase 16's summary. A cache miss (never
    generated, or a stale format_version) auto-triggers on this GET, same as
    the summary endpoint; `refresh=true` always regenerates.

    Rate limit matches the summary endpoint's reasoning: most calls here are
    cheap polls during a multi-minute background generation, not the
    (self-throttled by the "generating" guard) expensive action itself.
    """
    return _handle_format_review_request(db, background_tasks, paper_id, template, refresh, lang, current_user)


@router.post("/{paper_id}/format-review", response_model=FormatReviewResponse)
@limiter.limit("10/minute")
def run_format_review(
    request: Request,
    paper_id: int,
    background_tasks: BackgroundTasks,
    template: str = "imrad",
    lang: str | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> FormatReviewResponse:
    """Explicitly (re)runs the format review for `template` — e.g. the user
    switching templates or asking for a fresh check — always triggers
    generation regardless of any cached entry, unlike the polling GET above.
    """
    return _handle_format_review_request(db, background_tasks, paper_id, template, True, lang, current_user)


@router.get("/{paper_id}/citations", response_model=PaperCitationsResponse)
@limiter.limit("10/minute")
def get_paper_citations(
    request: Request,
    paper_id: int,
    refresh: bool = False,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> PaperCitationsResponse:
    paper = get_user_paper_by_id(db, current_user, paper_id)
    graph = citation_graph_service.get_or_refresh_citation_graph(db, paper, force=refresh)

    if graph is None:
        return PaperCitationsResponse(
            paper_id=paper.id,
            available=False,
            citation_count=None,
            reference_count=None,
            references=[],
            citing_papers=[],
            related_papers=[],
            fetched_at=None,
            message="No citation data available for this paper yet.",
        )

    return PaperCitationsResponse(
        paper_id=paper.id,
        available=True,
        citation_count=graph.get("citation_count"),
        reference_count=graph.get("reference_count"),
        references=[ExternalPaperResult(**entry) for entry in graph.get("references", [])],
        citing_papers=[ExternalPaperResult(**entry) for entry in graph.get("citing_papers", [])],
        related_papers=citation_graph_service.suggest_related_papers(graph),
        fetched_at=graph.get("fetched_at"),
    )


@router.post("/{paper_id}/explain", response_model=ConceptExplanationResponse)
@limiter.limit("10/minute")
def explain_paper_concept(
    request: Request,
    paper_id: int,
    payload: ConceptExplanationRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ConceptExplanationResponse:
    paper = get_user_paper_by_id(db, current_user, paper_id)
    explanation, citations = concept_service.explain_concept(db, paper, payload.term, payload.difficulty)

    language = "en"
    if payload.lang:
        # Not cached (same as the rest of this endpoint, which Phase 3
        # deliberately left uncached — explanations are cheap to regenerate
        # and have no stable "item" to key a cache on): translated
        # synchronously, in line with this endpoint's existing synchronous,
        # no-polling design rather than introducing a background-task/status
        # flow for what's already a single short paragraph.
        if payload.lang not in translation_service.SUPPORTED_LANGUAGES:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Unsupported language: {payload.lang}")
        try:
            explanation = translation_service.translate_text(explanation, payload.lang)
            language = payload.lang
        except Exception:
            logger.exception("concept_explanation_translation_failed paper_id=%s lang=%s", paper_id, payload.lang)
            # Fall back to the English explanation rather than failing the
            # whole request over a translation-only problem.

    return ConceptExplanationResponse(
        term=payload.term,
        difficulty=payload.difficulty,
        explanation=explanation,
        citations=citations,
        language=language,
    )


def _handle_section_translation_request(
    db: Session,
    background_tasks: BackgroundTasks,
    paper_id: int,
    section_index: int,
    lang: str,
    refresh: bool,
    current_user: User,
) -> PaperSectionTranslationResponse:
    """Shared by the poll (GET) and explicit-run (POST) endpoints below, same
    split as format-review's GET/POST pair. Translates one section of the
    paper's own text (Phase 16's outline) into `lang`, on demand — this is the
    third translation target from Phase 18's spec (alongside the summary and
    format-review translations above), the one with no existing English
    generation step to depend on: the English "source" here is just the raw
    PDF text for that section, which is always already available once the
    paper has finished processing.
    """
    if lang not in translation_service.SUPPORTED_LANGUAGES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Unsupported language: {lang}")

    paper = get_user_paper_by_id(db, current_user, paper_id)
    if paper.processing_status != "ready":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Paper is not ready for translation yet (status: {paper.processing_status})",
        )

    entry = translation_service.get_section_translation_entry(paper, lang, section_index)
    is_current = translation_service.is_section_translation_current(paper, entry)

    if refresh:
        should_trigger = True
    elif entry.get("status") == "generating":
        should_trigger = False
    else:
        should_trigger = not is_current and entry.get("status") != "failed"

    if should_trigger:
        translation_service.mark_translation_generating(
            db, paper, translation_service.section_translation_path(lang, section_index)
        )
        background_tasks.add_task(translation_service.start_section_translation, paper.id, lang, section_index)
        entry = translation_service.get_section_translation_entry(paper, lang, section_index)

    return PaperSectionTranslationResponse(
        status=entry.get("status", "pending"),
        cached=is_current and not refresh,
        language=lang,
        section_index=section_index,
        heading=entry.get("heading"),
        translated_heading=entry.get("translated_heading"),
        translated_text=entry.get("translated_text"),
        page_start=entry.get("page_start"),
        page_end=entry.get("page_end"),
        generated_at=entry.get("translated_at"),
        error=entry.get("error"),
    )


@router.get("/{paper_id}/translate-section", response_model=PaperSectionTranslationResponse)
@limiter.limit("30/minute")
def get_section_translation(
    request: Request,
    paper_id: int,
    background_tasks: BackgroundTasks,
    section_index: int = Query(..., ge=0),
    lang: str = Query(...),
    refresh: bool = False,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> PaperSectionTranslationResponse:
    """Translates section `section_index` of the paper's own text (Phase 16's
    outline order) into `lang` — background task + pollable status, same
    pattern as every other Phase 16-18 generation. A cache miss auto-triggers
    on this GET; `refresh=true` always regenerates.
    """
    return _handle_section_translation_request(db, background_tasks, paper_id, section_index, lang, refresh, current_user)


@router.post("/{paper_id}/translate-section", response_model=PaperSectionTranslationResponse)
@limiter.limit("10/minute")
def run_section_translation(
    request: Request,
    paper_id: int,
    background_tasks: BackgroundTasks,
    section_index: int = Query(..., ge=0),
    lang: str = Query(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> PaperSectionTranslationResponse:
    """Explicitly (re)translates one section — always triggers regardless of
    any cached entry, unlike the polling GET above."""
    return _handle_section_translation_request(db, background_tasks, paper_id, section_index, lang, True, current_user)