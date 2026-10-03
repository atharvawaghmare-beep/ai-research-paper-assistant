from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.config.database import get_db
from app.config.settings import get_settings
from app.models.user import User
from app.models.notification import Notification
from app.rate_limit import limiter
from app.schemas.notification import NotificationJobResponse, NotificationListResponse, NotificationRead
from app.services import notification_service

router = APIRouter(prefix="/notifications")
settings = get_settings()


@router.get("", response_model=NotificationListResponse)
def list_user_notifications(
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> NotificationListResponse:
    notifications = notification_service.list_notifications(db, current_user, limit)
    return NotificationListResponse(
        notifications=[NotificationRead.model_validate(notification) for notification in notifications],
        unread_count=notification_service.unread_count(db, current_user),
    )


@router.get("/unread-count")
def get_unread_count(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, int]:
    return {"unread_count": notification_service.unread_count(db, current_user)}


@router.post("/check", response_model=NotificationJobResponse)
@limiter.limit("2/hour")
def run_notification_check(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> NotificationJobResponse:
    created_count, skipped_count, warnings = notification_service.create_notifications_for_user(
        db, current_user, settings=settings
    )
    return NotificationJobResponse(
        created_count=created_count,
        skipped_count=skipped_count,
        warnings=warnings,
    )


@router.post("/{notification_id}/read", response_model=NotificationRead)
def mark_notification_read(
    notification_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> NotificationRead:
    notification = db.query(Notification).filter(
        Notification.id == notification_id,
        Notification.user_id == current_user.id,
    ).first()
    if notification is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Notification not found")

    notification.is_read = True
    db.commit()
    db.refresh(notification)
    return NotificationRead.model_validate(notification)
