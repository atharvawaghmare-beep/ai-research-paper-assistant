from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from typing import TypeVar

from rank_bm25 import BM25Okapi
from sentence_transformers import CrossEncoder
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config.settings import get_settings
from app.models.document_chunk import DocumentChunk
from app.models.uploaded_paper import UploadedPaper
from app.services import embedding_service, faiss_index_service

settings = get_settings()

_TOKEN_RE = re.compile(r"[A-Za-z0-9]+")

DEFAULT_TOP_K = 5
DEFAULT_VECTOR_CANDIDATES = 200
DEFAULT_RERANK_CANDIDATES = 20
DEFAULT_VECTOR_WEIGHT = 0.5


@dataclass
class RetrievedChunk:
    chunk_id: int
    paper_id: int
    paper_title: str
    chunk_index: int
    content: str
    page_start: int
    page_end: int
    vector_score: float
    bm25_score: float
    hybrid_score: float
    rerank_score: float


@lru_cache
def get_cross_encoder() -> CrossEncoder:
    """Lazily load and cache the reranking cross-encoder for the process
    lifetime, same reasoning as embedding_service's model cache."""
    return CrossEncoder(settings.reranker_model_name)


def _tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall(text.lower())


def _normalize(values: dict[int, float]) -> dict[int, float]:
    if not values:
        return {}
    lo, hi = min(values.values()), max(values.values())
    if hi - lo < 1e-9:
        return dict.fromkeys(values, 0.0)
    return {key: (value - lo) / (hi - lo) for key, value in values.items()}


_HasPaperId = TypeVar("_HasPaperId", DocumentChunk, RetrievedChunk)


def _ensure_paper_coverage(chunks: list[_HasPaperId], paper_ids: list[int], limit: int) -> list[_HasPaperId]:
    """Truncate an already best-first-sorted list to `limit`, but when comparing
    multiple papers, don't let truncation silently drop every candidate from one
    of them — swap in that paper's best remaining candidate for the weakest kept
    one. Without this, a comparison question can end up citing only the
    higher-scoring paper and never mention the other, which defeats the point of
    a multi-paper query. No-op for a single-paper request."""
    if len(paper_ids) <= 1 or len(chunks) <= limit:
        return chunks[:limit]

    selected = chunks[:limit]
    covered = {chunk.paper_id for chunk in selected}
    missing = [pid for pid in paper_ids if pid not in covered]
    if not missing:
        return selected

    remaining = chunks[limit:]
    replace_at = len(selected) - 1  # bump the weakest kept candidate first, then next-weakest, ...
    for paper_id in missing:
        if replace_at < 0:
            break
        best = next((chunk for chunk in remaining if chunk.paper_id == paper_id), None)
        if best is not None:
            selected[replace_at] = best
            replace_at -= 1
    return selected


def retrieve_chunks(
    db: Session,
    paper_ids: list[int],
    query: str,
    top_k: int = DEFAULT_TOP_K,
    vector_candidates: int = DEFAULT_VECTOR_CANDIDATES,
    rerank_candidates: int = DEFAULT_RERANK_CANDIDATES,
    vector_weight: float = DEFAULT_VECTOR_WEIGHT,
) -> list[RetrievedChunk]:
    """Hybrid retrieval: vector search (FAISS) + BM25 over the target paper(s)'
    chunks, combined by a weighted sum, then reranked by a cross-encoder.

    The FAISS index is global (all papers), so step 1 searches it widely and
    step 2 restricts to the requested paper(s) via a DB query — simpler to
    keep in sync than a per-paper index, at the cost of an occasional miss if
    a paper's relevant chunk falls outside the wide candidate window (mitigated
    by `vector_candidates` defaulting high relative to a typical paper's chunk count).
    """
    query = query.strip()
    if not paper_ids or not query:
        return []

    # 1. Vector search, cast wide across the whole index.
    query_vector = embedding_service.embed_texts([query])[0]
    candidate_size = min(vector_candidates, faiss_index_service.index_size())
    vector_hits = faiss_index_service.search(query_vector, k=candidate_size) if candidate_size else []
    vector_scores_by_chunk_id = dict(vector_hits)

    # 2. Load every chunk for the target paper(s) — BM25 needs the full
    #    per-paper corpus, and this also resolves the chunk rows for step 1's hits.
    statement = select(DocumentChunk).where(DocumentChunk.paper_id.in_(paper_ids))
    chunks = list(db.scalars(statement))
    if not chunks:
        return []

    titles_by_paper_id = {
        paper.id: paper.title
        for paper in db.scalars(select(UploadedPaper).where(UploadedPaper.id.in_(paper_ids)))
    }

    # 3. BM25 over that paper's chunks.
    tokenized_corpus = [_tokenize(chunk.content) for chunk in chunks]
    bm25 = BM25Okapi(tokenized_corpus)
    bm25_scores = bm25.get_scores(_tokenize(query))
    bm25_by_chunk_id = {chunk.id: float(score) for chunk, score in zip(chunks, bm25_scores)}

    # 4. Combine: min-max normalize each score set within this candidate pool,
    #    then a simple weighted sum. A chunk BM25 alone found (or vector search
    #    alone found) still competes — the union is what makes this "hybrid".
    vector_norm = _normalize(vector_scores_by_chunk_id)
    bm25_norm = _normalize(bm25_by_chunk_id)
    hybrid_scores = {
        chunk.id: vector_weight * vector_norm.get(chunk.id, 0.0) + (1 - vector_weight) * bm25_norm.get(chunk.id, 0.0)
        for chunk in chunks
    }

    ranked = sorted(chunks, key=lambda c: hybrid_scores.get(c.id, 0.0), reverse=True)
    candidates = _ensure_paper_coverage(ranked, paper_ids, rerank_candidates)
    if not candidates:
        return []

    # 5. Cross-encoder reranking over the shortlist — this is what actually
    #    picks the final top_k, the hybrid score above only narrows the field.
    cross_encoder = get_cross_encoder()
    pairs = [(query, chunk.content) for chunk in candidates]
    rerank_scores = cross_encoder.predict(pairs)

    results = [
        RetrievedChunk(
            chunk_id=chunk.id,
            paper_id=chunk.paper_id,
            paper_title=titles_by_paper_id.get(chunk.paper_id, "Untitled paper"),
            chunk_index=chunk.chunk_index,
            content=chunk.content,
            page_start=chunk.page_start,
            page_end=chunk.page_end,
            vector_score=vector_scores_by_chunk_id.get(chunk.id, 0.0),
            bm25_score=bm25_by_chunk_id.get(chunk.id, 0.0),
            hybrid_score=hybrid_scores.get(chunk.id, 0.0),
            rerank_score=float(score),
        )
        for chunk, score in zip(candidates, rerank_scores)
    ]
    results.sort(key=lambda r: r.rerank_score, reverse=True)
    return _ensure_paper_coverage(results, paper_ids, top_k)
