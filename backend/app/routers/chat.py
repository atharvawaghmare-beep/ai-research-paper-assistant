from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.config.database import get_db
from app.models.user import User
from app.rate_limit import limiter
from app.schemas.chat import ChatMessageCreate, ChatMessageRead, ChatSessionRead, ChatSessionWithMessages, ChatTurnResponse
from app.services import chat_service


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
    return ChatTurnResponse(
        session_id=session.id,
        user_message=ChatMessageRead.model_validate(user_message),
        assistant_message=ChatMessageRead.model_validate(assistant_message),
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
