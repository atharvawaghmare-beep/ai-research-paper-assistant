from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class NotificationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    source: str
    external_id: str
    title: str
    message: str
    external_url: str | None
    pdf_url: str | None
    categories: list[str]
    recommendation_score: float | None
    is_read: bool
    created_at: datetime


class NotificationListResponse(BaseModel):
    notifications: list[NotificationRead]
    unread_count: int


class NotificationJobResponse(BaseModel):
    created_count: int
    skipped_count: int
    warnings: list[str] = Field(default_factory=list)
