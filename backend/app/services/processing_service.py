from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy.orm import Session

from app.config.database import SessionLocal
from app.models.document_chunk import DocumentChunk
from app.models.document_embedding import DocumentEmbedding
from app.models.uploaded_paper import UploadedPaper
from app.services import chunking_service, embedding_service, faiss_index_service

logger = logging.getLogger(__name__)


def process_uploaded_paper(paper_id: int) -> None:
    """Runs the chunk -> embed -> index pipeline for one uploaded paper, driving
    UploadedPaper.processing_status through uploaded -> chunking -> embedding ->
    ready (or failed) so the frontend can poll real progress.

    Intended to run as a FastAPI BackgroundTask: the request-scoped DB session is
    closed by the time a background task runs, so this opens its own session.
    """
    db = SessionLocal()
    try:
        paper = db.get(UploadedPaper, paper_id)
        if paper is None:
            logger.warning("process_uploaded_paper: paper %s not found", paper_id)
            return

        try:
            _mark_status(db, paper, "chunking")
            _chunk_paper(db, paper)

            _mark_status(db, paper, "embedding")
            _embed_paper(db, paper)

            paper.processing_status = "ready"
            paper.processed_at = datetime.now(timezone.utc)
            db.commit()
        except Exception:
            logger.exception("Processing pipeline failed for paper %s", paper_id)
            db.rollback()
            failed_paper = db.get(UploadedPaper, paper_id)
            if failed_paper is not None:
                failed_paper.processing_status = "failed"
                db.commit()
    finally:
        db.close()


def _mark_status(db: Session, paper: UploadedPaper, status: str) -> None:
    paper.processing_status = status
    db.commit()
    db.refresh(paper)


def _chunk_paper(db: Session, paper: UploadedPaper) -> list[DocumentChunk]:
    pdf_path = Path(paper.storage_path)
    if not pdf_path.exists():
        raise FileNotFoundError(f"Stored PDF not found for paper {paper.id}: {pdf_path}")

    # Delete any chunks (and, via DB-level ON DELETE CASCADE, embeddings + FAISS
    # entries) from a previous attempt so re-processing a paper is idempotent
    # rather than accumulating duplicates.
    existing_chunk_ids = [
        row.id for row in db.query(DocumentChunk.id).filter(DocumentChunk.paper_id == paper.id)
    ]
    if existing_chunk_ids:
        faiss_index_service.remove_chunk_vectors(existing_chunk_ids)
        db.query(DocumentChunk).filter(DocumentChunk.paper_id == paper.id).delete()
        db.commit()

    results, page_count = chunking_service.chunk_paper_text(pdf_path, paper_id=paper.id)
    if not results:
        raise ValueError(f"No extractable text found in paper {paper.id}")

    chunks = [
        DocumentChunk(
            paper_id=paper.id,
            chunk_index=result.chunk_index,
            content=result.content,
            token_count=result.token_count,
            character_start=result.character_start,
            character_end=result.character_end,
            page_start=result.page_start,
            page_end=result.page_end,
            chunk_hash=result.chunk_hash,
        )
        for result in results
    ]
    db.add_all(chunks)
    paper.page_count = page_count
    db.commit()
    for chunk in chunks:
        db.refresh(chunk)
    return chunks


def _embed_paper(db: Session, paper: UploadedPaper) -> None:
    chunks = list(
        db.query(DocumentChunk).filter(DocumentChunk.paper_id == paper.id).order_by(DocumentChunk.chunk_index)
    )
    if not chunks:
        return

    vectors = embedding_service.embed_texts([chunk.content for chunk in chunks])
    dimensions = embedding_service.embedding_dimensions()
    now = datetime.now(timezone.utc)

    embeddings = [
        DocumentEmbedding(
            chunk_id=chunk.id,
            embedding_model=embedding_service.model_name(),
            embedding_provider="sentence-transformers",
            embedding_dimensions=dimensions,
            embedding_vector=vector,
            vector_metadata={"paper_id": paper.id},
            embedding_status="ready",
            embedded_at=now,
        )
        for chunk, vector in zip(chunks, vectors)
    ]
    db.add_all(embeddings)
    db.commit()

    faiss_index_service.add_chunk_vectors(
        chunk_ids=[chunk.id for chunk in chunks],
        vectors=vectors,
        dimensions=dimensions,
    )
