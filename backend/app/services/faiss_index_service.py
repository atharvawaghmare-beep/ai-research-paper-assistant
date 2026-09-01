from __future__ import annotations

import threading
from pathlib import Path

import faiss
import numpy as np

from app.config.settings import get_settings

settings = get_settings()

# One global index shared across all papers, with chunk_id as the FAISS vector
# id (via IndexIDMap2) so retrieval can filter to a paper's chunk_ids after a
# search — simpler to keep in sync than one index file per paper.
_lock = threading.Lock()


def _index_path() -> Path:
    path = Path(settings.faiss_index_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _load_or_create_index(dimensions: int) -> faiss.Index:
    path = _index_path()
    if path.exists():
        return faiss.read_index(str(path))
    # Inner product over normalized vectors == cosine similarity.
    return faiss.IndexIDMap2(faiss.IndexFlatIP(dimensions))


def add_chunk_vectors(chunk_ids: list[int], vectors: list[list[float]], dimensions: int) -> None:
    """Add (or replace) vectors for the given chunk ids and persist to disk."""
    if not chunk_ids:
        return
    if len(chunk_ids) != len(vectors):
        raise ValueError("chunk_ids and vectors must be the same length")

    with _lock:
        index = _load_or_create_index(dimensions)
        ids = np.array(chunk_ids, dtype="int64")
        # Idempotent: drop any existing vectors for these ids first, so
        # re-processing a paper doesn't create duplicate entries.
        index.remove_ids(ids)
        matrix = np.array(vectors, dtype="float32")
        index.add_with_ids(matrix, ids)
        faiss.write_index(index, str(_index_path()))


def remove_chunk_vectors(chunk_ids: list[int]) -> None:
    """Remove vectors for the given chunk ids, if the index exists yet."""
    if not chunk_ids:
        return
    path = _index_path()
    if not path.exists():
        return

    with _lock:
        index = faiss.read_index(str(path))
        index.remove_ids(np.array(chunk_ids, dtype="int64"))
        faiss.write_index(index, str(path))


def search(query_vector: list[float], k: int) -> list[tuple[int, float]]:
    """Return up to k (chunk_id, similarity_score) pairs, best match first.
    Similarity is inner product over normalized vectors, i.e. cosine similarity."""
    path = _index_path()
    if not path.exists():
        return []

    with _lock:
        index = faiss.read_index(str(path))
    if index.ntotal == 0:
        return []

    k = min(k, index.ntotal)
    query = np.array([query_vector], dtype="float32")
    scores, ids = index.search(query, k)
    return [(int(chunk_id), float(score)) for chunk_id, score in zip(ids[0], scores[0]) if chunk_id != -1]


def index_size() -> int:
    """Total vectors currently stored in the index (0 if it doesn't exist yet)."""
    path = _index_path()
    if not path.exists():
        return 0
    return faiss.read_index(str(path)).ntotal
