from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.config.database import get_db
from app.models.user import User
from app.schemas.analytics import AnalyticsSummaryResponse
from app.services import analytics_service

router = APIRouter(prefix="/analytics")


@router.get("/summary", response_model=AnalyticsSummaryResponse)
def get_analytics_summary(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> AnalyticsSummaryResponse:
    return analytics_service.get_analytics_summary(db, current_user)
