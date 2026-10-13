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
    is_user_authored: bool


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


class OutlineSectionSchema(BaseModel):
    heading: str
    page_start: int
    page_end: int


class SectionSummarySchema(BaseModel):
    heading: str
    page_start: int
    page_end: int
    summary: str


class EquationExplanationSchema(BaseModel):
    page: int
    raw_text: str = Field(description="The equation as extracted from the PDF, verbatim — PDF text extraction of math is lossy, so this may not render cleanly, but it is never altered.")
    confidence: Literal["numbered", "heuristic"] = Field(
        description="'numbered' when a standalone equation-number marker like '(3)' was found "
        "(the standard LaTeX-compiled convention, high confidence); 'heuristic' when it was "
        "flagged only by a dense cluster of math symbols/Greek letters (lower confidence)."
    )
    explanation: str
    latex: str | None = Field(
        default=None,
        description="An LLM best-effort LaTeX reconstruction for display (e.g. via KaTeX) — "
        "never the paper's verbatim text, and the frontend must label it as a reconstruction.",
    )


class PaperSummaryResponse(BaseModel):
    status: Literal["pending", "generating", "ready", "failed"]
    cached: bool
    generated_at: datetime | None
    outline: list[OutlineSectionSchema] = Field(default_factory=list)
    section_summaries: list[SectionSummarySchema] = Field(default_factory=list)
    overall_summary: str | None = None
    equations: list[EquationExplanationSchema] = Field(default_factory=list)
    methods: list[str] = Field(default_factory=list)
    error: str | None = None
    # Phase 18: "language" is what's actually shown in the fields above right
    # now — "en" until a requested translation is actually ready, at which
    # point it flips to the target language. `translation_status` is None
    # when no ?lang= was requested at all; otherwise it's the background
    # translation job's own status, polled the same way summary_status is.
    language: str = "en"
    translation_status: Literal["pending", "generating", "ready", "failed"] | None = None


class ConceptExplanationRequest(BaseModel):
    term: str = Field(min_length=1, max_length=200)
    difficulty: Literal["beginner", "intermediate", "expert"] = "intermediate"
    lang: str | None = None


class ConceptExplanationResponse(BaseModel):
    term: str
    difficulty: Literal["beginner", "intermediate", "expert"]
    explanation: str
    citations: list[dict]
    language: str = "en"


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


class FormatTemplateInfo(BaseModel):
    id: str
    name: str
    description: str


class FormatChecklistItem(BaseModel):
    id: str
    name: str
    required: bool
    present: bool
    heading: str | None = None
    page_start: int | None = None
    page_end: int | None = None


class FormatReviewFinding(BaseModel):
    severity: Literal["missing", "issue", "suggestion"]
    section: str
    page: int | None = None
    message: str
    fix: str | None = None


class FormatReviewResponse(BaseModel):
    status: Literal["pending", "generating", "ready", "failed"]
    cached: bool
    template_id: str
    template_name: str
    checklist: list[FormatChecklistItem] = Field(default_factory=list)
    findings: list[FormatReviewFinding] = Field(default_factory=list)
    generated_at: datetime | None = None
    error: str | None = None
    # Phase 18 — same meaning as on PaperSummaryResponse: "language" is what's
    # actually shown in `findings` right now; `translation_status` is None
    # unless a `lang` was requested for this call.
    language: str = "en"
    translation_status: Literal["pending", "generating", "ready", "failed"] | None = None


class PaperSectionTranslationResponse(BaseModel):
    status: Literal["pending", "generating", "ready", "failed"]
    cached: bool
    language: str
    section_index: int
    heading: str | None = None
    translated_heading: str | None = None
    translated_text: str | None = None
    page_start: int | None = None
    page_end: int | None = None
    generated_at: datetime | None = None
    error: str | None = None


class PaperCompareEntry(BaseModel):
    paper: UploadedPaperRead
    summary: str
    cached: bool
    generated_at: datetime | None


class PaperCompareResponse(BaseModel):
    papers: list[PaperCompareEntry]
