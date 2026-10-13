import logging

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.config.database import get_db
from app.models.user import User
from app.rate_limit import limiter
from app.schemas.chat import ChatMessageCreate, ChatMessageRead, ChatSessionRead, ChatSessionWithMessages, ChatTurnResponse
from app.services import chat_service, translation_service

logger = logging.getLogger("app.chat")

router = APIRouter(prefix="/papers/{paper_id}/chat")


@router.post("", response_model=ChatTurnResponse, status_code=status.HTTP_201_CREATED)
@limiter.limit("10/minute")
def send_chat_message(
    request: Request,
    paper_id: int,
    payload: ChatMessageCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ChatTurnResponse:
    session, user_message, assistant_message = chat_service.send_message(
        db, current_user, paper_id, payload.message, payload.session_id, payload.additional_paper_ids
    )

    assistant_read = ChatMessageRead.model_validate(assistant_message)
    if payload.lang:
        # Retrieval and the stored message both stay English (see
        # ChatMessageCreate.lang's docstring) — only this turn's displayed
        # answer is translated, synchronously, same as the explain endpoint.
        # Citations were already extracted from the English `content` above
        # and are untouched by this.
        if payload.lang not in translation_service.SUPPORTED_LANGUAGES:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Unsupported language: {payload.lang}")
        try:
            translated = translation_service.translate_text(assistant_message.content, payload.lang)
            assistant_read = assistant_read.model_copy(update={"translated_content": translated})
        except Exception:
            logger.exception("chat_answer_translation_failed paper_id=%s lang=%s", paper_id, payload.lang)
            # Fall back to showing the English answer rather than failing the
            # whole turn over a translation-only problem — the message was
            # already generated and persisted successfully above.

    return ChatTurnResponse(
        session_id=session.id,
        user_message=ChatMessageRead.model_validate(user_message),
        assistant_message=assistant_read,
    )


@router.get("", response_model=list[ChatSessionRead])
def list_chat_sessions(
    paper_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[ChatSessionRead]:
    return chat_service.list_user_sessions(db, current_user, paper_id)


@router.get("/{session_id}", response_model=ChatSessionWithMessages)
def get_chat_session(
    paper_id: int,
    session_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ChatSessionWithMessages:
    return chat_service.get_user_session(db, current_user, paper_id, session_id)
