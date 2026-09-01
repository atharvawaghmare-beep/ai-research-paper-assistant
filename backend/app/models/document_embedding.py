from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.utils.time import utc_now


class DocumentEmbedding(Base):
    __tablename__ = "document_embeddings"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    chunk_id: Mapped[int] = mapped_column(ForeignKey("document_chunks.id", ondelete="CASCADE"), unique=True, index=True, nullable=False)
    embedding_model: Mapped[str] = mapped_column(String(255), nullable=False)
    embedding_provider: Mapped[str | None] = mapped_column(String(100), nullable=True)
    embedding_dimensions: Mapped[int] = mapped_column(Integer, nullable=False)
    embedding_vector: Mapped[list[float] | None] = mapped_column(JSONB, nullable=True)
    vector_metadata: Mapped[dict | None] = mapped_column(JSONB, default=dict, nullable=True)
    embedding_status: Mapped[str] = mapped_column(String(50), default="pending", nullable=False)
    embedded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    chunk: Mapped[DocumentChunk] = relationship(back_populates="embedding")