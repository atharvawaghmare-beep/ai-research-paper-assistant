from __future__ import annotations

import logging
import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config.settings import Settings, get_settings
from app.models.uploaded_paper import UploadedPaper
from app.models.user import User
from app.schemas.paper import ExternalPaperResult
from app.services import external_paper_service, paper_insight_service
from app.services.classification_service import get_classification_service
from app.services.embedding_service import embed_texts
from app.services.external_paper_service import ARXIV_CATEGORIES, ExternalPaperError

logger = logging.getLogger("app.related_papers")

CANDIDATE_LIMIT = 40
# Category predictions below this don't narrow the arXiv query — a weak guess
# would just hide good matches from a neighbouring field.
CATEGORY_SCORE_THRESHOLD = 0.3
MAX_QUERY_CATEGORIES = 3
# An arXiv result this similar to the source paper *is* the source paper (the
# mentor uploaded a PDF of an arXiv paper); drop it rather than recommend it.
# Genuinely distinct papers in a tight sub-field top out around 0.8 in testing
# (BPE-tokeniser cluster: 0.78), while the same paper compared against its own
# LLM-paraphrased abstract scored 0.90 — hence the cut between them.
SELF_SIMILARITY_THRESHOLD = 0.88


def _normalize_title(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", title.lower()).strip()


def _is_source_paper(candidate: ExternalPaperResult, opening_text: str) -> bool:
    """A manual upload's stored title comes from PDF metadata or the filename,
    so it can't be trusted to match arXiv's record — but the paper's real
    title is always printed on its first page. If the candidate's title appears
    in the opening text, it's this paper."""
    title = _normalize_title(candidate.title)
    return len(title) >= 20 and title in opening_text


def _predict_query_categories(title: str, abstract: str, paper: UploadedPaper) -> list[str]:
    own = [c for c in (paper.paper_metadata or {}).get("categories", []) if c in ARXIV_CATEGORIES]
    if own:
        return own[:MAX_QUERY_CATEGORIES]
    predictions = get_classification_service().predict_categories(title, abstract, threshold=CATEGORY_SCORE_THRESHOLD)
    return [category for category, _ in predictions[:MAX_QUERY_CATEGORIES]]


def _fetch_candidates(
    phrases: list[str], categories: list[str], settings: Settings
) -> tuple[list[ExternalPaperResult], list[str]]:
    """Phrase search within the predicted categories; if that's too narrow to
    return anything, widen to all categories, then to the top phrases only.
    Each step is a real arXiv call, so stop at the first one that yields
    results."""
    warnings: list[str] = []
    attempts = [
        (phrases, categories),
        (phrases, []),
        (phrases[:3], []),
    ]
    seen_queries: set[str] = set()
    for attempt_phrases, attempt_categories in attempts:
        query = external_paper_service.build_arxiv_phrase_query(attempt_phrases, attempt_categories or None)
        if query in seen_queries:
            continue
        seen_queries.add(query)
        try:
            results = external_paper_service.search_arxiv(None, CANDIDATE_LIMIT, settings, search_query=query)
        except ExternalPaperError as error:
            logger.warning("related_arxiv_search_failed query=%r error=%s", query, error)
            return [], [f"arXiv is temporarily unavailable; related papers could not be fetched."]
        if results:
            return results, warnings
    return [], warnings


def get_related_papers(
    db: Session,
    current_user: User,
    paper: UploadedPaper,
    *,
    limit: int = 10,
    settings: Settings | None = None,
) -> tuple[list[ExternalPaperResult], dict, list[str], str | None]:
    """Content-based related papers for one paper in the user's library.

    Pipeline: LLM-extracted key phrases + abstract (paper_insight_service) ->
    arXiv phrase search, narrowed to the paper's predicted categories ->
    re-ranked by embedding cosine similarity between this paper's abstract and
    each candidate's title+abstract (same sentence-transformers model the
    retrieval index uses). Papers already in the user's library, and the
    source paper itself, are excluded.

    Returns (results, query_info, warnings, message). `message` is set when
    there's nothing to rank (insight unavailable / no arXiv matches) so the UI
    shows an explanation rather than an empty list.
    """
    settings = settings or get_settings()

    insight = paper_insight_service.get_cached_insight(paper) or paper_insight_service.extract_paper_insight(db, paper)
    if insight is None:
        return [], {}, [], "Could not extract this paper's key topics yet (the local AI model may be unavailable)."

    phrases: list[str] = insight["key_phrases"]
    abstract: str = insight["abstract"]
    categories = _predict_query_categories(paper.title, abstract, paper)
    query_info = {"key_phrases": phrases, "categories": categories, "abstract_source": insight.get("abstract_source")}

    candidates, warnings = _fetch_candidates(phrases, categories, settings)
    if not candidates:
        return [], query_info, warnings, (None if warnings else "arXiv has no papers matching this paper's key phrases.")

    # Exclusions: anything already in the library (by external id) and the source paper itself.
    library = list(db.scalars(select(UploadedPaper).where(UploadedPaper.user_id == current_user.id)))
    library_ids = {
        (metadata.get("source", "").removesuffix("-import"), metadata.get("external_id"))
        for entry in library
        if (metadata := (entry.paper_metadata or {})).get("external_id")
    }
    library_titles = {_normalize_title(entry.title) for entry in library}
    opening_text = _normalize_title(paper_insight_service.opening_text(db, paper))
    candidates = [
        c
        for c in candidates
        if (c.source, c.external_id) not in library_ids
        and _normalize_title(c.title) not in library_titles
        and not _is_source_paper(c, opening_text)
    ]
    if not candidates:
        return [], query_info, warnings, "Every matching arXiv paper is already in your library."

    # Semantic re-rank: cosine between this paper's abstract and each candidate.
    # embed_texts L2-normalizes, so a dot product is the cosine similarity.
    source_vector = embed_texts([f"{paper.title}. {abstract}"])[0]
    candidate_vectors = embed_texts([f"{c.title}. {c.abstract or ''}" for c in candidates])
    scored: list[ExternalPaperResult] = []
    for candidate, vector in zip(candidates, candidate_vectors):
        similarity = sum(a * b for a, b in zip(source_vector, vector))
        if similarity >= SELF_SIMILARITY_THRESHOLD:
            continue
        candidate.recommendation_score = round(similarity, 4)
        candidate.matched_categories = [c for c in categories if c in candidate.categories]
        scored.append(candidate)

    scored.sort(key=lambda c: c.recommendation_score or 0.0, reverse=True)
    return scored[:limit], query_info, warnings, None
