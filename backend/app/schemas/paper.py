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
