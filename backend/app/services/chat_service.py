from __future__ import annotations

from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.chat_message import ChatMessage
from app.models.chat_session import ChatSession, chat_session_papers
from app.models.uploaded_paper import UploadedPaper
from app.models.user import User
from app.services.llm_service import LLMGenerationError
from app.services.paper_service import get_user_paper_by_id
from app.services.rag_service import answer_question


def get_user_session(db: Session, current_user: User, paper_id: int, session_id: int) -> ChatSession:
    """Fetch a session the user owns that includes `paper_id` among its linked
    papers — not necessarily the one it was originally created (anchored) under,
    so a multi-paper session is reachable from any of its papers' pages."""
    statement = (
        select(ChatSession)
        .join(chat_session_papers, chat_session_papers.c.session_id == ChatSession.id)
        .where(
            ChatSession.id == session_id,
            ChatSession.user_id == current_user.id,
            chat_session_papers.c.paper_id == paper_id,
        )
    )
    session = db.scalar(statement)
    if session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chat session not found")
    return session


def list_user_sessions(db: Session, current_user: User, paper_id: int) -> list[ChatSession]:
    statement = (
        select(ChatSession)
        .join(chat_session_papers, chat_session_papers.c.session_id == ChatSession.id)
        .where(ChatSession.user_id == current_user.id, chat_session_papers.c.paper_id == paper_id)
        .order_by(ChatSession.updated_at.desc())
    )
    return list(db.scalars(statement))


def _require_ready(paper: UploadedPaper) -> None:
    if paper.processing_status != "ready":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f'Paper "{paper.title}" is not ready for chat yet (status: {paper.processing_status})',
        )


def _create_session(
    db: Session,
    current_user: User,
    anchor_paper: UploadedPaper,
    additional_paper_ids: list[int],
    title: str,
) -> tuple[ChatSession, list[UploadedPaper]]:
    """Create a new session anchored at `anchor_paper`, plus any additional
    papers (Phase 4 multi-paper Q&A) — each must be owned by the user and ready,
    same as the anchor. Returns the session and the full resolved paper list."""
    papers = [anchor_paper]
    seen_ids = {anchor_paper.id}
    for other_id in additional_paper_ids:
        if other_id in seen_ids:
            continue
        other_paper = get_user_paper_by_id(db, current_user, other_id)
        _require_ready(other_paper)
        papers.append(other_paper)
        seen_ids.add(other_id)

    session = ChatSession(user_id=current_user.id, paper_id=anchor_paper.id, title=title)
    db.add(session)
    db.commit()
    db.refresh(session)

    db.execute(chat_session_papers.insert().values([{"session_id": session.id, "paper_id": pid} for pid in seen_ids]))
    db.commit()

    return session, papers


def send_message(
    db: Session,
    current_user: User,
    paper_id: int,
    message: str,
    session_id: int | None,
    additional_paper_ids: list[int] | None = None,
) -> tuple[ChatSession, ChatMessage, ChatMessage]:
    anchor_paper = get_user_paper_by_id(db, current_user, paper_id)
    _require_ready(anchor_paper)

    if session_id is not None:
        session = get_user_session(db, current_user, paper_id, session_id)
        papers = list(session.papers) or [anchor_paper]  # existing session's fixed paper set
    else:
        session, papers = _create_session(
            db, current_user, anchor_paper, additional_paper_ids or [], title=message[:80] or "New chat"
        )

    history_statement = (
        select(ChatMessage).where(ChatMessage.session_id == session.id).order_by(ChatMessage.message_index)
    )
    history_rows = list(db.scalars(history_statement))
    history = [(row.role, row.content) for row in history_rows]
    next_index = (history_rows[-1].message_index + 1) if history_rows else 0

    user_message = ChatMessage(
        session_id=session.id,
        message_index=next_index,
        role="user",
        content=message,
    )
    db.add(user_message)
    db.commit()
    db.refresh(user_message)

    try:
        answer_text, citations = answer_question(db, papers, message, history)
    except LLMGenerationError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"The AI assistant is unavailable right now: {error}",
        ) from error

    assistant_message = ChatMessage(
        session_id=session.id,
        message_index=next_index + 1,
        role="assistant",
        content=answer_text,
        citations=citations or None,
    )
    db.add(assistant_message)
    session.last_message_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(assistant_message)

    return session, user_message, assistant_message
