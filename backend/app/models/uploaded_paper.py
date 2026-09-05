from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.utils.time import utc_now


class UploadedPaper(Base):
    __tablename__ = "uploaded_papers"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    storage_path: Mapped[str] = mapped_column(Text, nullable=False)
    mime_type: Mapped[str | None] = mapped_column(String(120), nullable=True)
    file_size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    checksum_sha256: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)
    processing_status: Mapped[str] = mapped_column(String(50), default="uploaded", nullable=False)
    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    paper_metadata: Mapped[dict | None] = mapped_column(JSONB, default=dict, nullable=True)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    summary_generated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_viewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)

    user: Mapped[User] = relationship(back_populates="uploaded_papers")
    chunks: Mapped[list[DocumentChunk]] = relationship(
        back_populates="paper",
        cascade="all, delete-orphan",
        order_by="DocumentChunk.chunk_index",
    )
    # No delete cascade here: this is the *anchor* relationship only (a session's
    # `paper_id`, matching the /papers/{id}/chat URL it was created under) — a
    # session can also be linked to other papers via `chat_session_papers` (Phase 4
    # multi-paper Q&A) that have nothing to do with this one being deleted. The FK
    # itself is `ondelete="SET NULL"` (see ChatSession.paper_id): deleting a paper
    # should just null out its anchor on any session, never delete the session,
    # since destroying it would also destroy messages that may cite other, still-
    # very-much-alive papers. An ORM-level delete cascade here previously
    # pre-empted that FK behavior and deleted the whole session instead — see
    # CLAUDE.md's "Known bug" note for how this was found.
    chat_sessions: Mapped[list[ChatSession]] = relationship(back_populates="paper")