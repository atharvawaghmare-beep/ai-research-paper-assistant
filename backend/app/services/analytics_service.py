from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.chat_message import ChatMessage
from app.models.chat_session import ChatSession, chat_session_papers
from app.models.uploaded_paper import UploadedPaper
from app.models.user import User
from app.schemas.analytics import ActivityPoint, AnalyticsSummaryResponse, MostActivePaper, MostCitedChunk

ACTIVITY_WINDOW_DAYS = 14
MOST_CITED_LIMIT = 5

# "Time spent per paper" (from CLAUDE.md's Phase 11 list) is deliberately not
# implemented: the only view-related signal this app tracks is `last_viewed_at`,
# a single timestamp per paper (Phase 8) — there's no view-start/view-end pair to
# derive a duration from. Faking a number from a single timestamp would be worse
# than not showing the metric at all, so it's skipped per CLAUDE.md's own
# instruction ("skip this metric rather than faking it").


def get_analytics_summary(db: Session, current_user: User) -> AnalyticsSummaryResponse:
    total_papers = (
        db.scalar(select(func.count()).select_from(UploadedPaper).where(UploadedPaper.user_id == current_user.id))
        or 0
    )

    total_questions_asked = (
        db.scalar(
            select(func.count())
            .select_from(ChatMessage)
            .join(ChatSession, ChatMessage.session_id == ChatSession.id)
            .where(ChatSession.user_id == current_user.id, ChatMessage.role == "user")
        )
        or 0
    )

    return AnalyticsSummaryResponse(
        total_papers=total_papers,
        total_questions_asked=total_questions_asked,
        most_active_paper=_most_active_paper(db, current_user),
        most_cited_chunks=_most_cited_chunks(db, current_user),
        activity_by_day=_activity_by_day(db, current_user),
    )


def _most_active_paper(db: Session, current_user: User) -> MostActivePaper | None:
    """"Most active" = the paper linked to the most user questions across its chat
    sessions. A multi-paper session's (Phase 4) questions count toward every paper
    it's linked to — this ranks papers by how much each was talked about, it isn't
    a strict partition of `total_questions_asked`.
    """
    statement = (
        select(chat_session_papers.c.paper_id, func.count().label("question_count"))
        .select_from(ChatMessage)
        .join(ChatSession, ChatMessage.session_id == ChatSession.id)
        .join(chat_session_papers, chat_session_papers.c.session_id == ChatSession.id)
        .where(ChatSession.user_id == current_user.id, ChatMessage.role == "user")
        .group_by(chat_session_papers.c.paper_id)
        .order_by(func.count().desc())
        .limit(1)
    )
    row = db.execute(statement).first()
    if row is None:
        return None

    paper_id, question_count = row
    paper = db.get(UploadedPaper, paper_id)
    if paper is None:
        return None
    return MostActivePaper(paper_id=paper_id, title=paper.title, questions_asked=question_count)


def _most_cited_chunks(db: Session, current_user: User) -> list[MostCitedChunk]:
    """Aggregates citation frequency straight from `ChatMessage.citations` — each
    stored citation already embeds paper_id/paper_title/page range, so no join back
    to `document_chunks` is needed. Done in Python rather than a JSONB aggregate
    query: at this project's scale (one user's own chat history, not a citation
    -analytics product) that's cheap, and it keeps the logic readable instead of a
    `jsonb_array_elements` query.
    """
    statement = select(ChatMessage.citations).join(ChatSession, ChatMessage.session_id == ChatSession.id).where(
        ChatSession.user_id == current_user.id,
        ChatMessage.role == "assistant",
        ChatMessage.citations.is_not(None),
    )

    counts: Counter[int] = Counter()
    first_seen: dict[int, dict] = {}
    for (citations,) in db.execute(statement):
        for citation in citations or []:
            chunk_id = citation.get("chunk_id")
            if chunk_id is None:
                continue
            counts[chunk_id] += 1
            first_seen.setdefault(chunk_id, citation)

    return [
        MostCitedChunk(
            paper_id=first_seen[chunk_id]["paper_id"],
            paper_title=first_seen[chunk_id]["paper_title"],
            page_start=first_seen[chunk_id]["page_start"],
            page_end=first_seen[chunk_id]["page_end"],
            times_cited=count,
        )
        for chunk_id, count in counts.most_common(MOST_CITED_LIMIT)
    ]


def _activity_by_day(db: Session, current_user: User) -> list[ActivityPoint]:
    since = datetime.now(timezone.utc) - timedelta(days=ACTIVITY_WINDOW_DAYS - 1)
    day_column = func.date(ChatMessage.created_at)
    statement = (
        select(day_column.label("day"), func.count().label("question_count"))
        .select_from(ChatMessage)
        .join(ChatSession, ChatMessage.session_id == ChatSession.id)
        .where(ChatSession.user_id == current_user.id, ChatMessage.role == "user", ChatMessage.created_at >= since)
        .group_by(day_column)
    )
    counts_by_day = {row.day: row.question_count for row in db.execute(statement)}

    today = datetime.now(timezone.utc).date()
    days = [today - timedelta(days=offset) for offset in range(ACTIVITY_WINDOW_DAYS - 1, -1, -1)]
    return [ActivityPoint(date=day.isoformat(), questions_asked=counts_by_day.get(day, 0)) for day in days]
