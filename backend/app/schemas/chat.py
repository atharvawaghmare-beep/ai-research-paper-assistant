from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.paper import UploadedPaperRead


class ChatMessageCreate(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    session_id: int | None = None
    # Only used when creating a new session (session_id omitted) — extends the
    # session's retrieval pool beyond the URL's anchor paper (Phase 4 multi-paper
    # Q&A). Ignored when continuing an existing session; its paper set is fixed
    # at creation.
    additional_paper_ids: list[int] = Field(default_factory=list)
    # Phase 18: retrieval and the stored message content always stay English —
    # only the answer actually displayed for this turn is translated, and only
    # on demand (not persisted; the same question asked again without `lang`
    # shows the original English answer untouched).
    lang: str | None = None


class ChatMessageRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    session_id: int
    message_index: int
    role: str
    content: str
    citations: list[dict] | None
    created_at: datetime
    # Set only on the assistant message of a turn where `lang` was requested
    # and translation succeeded — citations are extracted from (and still
    # refer to) the English `content` either way.
    translated_content: str | None = None


class ChatSessionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    paper_id: int | None
    title: str
    status: str
    created_at: datetime
    updated_at: datetime
    last_message_at: datetime | None
    papers: list[UploadedPaperRead]


class ChatSessionWithMessages(ChatSessionRead):
    messages: list[ChatMessageRead]


class ChatTurnResponse(BaseModel):
    session_id: int
    user_message: ChatMessageRead
    assistant_message: ChatMessageRead
