from __future__ import annotations

import re
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException, UploadFile, status
import pymupdf
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config.settings import Settings
from app.models.document_chunk import DocumentChunk
from app.models.uploaded_paper import UploadedPaper
from app.models.user import User
from app.services import faiss_index_service
from app.utils.time import utc_now

ALLOWED_PDF_MIME_TYPES = {"application/pdf", "application/x-pdf"}
_UNSAFE_FILENAME_CHARS = re.compile(r'[\\/:*?"<>|\r\n\t]')


def get_existing_paper_by_checksum(db: Session, checksum: str) -> UploadedPaper | None:
    statement = select(UploadedPaper).where(UploadedPaper.checksum_sha256 == checksum)
    return db.scalar(statement)


def list_user_uploaded_papers(
    db: Session,
    current_user: User,
    sort: str = "uploaded_at",
    limit: int | None = None,
) -> list[UploadedPaper]:
    statement = select(UploadedPaper).where(UploadedPaper.user_id == current_user.id)

    if sort == "last_viewed_at":
        # "Recently viewed" only makes sense for papers that have actually been
        # opened at least once — a paper sitting at NULL isn't "recent", it's unseen.
        statement = statement.where(UploadedPaper.last_viewed_at.is_not(None)).order_by(
            UploadedPaper.last_viewed_at.desc()
        )
    else:
        statement = statement.order_by(UploadedPaper.uploaded_at.desc())

    if limit is not None:
        statement = statement.limit(limit)

    return list(db.scalars(statement))


def mark_paper_viewed(db: Session, paper: UploadedPaper) -> UploadedPaper:
    """Stamps `last_viewed_at` for the "recently viewed" dashboard section. Called
    only from the explicit "open a paper" route (`GET /papers/{id}`) — not from the
    shared `get_user_paper_by_id` lookup other services (summary, explain, chat) use
    internally, so calling those doesn't masquerade as the user viewing the paper.
    """
    paper.last_viewed_at = utc_now()
    db.commit()
    db.refresh(paper)
    return paper


def get_user_paper_by_id(db: Session, current_user: User, paper_id: int) -> UploadedPaper:
    statement = select(UploadedPaper).where(UploadedPaper.id == paper_id, UploadedPaper.user_id == current_user.id)
    paper = db.scalar(statement)
    if paper is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Paper not found")
    return paper


def extract_pdf_page_text(paper: UploadedPaper) -> tuple[dict, list[dict]]:
    pdf_path = Path(paper.storage_path)
    if not pdf_path.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Stored PDF file not found on disk")

    try:
        document = pymupdf.open(pdf_path)
    except Exception as error:  # pragma: no cover
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Unable to open PDF: {error}") from error

    pages: list[dict] = []
    try:
        for index, page in enumerate(document, start=1):
            pages.append({
                "page_number": index,
                "text": page.get_text("text").strip(),
            })

        metadata = {
            "paper_id": paper.id,
            "title": paper.title,
            "original_filename": paper.original_filename,
            "storage_path": paper.storage_path,
            "file_size_bytes": paper.file_size_bytes,
            "total_pages": document.page_count,
            "pdf_metadata": {
                "author": document.metadata.get("author"),
                "subject": document.metadata.get("subject"),
                "title": document.metadata.get("title"),
                "keywords": document.metadata.get("keywords"),
                "creator": document.metadata.get("creator"),
                "producer": document.metadata.get("producer"),
                "creationDate": document.metadata.get("creationDate"),
                "modDate": document.metadata.get("modDate"),
            },
        }
    finally:
        document.close()

    return metadata, pages


def delete_uploaded_paper(db: Session, current_user: User, paper_id: int) -> None:
    """Delete a paper the user owns: removes the DB row (which cascades to its
    chunks, embeddings, and chat-session links via existing FK constraints),
    its vectors from the FAISS index, and the stored PDF file on disk.

    Any chat session that referenced only this paper survives — its anchor
    paper_id is set to NULL by the FK (ondelete="SET NULL") rather than the
    session being deleted — a paper being removed shouldn't silently erase a
    conversation's history. A session left with no linked papers at all is no
    longer reachable through any /papers/{id}/chat route, though its rows
    still exist; that's an acceptable edge case for a "remove a paper" action,
    not something this function tries to repair.
    """
    paper = get_user_paper_by_id(db, current_user, paper_id)

    chunk_ids = [row.id for row in db.query(DocumentChunk.id).filter(DocumentChunk.paper_id == paper.id)]
    storage_path = Path(paper.storage_path)

    db.delete(paper)
    db.commit()

    if chunk_ids:
        faiss_index_service.remove_chunk_vectors(chunk_ids)

    if storage_path.exists():
        storage_path.unlink()


def _sanitize_filename_component(value: str, fallback: str = "paper") -> str:
    cleaned = _UNSAFE_FILENAME_CHARS.sub(" ", value).strip()
    cleaned = " ".join(cleaned.split())
    return cleaned[:150] or fallback


def _persist_new_paper(
    db: Session,
    current_user: User,
    settings: Settings,
    contents: bytes,
    *,
    original_filename: str,
    mime_type: str | None,
    title: str | None = None,
    extra_metadata: dict,
) -> UploadedPaper:
    """Dedupe-by-checksum, size-check, on-disk storage, and `UploadedPaper` row
    creation shared by both entry points that add a paper to a user's library: a
    manual upload and a server-side import from an external search result. Neither
    path should bypass the other's checksum dedupe or size limit.
    """
    checksum = sha256(contents).hexdigest()
    existing_paper = get_existing_paper_by_checksum(db, checksum)
    if existing_paper is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"This PDF has already been uploaded as '{existing_paper.original_filename}'",
        )

    max_size_bytes = settings.max_pdf_upload_size_mb * 1024 * 1024
    if len(contents) > max_size_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"'{original_filename}' exceeds the {settings.max_pdf_upload_size_mb} MB limit",
        )

    safe_filename = Path(_sanitize_filename_component(original_filename, fallback="paper.pdf")).name
    if not safe_filename.lower().endswith(".pdf"):
        safe_filename = f"{safe_filename}.pdf"

    upload_dir = Path(settings.paper_upload_dir) / f"user-{current_user.id}"
    upload_dir.mkdir(parents=True, exist_ok=True)

    storage_filename = f"{uuid4().hex}-{safe_filename}"
    storage_path = upload_dir / storage_filename
    storage_path.write_bytes(contents)

    resolved_title = (
        title.strip()[:255]
        if title and title.strip()
        else (Path(safe_filename).stem.replace("_", " ").replace("-", " ").strip() or "Untitled paper")
    )

    paper = UploadedPaper(
        user_id=current_user.id,
        title=resolved_title,
        original_filename=safe_filename,
        storage_path=str(storage_path),
        mime_type=mime_type,
        file_size_bytes=len(contents),
        checksum_sha256=checksum,
        processing_status="uploaded",
        paper_metadata={"upload_dir": str(upload_dir), **extra_metadata},
    )

    db.add(paper)
    db.commit()
    db.refresh(paper)
    return paper


async def save_uploaded_pdf(
    db: Session,
    current_user: User,
    upload_file: UploadFile,
    settings: Settings,
) -> UploadedPaper:
    if upload_file.content_type not in ALLOWED_PDF_MIME_TYPES and not (upload_file.filename or "").lower().endswith(".pdf"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Only PDF files are supported")

    contents = await upload_file.read()
    return _persist_new_paper(
        db,
        current_user,
        settings,
        contents,
        original_filename=upload_file.filename or "paper.pdf",
        mime_type=upload_file.content_type,
        extra_metadata={"source": "pdf-upload"},
    )


def save_imported_pdf(
    db: Session,
    current_user: User,
    settings: Settings,
    contents: bytes,
    *,
    title: str,
    source: str,
    external_id: str,
    external_url: str | None,
) -> UploadedPaper:
    """Persists a PDF downloaded server-side from an external search result (arXiv /
    Semantic Scholar) through the identical dedupe/size/storage path a manual upload
    goes through, so it enters the same chunk -> embed -> ready pipeline without any
    duplicated logic.
    """
    return _persist_new_paper(
        db,
        current_user,
        settings,
        contents,
        original_filename=f"{title or external_id}.pdf",
        mime_type="application/pdf",
        title=title,
        extra_metadata={
            "source": f"{source}-import",
            "external_id": external_id,
            "external_url": external_url,
        },
    )