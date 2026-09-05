from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from app.models.uploaded_paper import UploadedPaper
from app.schemas.paper import ExternalPaperResult
from app.services import external_paper_service
from app.utils.time import utc_now

logger = logging.getLogger("app.citation_graph")

MAX_ENTRIES_PER_SIDE = 25
MAX_RELATED_SUGGESTIONS = 5


def get_or_refresh_citation_graph(db: Session, paper: UploadedPaper, force: bool = False) -> dict | None:
    """Returns the cached citation-graph payload for `paper` (`{fetched_at,
    citation_count, reference_count, references, citing_papers}`), fetching it from
    Semantic Scholar first if it's missing or `force` is set, then caching the
    result on `paper.paper_metadata` — the same cache-on-the-paper pattern the
    Phase 3 summary feature uses, so this isn't refetched on every page view.

    Returns None when the paper has no external identity to look up (a manual
    upload never went through arXiv/Semantic Scholar) or Semantic Scholar has
    never indexed it — both are legitimate "not available" outcomes, not errors.
    """
    metadata = paper.paper_metadata or {}
    cached = metadata.get("citation_graph")
    if cached and not force:
        return cached

    source = metadata.get("source") or ""
    external_id = metadata.get("external_id")
    if not external_id:
        return cached

    lookup_source = "semantic_scholar" if source.startswith("semantic_scholar") else "arxiv"
    graph = external_paper_service.fetch_semantic_scholar_paper_graph(lookup_source, external_id)
    if graph is None:
        return cached

    payload = _build_payload(graph)
    paper.paper_metadata = {**metadata, "citation_graph": payload}
    db.commit()
    db.refresh(paper)
    return payload


def suggest_related_papers(citation_graph: dict | None) -> list[ExternalPaperResult]:
    """Ranks the cached graph's references + citing papers into a small "related
    papers" list: importable results first, then by citation count. A directly
    cited/citing paper is about as "related" as it gets without building a real
    recommender, and unlike a cross-library keyword comparison, it's guaranteed to
    be an external paper the user can actually import.
    """
    if not citation_graph:
        return []

    candidates = [
        ExternalPaperResult(**entry)
        for entry in (citation_graph.get("references") or []) + (citation_graph.get("citing_papers") or [])
    ]

    seen: set[tuple[str, str]] = set()
    unique: list[ExternalPaperResult] = []
    for candidate in candidates:
        key = (candidate.source, candidate.external_id)
        if key in seen:
            continue
        seen.add(key)
        unique.append(candidate)

    unique.sort(key=lambda candidate: (not candidate.importable, -(candidate.citation_count or 0)))
    return unique[:MAX_RELATED_SUGGESTIONS]


def _build_payload(graph: dict) -> dict:
    references = _map_entries(graph.get("references") or [])
    citing_papers = _map_entries(graph.get("citations") or [])
    return {
        "fetched_at": utc_now().isoformat(),
        "citation_count": graph.get("citationCount"),
        "reference_count": graph.get("referenceCount"),
        "references": [entry.model_dump() for entry in references[:MAX_ENTRIES_PER_SIDE]],
        "citing_papers": [entry.model_dump() for entry in citing_papers[:MAX_ENTRIES_PER_SIDE]],
    }


def _map_entries(items: list[dict]) -> list[ExternalPaperResult]:
    mapped = []
    for item in items:
        entry = external_paper_service.map_citation_graph_entry(item)
        if entry is not None:
            mapped.append(entry)
    return mapped
