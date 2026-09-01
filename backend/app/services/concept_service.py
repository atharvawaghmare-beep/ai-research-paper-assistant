from __future__ import annotations

from typing import Literal

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.uploaded_paper import UploadedPaper
from app.services.citation_utils import CITATION_INSTRUCTION, extract_citations, format_context_excerpts
from app.services.llm_service import LLMGenerationError, generate_chat_completion
from app.services.retrieval_service import retrieve_chunks

Difficulty = Literal["beginner", "intermediate", "expert"]

# Same retrieval as chat Q&A — only the system prompt varies by difficulty, per
# CLAUDE.md's Phase 3 instruction ("same retrieval, different system prompt").
DIFFICULTY_INSTRUCTIONS: dict[Difficulty, str] = {
    "beginner": (
        "Explain this to someone with no background in the field. Avoid jargon; when "
        "a technical term is unavoidable, define it in plain language the moment you "
        "use it. A short, concrete analogy is welcome if it genuinely helps. Keep it "
        "to a few short sentences."
    ),
    "intermediate": (
        "Explain this to a reader with general STEM/CS background but no special "
        "expertise in this particular research area. Standard technical vocabulary is "
        "fine; briefly clarify anything specific to this paper's approach."
    ),
    "expert": (
        "Explain this to a reader who is already an expert in this research area. Be "
        "precise and technical, reference the paper's specific formulation or notation "
        "where relevant, and skip definitions of foundational concepts."
    ),
}

NO_CONTEXT_EXPLANATION = "I couldn't find \"{term}\" discussed anywhere in this paper."


def explain_concept(
    db: Session,
    paper: UploadedPaper,
    term: str,
    difficulty: Difficulty,
) -> tuple[str, list[dict]]:
    """Explain `term` as used in `paper`, at the given difficulty level."""
    if paper.processing_status != "ready":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Paper is not ready yet (status: {paper.processing_status})",
        )

    chunks = retrieve_chunks(db, paper_ids=[paper.id], query=term)
    if not chunks:
        return NO_CONTEXT_EXPLANATION.format(term=term), []

    context = format_context_excerpts(chunks)
    system_prompt = (
        f'You are a research paper assistant explaining a concept from the paper "{paper.title}" '
        f"using ONLY the excerpts provided below. {DIFFICULTY_INSTRUCTIONS[difficulty]} "
        f"{CITATION_INSTRUCTION} If the excerpts don't actually cover this term, say so "
        "rather than guessing or using outside knowledge."
    )
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": f'Excerpts:\n\n{context}\n\nExplain: "{term}"'},
    ]

    try:
        explanation = generate_chat_completion(messages)
    except LLMGenerationError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"The AI assistant is unavailable right now: {error}",
        ) from error

    citations = extract_citations(explanation, chunks)
    return explanation, citations
