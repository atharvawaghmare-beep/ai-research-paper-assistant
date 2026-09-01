from __future__ import annotations

from functools import lru_cache

from sentence_transformers import SentenceTransformer

from app.config.settings import get_settings

settings = get_settings()


@lru_cache
def get_embedding_model() -> SentenceTransformer:
    """Lazily load and cache the Sentence Transformers model for the process
    lifetime — loading it is the expensive part, so this should only happen
    once regardless of how many papers get embedded."""
    return SentenceTransformer(settings.embedding_model_name)


def model_name() -> str:
    return settings.embedding_model_name


def embedding_dimensions() -> int:
    dimensions = get_embedding_model().get_sentence_embedding_dimension()
    if dimensions is None:
        raise RuntimeError(f"Could not determine embedding dimensions for model {settings.embedding_model_name!r}")
    return dimensions


def embed_texts(texts: list[str]) -> list[list[float]]:
    """Embed a batch of chunk texts. Vectors are L2-normalized so a plain dot
    product (FAISS IndexFlatIP) gives cosine similarity at query time."""
    if not texts:
        return []

    model = get_embedding_model()
    vectors = model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
    return [vector.tolist() for vector in vectors]
