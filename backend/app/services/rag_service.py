from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.uploaded_paper import UploadedPaper
from app.services.citation_utils import CITATION_INSTRUCTION, extract_citations, format_context_excerpts
from app.services.llm_service import generate_chat_completion
from app.services.retrieval_service import retrieve_chunks

SYSTEM_PROMPT = (
    "You are a research paper assistant. Answer the user's question using ONLY the "
    "information in the numbered context excerpts provided with the question. "
    f"{CITATION_INSTRUCTION} If the excerpts don't contain the answer, say you don't "
    "know rather than guessing or using outside knowledge."
)

# Appended to SYSTEM_PROMPT only when a session spans more than one paper (Phase 4).
# Each excerpt is already labeled with its source paper's title in this case (see
# format_context_excerpts) — this just tells the model to actually use that.
MULTI_PAPER_INSTRUCTION = (
    " These excerpts are drawn from more than one paper, each excerpt labeled with "
    "its source paper's title. When you answer, make clear which paper each claim "
    "comes from — don't blend them into one undifferentiated answer, especially for "
    "a comparison question."
)

MAX_HISTORY_MESSAGES = 6
NO_CONTEXT_ANSWER = (
    "I couldn't find any relevant content in these papers to answer that — try "
    "rephrasing, or confirm the papers have finished processing."
)


def answer_question(
    db: Session,
    papers: list[UploadedPaper],
    question: str,
    history: list[tuple[str, str]],
) -> tuple[str, list[dict]]:
    """Retrieve context for `question` across `papers` (one or more) and generate a
    grounded, cited answer. `history` is [(role, content), ...] oldest first."""
    paper_ids = [paper.id for paper in papers]
    chunks = retrieve_chunks(db, paper_ids=paper_ids, query=question)
    if not chunks:
        return NO_CONTEXT_ANSWER, []

    is_multi_paper = len(papers) > 1
    system_prompt = SYSTEM_PROMPT + (MULTI_PAPER_INSTRUCTION if is_multi_paper else "")

    context = format_context_excerpts(chunks)
    intro = (
        f"Context excerpts from {len(papers)} papers:"
        if is_multi_paper
        else f'Context excerpts from "{papers[0].title}":'
    )

    messages = [{"role": "system", "content": system_prompt}]
    for role, content in history[-MAX_HISTORY_MESSAGES:]:
        messages.append({"role": role, "content": content})
    messages.append({"role": "user", "content": f"{intro}\n\n{context}\n\nQuestion: {question}"})

    answer = generate_chat_completion(messages)
    citations = extract_citations(answer, chunks)
    return answer, citations
