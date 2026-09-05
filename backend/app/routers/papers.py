import logging
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Query, Request, UploadFile, status
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
    PaperCitationsResponse,
    PaperCompareEntry,
    PaperCompareResponse,
    PaperImportRequest,
    PaperSearchResponse,
    PaperSummaryResponse,
    UploadedPaperRead,
)
from app.services import citation_graph_service, concept_service, external_paper_service, summary_service
from app.services.external_paper_service import ExternalPaperError
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
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> UploadedPaperRead:
    if not file.filename:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="A PDF filename is required")

    paper = await save_uploaded_pdf(db=db, current_user=current_user, upload_file=file, settings=settings)
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
    q: str,
    limit: int = 10,
    current_user: User = Depends(get_current_user),
) -> PaperSearchResponse:
    query = q.strip()
    if not query:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Search query must not be empty")

    bounded_limit = max(1, min(limit, 25))
    results, warnings = external_paper_service.search_papers(query, bounded_limit, settings)
    return PaperSearchResponse(query=query, results=results, warnings=warnings)


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
@limiter.limit("10/minute")
def get_paper_summary(
    request: Request,
    paper_id: int,
    refresh: bool = False,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> PaperSummaryResponse:
    paper = get_user_paper_by_id(db, current_user, paper_id)
    summary, cached = summary_service.get_or_generate_summary(db, paper, force=refresh)
    return PaperSummaryResponse(summary=summary, cached=cached, generated_at=paper.summary_generated_at)


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
    return ConceptExplanationResponse(
        term=payload.term,
        difficulty=payload.difficulty,
        explanation=explanation,
        citations=citations,
    )