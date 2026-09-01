"""Generates the eval harness's fixture PDFs and writes them to eval/fixtures/.

Run once (or whenever the fixture content itself needs to change):
    python eval/generate_fixtures.py

The generated files are committed to the repo so the eval dataset is stable
and inspectable — this script exists for reproducibility, not to be re-run
automatically before every eval run.
"""

from __future__ import annotations

from pathlib import Path

import pymupdf

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def _add_page(doc: pymupdf.Document, lines: list[tuple[str, int]]) -> None:
    """lines: [(text, fontsize), ...], laid out top-to-bottom."""
    page = doc.new_page()
    y = 72
    for text, size in lines:
        page.insert_text((72, y), text, fontsize=size, fontname="helv")
        y += size + 10


def build_solartrack() -> None:
    doc = pymupdf.open()
    _add_page(
        doc,
        [
            ("SolarTrack: Adaptive Solar Panel Orientation", 16),
            ("", 8),
            ("Abstract", 14),
            ("SolarTrack adjusts panel tilt every fifteen minutes using a lightweight", 10),
            ("sun-position model, increasing daily energy capture by twenty eight percent", 10),
            ("compared to fixed-angle panels.", 10),
            ("", 8),
            ("Introduction", 14),
            ("Fixed-angle solar panels lose significant output as the sun moves across the", 10),
            ("sky. SolarTrack addresses this by recomputing an optimal tilt angle at a", 10),
            ("regular interval throughout the day.", 10),
        ],
    )
    _add_page(
        doc,
        [
            ("Method", 14),
            ("SolarTrack uses a Kalman filter to smooth noisy light-sensor readings", 10),
            ("before computing the optimal tilt angle for the next fifteen-minute window.", 10),
            ("", 8),
            ("Results", 14),
            ("In field trials across four rooftop installations over three months,", 10),
            ("SolarTrack consistently outperformed fixed panels, with the largest gain", 10),
            ("of thirty five percent observed in winter months.", 10),
            ("", 8),
            ("Conclusion", 14),
            ("SolarTrack demonstrates that lightweight, sensor-driven tilt adjustment", 10),
            ("can meaningfully improve solar capture without complex hardware.", 10),
        ],
    )
    doc.save(FIXTURES_DIR / "solartrack.pdf")
    doc.close()


def build_packlite() -> None:
    doc = pymupdf.open()
    _add_page(
        doc,
        [
            ("PackLite: Compressed Model Checkpointing", 16),
            ("", 8),
            ("Abstract", 14),
            ("PackLite compresses neural network checkpoints using delta encoding", 10),
            ("between consecutive training steps, cutting checkpoint storage by sixty", 10),
            ("percent without any loss in model accuracy.", 10),
            ("", 8),
            ("Introduction", 14),
            ("Large model checkpoints consume enormous storage over long training runs.", 10),
            ("PackLite reduces this footprint by exploiting redundancy between", 10),
            ("consecutive checkpoints rather than storing each one in full.", 10),
        ],
    )
    _add_page(
        doc,
        [
            ("Method", 14),
            ("PackLite stores only the difference between each checkpoint and the", 10),
            ("previous one, using sparse delta encoding to keep the diffs small.", 10),
            ("", 8),
            ("Results", 14),
            ("Across five large language model training runs, PackLite reduced total", 10),
            ("checkpoint storage from 2.1 terabytes to approximately 840 gigabytes,", 10),
            ("with no measurable change in downstream task accuracy.", 10),
        ],
    )
    doc.save(FIXTURES_DIR / "packlite.pdf")
    doc.close()


if __name__ == "__main__":
    FIXTURES_DIR.mkdir(parents=True, exist_ok=True)
    build_solartrack()
    build_packlite()
    print(f"Wrote fixtures to {FIXTURES_DIR}")
