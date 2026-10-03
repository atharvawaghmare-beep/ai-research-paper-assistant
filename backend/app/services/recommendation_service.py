from __future__ import annotations

from collections import Counter

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config.settings import Settings, get_settings
from app.models.uploaded_paper import UploadedPaper
from app.models.user import User
from app.schemas.paper import ExternalPaperResult
from app.services import external_paper_service
from app.services.classification_service import get_classification_service
from app.services.paper_insight_service import get_cached_insight
from app.services.external_paper_service import ARXIV_CATEGORIES


def _paper_categories(paper: UploadedPaper) -> list[str]:
    metadata = paper.paper_metadata or {}
    categories = metadata.get("categories", [])
    return [category for category in categories if category in ARXIV_CATEGORIES]


def build_interest_profile(papers: list[UploadedPaper]) -> dict[str, float]:
    """Aggregates paper categories with a modest view recency weight.

    Papers without arXiv category metadata (manual uploads, pre-Phase-14
    imports) are classified locally instead. The classifier is fed the LLM-
    extracted abstract when the insight step has produced one — title-only
    classification is noticeably weaker (a tokenisation paper classified from
    its title alone came back cs.AI/cs.IR; with its abstract, cs.CL at 0.65).
    """
    profile: Counter[str] = Counter()
    classifier = get_classification_service()
    for paper in papers:
        weight = 2.0 if paper.last_viewed_at is not None else 1.0
        categories = _paper_categories(paper)
        if not categories:
            insight = get_cached_insight(paper)
            abstract = insight["abstract"] if insight else ""
            categories = [
                category
                for category, _ in classifier.predict_categories(paper.title, abstract, threshold=0.3)[:3]
            ]
        for category in categories:
            profile[category] += weight

    total = sum(profile.values())
    if not total:
        return {}
    return {category: round(score / total, 4) for category, score in profile.most_common()}


def get_recommendations(
    db: Session,
    current_user: User,
    *,
    limit: int = 10,
    settings: Settings | None = None,
) -> tuple[list[ExternalPaperResult], dict[str, float], list[str], str | None]:
    settings = settings or get_settings()
    papers = list(
        db.scalars(select(UploadedPaper).where(UploadedPaper.user_id == current_user.id))
    )
    interest_profile = build_interest_profile(papers)
    if not interest_profile:
        return [], {}, [], "Import or view papers with arXiv categories to build recommendations."

    top_categories = list(interest_profile)[:3]
    # Scores are normalized by the weight mass of the categories actually
    # queried, so a score reads as "weighted classifier confidence on the
    # categories you care about" in [0, 1] whether the library spans 2
    # categories or 6. Without this, a broader profile (weights 0.25/0.25/0.17
    # instead of 0.33 x 3) silently capped every score at ~0.67 and the
    # notification threshold (0.35) became unreachable.
    top_weight = sum(interest_profile[category] for category in top_categories) or 1.0
    candidates, warnings = external_paper_service.search_recent_category_papers(
        top_categories,
        min(max(limit * 4, 20), 50),
        settings,
    )
    imported_ids = {
        (metadata.get("source", "").removesuffix("-import"), metadata.get("external_id"))
        for paper in papers
        if (metadata := (paper.paper_metadata or {})).get("external_id")
    }

    classifier = get_classification_service()
    scored: list[ExternalPaperResult] = []
    for candidate in candidates:
        if (candidate.source, candidate.external_id) in imported_ids:
            continue
        predictions = classifier.predict_categories(candidate.title, candidate.abstract or "", threshold=0.0)
        category_scores = dict(predictions)
        score = (
            sum(interest_profile.get(category, 0.0) * category_scores.get(category, 0.0) for category in top_categories)
            / top_weight
        )
        if score <= 0:
            continue
        candidate.recommendation_score = round(score, 4)
        candidate.matched_categories = [
            category for category in top_categories if category_scores.get(category, 0.0) >= 0.3
        ]
        scored.append(candidate)

    scored.sort(key=lambda paper: paper.recommendation_score or 0.0, reverse=True)
    return scored[:limit], interest_profile, warnings, None