from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Request, UploadFile, status
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.config.database import get_db
from app.config.settings import get_settings
from app.models.user import User
from app.rate_limit import limiter
from app.schemas.paper import (
    ConceptExplanationRequest,
    ConceptExplanationResponse,
    ExtractedPdfResponse,
    PaperSummaryResponse,
    UploadedPaperRead,
)
from app.services import concept_service, summary_service
from app.services.paper_service import (
    delete_uploaded_paper,
    extract_pdf_page_text,
    get_user_paper_by_id,
    list_user_uploaded_papers,
    save_uploaded_pdf,
)
from app.services.processing_service import process_uploaded_paper


router = APIRouter(prefix="/papers")
settings = get_settings()


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
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[UploadedPaperRead]:
    return list_user_uploaded_papers(db, current_user)


@router.get("/{paper_id}", response_model=UploadedPaperRead)
def get_paper(
    paper_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> UploadedPaperRead:
    return get_user_paper_by_id(db, current_user, paper_id)


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