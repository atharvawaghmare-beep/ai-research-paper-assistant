from __future__ import annotations

import re

from app.services.retrieval_service import RetrievedChunk

# Source-tagged citations ([S1], [S2], ...) are extracted from the model's plain-text
# answer by regex rather than asking the model to also emit a structured citations
# blob — a small local model is far more reliable at dropping a "[S2]" into prose than
# at producing well-formed JSON, and the excerpt->chunk mapping is already known before
# generation, so no information is lost by keeping the model's job purely textual.
# The "S" prefix (vs. a bare number) deliberately avoids colliding with the paper's own
# in-text reference citations (e.g. "the Adam optimizer [17]"), which a bare [N] scheme
# does not — a small model asked to cite "[N]" will sometimes echo the source's own
# citation number instead of the excerpt tag it was actually given.
CITATION_MARKER_RE = re.compile(r"\[S(\d+)\]")

CITATION_INSTRUCTION = (
    "For every factual claim, cite the excerpt using its source tag in square brackets, "
    "e.g. [S1] or [S2][S3]. The excerpts are pulled from an academic paper and may "
    "themselves contain numeric reference citations like [12] or [17] — those are part "
    "of the paper's own text, NOT excerpt tags; never cite them, only ever cite [S1], "
    "[S2], etc."
)


def format_context_excerpts(chunks: list[RetrievedChunk]) -> str:
    """Render retrieved chunks as numbered, page-labeled excerpts for a prompt.

    When the chunks span more than one paper (Phase 4 multi-paper Q&A), each
    excerpt is also labeled with its source paper's title, so the model can
    actually distinguish "paper A says X" from "paper B says Y" rather than
    treating everything as one undifferentiated context blob.
    """
    multi_paper = len({chunk.paper_id for chunk in chunks}) > 1
    lines = []
    for position, chunk in enumerate(chunks, start=1):
        page_label = (
            f"p.{chunk.page_start}" if chunk.page_start == chunk.page_end else f"pp.{chunk.page_start}-{chunk.page_end}"
        )
        source_label = f'"{chunk.paper_title}", {page_label}' if multi_paper else page_label
        lines.append(f"[S{position}] ({source_label}) {chunk.content}")
    return "\n\n".join(lines)


def extract_citations(answer: str, chunks: list[RetrievedChunk]) -> list[dict]:
    """Pull [S1], [S2], ... markers out of a generated answer and resolve them back
    to the chunks that were actually offered — silently dropping any marker number
    outside that range rather than fabricating a citation for it."""
    referenced_positions = sorted({int(match) for match in CITATION_MARKER_RE.findall(answer)})
    citations = []
    for position in referenced_positions:
        if not (1 <= position <= len(chunks)):
            continue
        chunk = chunks[position - 1]
        citations.append(
            {
                "marker": position,
                "chunk_id": chunk.chunk_id,
                "paper_id": chunk.paper_id,
                "paper_title": chunk.paper_title,
                "page_start": chunk.page_start,
                "page_end": chunk.page_end,
                "snippet": chunk.content[:240],
            }
        )
    return citations
