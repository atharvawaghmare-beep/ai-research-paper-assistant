from __future__ import annotations

import logging

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config.settings import Settings, get_settings
from app.models.notification import Notification
from app.models.user import User
from app.services import recommendation_service

logger = logging.getLogger("app.notifications")


def unread_count(db: Session, current_user: User) -> int:
    return int(
        db.scalar(
            select(func.count(Notification.id)).where(
                Notification.user_id == current_user.id,
                Notification.is_read.is_(False),
            )
        )
        or 0
    )


def list_notifications(db: Session, current_user: User, limit: int = 20) -> list[Notification]:
    return list(
        db.scalars(
            select(Notification)
            .where(Notification.user_id == current_user.id)
            .order_by(Notification.created_at.desc())
            .limit(limit)
        )
    )


def create_notifications_for_user(
    db: Session,
    user: User,
    *,
    settings: Settings | None = None,
) -> tuple[int, int, list[str]]:
    settings = settings or get_settings()
    recommendations, _, warnings, _ = recommendation_service.get_recommendations(
        db, user, limit=settings.notification_candidate_limit, settings=settings
    )
    created_count = 0
    skipped_count = 0

    for paper in recommendations:
        if (paper.recommendation_score or 0.0) < settings.notification_score_threshold:
            skipped_count += 1
            continue

        exists = db.scalar(
            select(Notification.id).where(
                Notification.user_id == user.id,
                Notification.source == paper.source,
                Notification.external_id == paper.external_id,
            )
        )
        if exists is not None:
            skipped_count += 1
            continue

        categories = paper.matched_categories or paper.categories
        db.add(
            Notification(
                user_id=user.id,
                source=paper.source,
                external_id=paper.external_id,
                title=paper.title,
                message=(
                    f"New paper matched your interests in {', '.join(categories) or 'your research topics'}."
                ),
                external_url=paper.external_url,
                pdf_url=paper.pdf_url,
                categories=categories,
                recommendation_score=paper.recommendation_score,
            )
        )
        created_count += 1

    db.commit()
    return created_count, skipped_count, warnings


def run_alert_job(settings: Settings | None = None) -> dict[str, int | list[str]]:
    """Runs the alert scan for every active user; safe for scheduler/manual use."""
    from app.config.database import SessionLocal

    settings = settings or get_settings()
    db = SessionLocal()
    total_created = 0
    total_skipped = 0
    warnings: list[str] = []
    try:
        users = list(db.scalars(select(User).where(User.is_active.is_(True))))
        for user in users:
            try:
                created, skipped, user_warnings = create_notifications_for_user(
                    db, user, settings=settings
                )
                total_created += created
                total_skipped += skipped
                warnings.extend(user_warnings)
            except Exception as error:
                db.rollback()
                logger.exception("notification_scan_failed user_id=%s", user.id)
                warnings.append(f"User {user.id}: {error}")
    finally:
        db.close()

    return {"created_count": total_created, "skipped_count": total_skipped, "warnings": warnings}
