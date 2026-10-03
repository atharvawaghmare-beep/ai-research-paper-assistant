from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class UploadedPaperRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    title: str
    original_filename: str
    storage_path: str
    mime_type: str | None
    file_size_bytes: int | None
    checksum_sha256: str | None
    processing_status: str
    page_count: int | None
    paper_metadata: dict | None
    uploaded_at: datetime
    processed_at: datetime | None
    summary_generated_at: datetime | None
    last_viewed_at: datetime | None


class ExtractedPage(BaseModel):
    page_number: int
    text: str


class ExtractedDocumentMetadata(BaseModel):
    paper_id: int
    title: str
    original_filename: str
    storage_path: str
    file_size_bytes: int | None
    total_pages: int
    pdf_metadata: dict


class ExtractedPdfResponse(BaseModel):
    metadata: ExtractedDocumentMetadata
    pages: list[ExtractedPage]


class PaperSummaryResponse(BaseModel):
    summary: str
    cached: bool
    generated_at: datetime | None


class ConceptExplanationRequest(BaseModel):
    term: str = Field(min_length=1, max_length=200)
    difficulty: Literal["beginner", "intermediate", "expert"] = "intermediate"


class ConceptExplanationResponse(BaseModel):
    term: str
    difficulty: Literal["beginner", "intermediate", "expert"]
    explanation: str
    citations: list[dict]


class ExternalPaperResult(BaseModel):
    source: Literal["arxiv", "semantic_scholar"]
    external_id: str
    title: str
    authors: list[str]
    abstract: str | None
    year: int | None
    pdf_url: str | None
    external_url: str | None
    importable: bool = Field(
        description="False when the provider has no downloadable PDF for this result "
        "(e.g. a Semantic Scholar paper with no open-access copy) — the frontend should "
        "disable import rather than let it fail server-side."
    )
    citation_count: int | None = Field(
        default=None,
        description="How many papers cite this one, when known. Only populated for "
        "citation-graph entries (references/citing papers/related suggestions) — "
        "plain arXiv/Semantic Scholar search results don't carry this.",
    )
    recommendation_score: float | None = None
    matched_categories: list[str] = Field(default_factory=list)
    categories: list[str] = Field(
        default_factory=list,
        description="Topic labels for this result: real arXiv category codes "
        "(e.g. 'cs.LG') for arXiv results, or Semantic Scholar's own "
        "field-of-study strings for Semantic Scholar results — display-only "
        "badges, not a taxonomy unified across both sources.",
    )


class PaperSearchResponse(BaseModel):
    query: str
    results: list[ExternalPaperResult]
    warnings: list[str] = Field(
        default_factory=list,
        description="Non-fatal problems (e.g. one provider timed out) — results may be partial.",
    )


class PaperRecommendationResponse(BaseModel):
    recommendations: list[ExternalPaperResult]
    interest_profile: dict[str, float]
    warnings: list[str] = Field(default_factory=list)
    message: str | None = None


class RelatedPapersQueryInfo(BaseModel):
    key_phrases: list[str] = Field(default_factory=list)
    categories: list[str] = Field(default_factory=list)
    abstract_source: str | None = Field(
        default=None,
        description='"llm" when the abstract came from the paper text, "opening_text" when the '
        "document had no abstract (slides, notes) and its opening was used instead.",
    )


class RelatedPapersResponse(BaseModel):
    paper_id: int
    results: list[ExternalPaperResult]
    query: RelatedPapersQueryInfo
    warnings: list[str] = Field(default_factory=list)
    message: str | None = None


class PaperImportRequest(BaseModel):
    source: Literal["arxiv", "semantic_scholar"]
    external_id: str = Field(min_length=1, max_length=200)
    pdf_url: str = Field(min_length=1, max_length=2048)
    title: str | None = Field(default=None, max_length=255)
    external_url: str | None = Field(default=None, max_length=2048)
    categories: list[str] = Field(default_factory=list, max_length=20)


class PaperCitationsResponse(BaseModel):
    paper_id: int
    available: bool = Field(
        description="False when this paper has no external identity to look up (a "
        "manual upload) or Semantic Scholar has no record for it — a legitimate "
        "outcome the frontend should show as 'not available', not an error."
    )
    citation_count: int | None
    reference_count: int | None
    references: list[ExternalPaperResult]
    citing_papers: list[ExternalPaperResult]
    related_papers: list[ExternalPaperResult] = Field(
        description="A small, explainable subset of references + citing papers, "
        "ranked importable-first then by citation count — a simple heuristic, not "
        "a real recommender."
    )
    fetched_at: datetime | None
    message: str | None = None


class PaperCompareEntry(BaseModel):
    paper: UploadedPaperRead
    summary: str
    cached: bool
    generated_at: datetime | None


class PaperCompareResponse(BaseModel):
    papers: list[PaperCompareEntry]
