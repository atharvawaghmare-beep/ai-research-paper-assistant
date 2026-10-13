"""Format-review templates (Phase 17) as plain data, not hardcoded prompts —
adding a new template later should mean adding an entry here, not writing new
matching/check code. Each template describes a standard research-paper
structure as an ordered list of sections; `format_review_service` matches a
paper's actual outline (Phase 16's `extract_outline_and_pages()`) against
whichever template the user picks.

`aliases` are lowercase substrings matched against outline heading text in
both directions (alias-in-heading or heading-in-alias) — real headings vary a
lot ("Methodology" vs "Method" vs "Proposed Approach"), so this is deliberately
loose rather than an exact-match whitelist.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class TemplateSection:
    id: str
    name: str
    aliases: tuple[str, ...]
    required: bool
    # Position in the template's expected reading order — used only to detect
    # sections that appear out of order relative to each other, not to require
    # an exact section count or forbid extra sections in between.
    order_index: int
    # (min_words, max_words), checked only for sections where paper norms are
    # tight enough that a violation is a real signal (abstracts). None for
    # every other section — a "too short Methods section" is instead caught by
    # the generic near-empty-section check, which doesn't need a hard range.
    word_range: tuple[int, int] | None = None


@dataclass(frozen=True)
class FormatTemplate:
    id: str
    name: str
    description: str
    sections: tuple[TemplateSection, ...]


_IMRAD_SECTIONS: tuple[TemplateSection, ...] = (
    TemplateSection("abstract", "Abstract", ("abstract",), required=True, order_index=0, word_range=(100, 350)),
    TemplateSection("introduction", "Introduction", ("introduction",), required=True, order_index=1),
    TemplateSection(
        "related_work",
        "Related Work",
        ("related work", "literature review", "background", "prior work"),
        required=False,
        order_index=2,
    ),
    TemplateSection(
        "methodology",
        "Methodology",
        (
            "method",
            "methodology",
            "approach",
            "proposed method",
            "system design",
            "materials and methods",
            "architecture",
            "framework",
        ),
        required=True,
        order_index=3,
    ),
    TemplateSection(
        "results",
        "Results",
        ("result", "experiment", "evaluation", "findings"),
        required=True,
        order_index=4,
    ),
    TemplateSection("discussion", "Discussion", ("discussion",), required=False, order_index=5),
    TemplateSection(
        "conclusion",
        "Conclusion",
        ("conclusion", "concluding remark", "summary and future work"),
        required=True,
        order_index=6,
    ),
    TemplateSection("references", "References", ("reference", "bibliography"), required=True, order_index=7),
)

_IEEE_SECTIONS: tuple[TemplateSection, ...] = (
    TemplateSection("abstract", "Abstract", ("abstract",), required=True, order_index=0, word_range=(150, 250)),
    TemplateSection(
        "keywords",
        "Index Terms / Keywords",
        ("keywords", "index terms"),
        required=False,
        order_index=1,
    ),
    TemplateSection("introduction", "Introduction", ("introduction",), required=True, order_index=2),
    TemplateSection(
        "related_work",
        "Related Work",
        ("related work", "literature review", "background", "prior work"),
        required=False,
        order_index=3,
    ),
    TemplateSection(
        "methodology",
        "Methodology",
        ("method", "methodology", "approach", "proposed system", "system design", "architecture", "framework"),
        required=True,
        order_index=4,
    ),
    TemplateSection(
        "results",
        "Results",
        ("result", "experiment", "simulation", "evaluation"),
        required=True,
        order_index=5,
    ),
    TemplateSection(
        "conclusion",
        "Conclusion",
        ("conclusion", "concluding remark", "future work"),
        required=True,
        order_index=6,
    ),
    TemplateSection("references", "References", ("reference",), required=True, order_index=7),
)

FORMAT_TEMPLATES: dict[str, FormatTemplate] = {
    "imrad": FormatTemplate(
        id="imrad",
        name="Generic IMRaD",
        description="The standard Introduction/Methods/Results/Discussion structure used by most journals and theses.",
        sections=_IMRAD_SECTIONS,
    ),
    "ieee": FormatTemplate(
        id="ieee",
        name="IEEE Conference",
        description="IEEE-style conference paper structure, including an Index Terms/Keywords section.",
        sections=_IEEE_SECTIONS,
    ),
}

FORMAT_REVIEW_VERSION = 1


def list_templates() -> list[dict]:
    return [
        {"id": template.id, "name": template.name, "description": template.description}
        for template in FORMAT_TEMPLATES.values()
    ]


def get_template(template_id: str) -> FormatTemplate:
    template = FORMAT_TEMPLATES.get(template_id)
    if template is None:
        raise ValueError(f"Unknown format template: {template_id!r}")
    return template
