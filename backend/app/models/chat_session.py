from __future__ import annotations

from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, String, Table
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.utils.time import utc_now

# Many-to-many: which papers a chat session draws retrieval context from (Phase 4).
# A session's `paper_id` column below is kept as the "anchor" paper it was created
# under (matches the /papers/{paper_id}/chat URL shape and existing single-paper
# sessions), but is always also present as a row here — retrieval and ownership
# checks go through this table uniformly rather than special-casing the anchor.
chat_session_papers = Table(
    "chat_session_papers",
    Base.metadata,
    Column("session_id", ForeignKey("chat_sessions.id", ondelete="CASCADE"), primary_key=True),
    Column("paper_id", ForeignKey("uploaded_papers.id", ondelete="CASCADE"), primary_key=True),
)


class ChatSession(Base):
    __tablename__ = "chat_sessions"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    paper_id: Mapped[int | None] = mapped_column(ForeignKey("uploaded_papers.id", ondelete="SET NULL"), index=True, nullable=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(50), default="active", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)
    last_message_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped[User] = relationship(back_populates="chat_sessions")
    paper: Mapped[UploadedPaper | None] = relationship(back_populates="chat_sessions")
    papers: Mapped[list[UploadedPaper]] = relationship(secondary=chat_session_papers)
    messages: Mapped[list[ChatMessage]] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
        order_by="ChatMessage.message_index",
    )