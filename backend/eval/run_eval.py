"""Evaluation harness for the RAG pipeline (Phase 6).

Runs a small fixed set of hand-written question/answer pairs against the
*real* running backend (over HTTP, same as the frontend would call it) and
scores each answer for keyword coverage, citation page accuracy, and honest
"I don't know" behavior on questions the source papers don't answer.

Usage (backend must already be running, e.g. `uvicorn app.main:app`):
    python eval/run_eval.py [--base-url http://localhost:8000/api/v1]

Uses a dedicated, persistent eval account (EVAL_EMAIL below) so re-runs are
idempotent: fixture papers are uploaded once and reused (checksum-matched)
on every subsequent run rather than re-uploaded, and a fresh chat session is
created per question so one case's context can never leak into another's.

Writes a JSON report to eval/report.json and prints a summary table.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import httpx

EVAL_DIR = Path(__file__).parent
FIXTURES_DIR = EVAL_DIR / "fixtures"
DATASET_PATH = EVAL_DIR / "dataset.json"
REPORT_PATH = EVAL_DIR / "report.json"

EVAL_EMAIL = "eval-harness@example.com"
EVAL_PASSWORD = "eval-harness-password-not-a-real-account"

UNKNOWN_HEDGE_PHRASES = [
    "don't know",
    "do not know",
    "not mentioned",
    "not specify",
    "not specified",
    "couldn't find",
    "could not find",
    "cannot find",
    "can't find",
    "no information",
    "doesn't contain",
    "does not contain",
    "doesn't mention",
    "does not mention",
]

POLL_INTERVAL_S = 2
POLL_TIMEOUT_S = 60


@dataclass
class CaseResult:
    case_id: str
    question: str
    answer: str
    passed: bool
    keyword_coverage: float
    citation_correct: bool | None
    detail: str
    elapsed_s: float


class EvalClient:
    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.client = httpx.Client(timeout=180.0)
        self.token: str | None = None

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"}

    def ensure_account(self) -> None:
        response = self.client.post(
            f"{self.base_url}/auth/register",
            json={"email": EVAL_EMAIL, "password": EVAL_PASSWORD, "full_name": "Eval Harness"},
        )
        if response.status_code == 201:
            self.token = response.json()["token"]["access_token"]
            print(f"Registered fresh eval account ({EVAL_EMAIL})")
            return

        response = self.client.post(
            f"{self.base_url}/auth/login", json={"email": EVAL_EMAIL, "password": EVAL_PASSWORD}
        )
        response.raise_for_status()
        self.token = response.json()["token"]["access_token"]
        print(f"Logged in to existing eval account ({EVAL_EMAIL})")

    def list_papers(self) -> list[dict]:
        response = self.client.get(f"{self.base_url}/papers/", headers=self._headers())
        response.raise_for_status()
        return response.json()

    def upload_paper(self, file_path: Path) -> dict:
        with open(file_path, "rb") as fh:
            response = self.client.post(
                f"{self.base_url}/papers/upload",
                headers=self._headers(),
                files={"file": (file_path.name, fh, "application/pdf")},
            )
        if response.status_code == 409:
            # Already uploaded (checksum match) — find it in the existing list.
            checksum_conflict_title = response.json().get("detail", "")
            for paper in self.list_papers():
                if paper["original_filename"] == file_path.name:
                    return paper
            raise RuntimeError(f"409 on upload but couldn't find existing paper: {checksum_conflict_title}")
        response.raise_for_status()
        return response.json()

    def wait_until_ready(self, paper_id: int) -> str:
        deadline = time.time() + POLL_TIMEOUT_S
        while time.time() < deadline:
            response = self.client.get(f"{self.base_url}/papers/{paper_id}", headers=self._headers())
            response.raise_for_status()
            status = response.json()["processing_status"]
            if status in ("ready", "failed"):
                return status
            time.sleep(POLL_INTERVAL_S)
        raise TimeoutError(f"Paper {paper_id} did not finish processing within {POLL_TIMEOUT_S}s")

    def ask(self, anchor_paper_id: int, question: str, additional_paper_ids: list[int]) -> dict:
        response = self.client.post(
            f"{self.base_url}/papers/{anchor_paper_id}/chat",
            headers=self._headers(),
            json={"message": question, "session_id": None, "additional_paper_ids": additional_paper_ids},
        )
        response.raise_for_status()
        return response.json()


def _matches_any(text: str, phrases: list[str]) -> bool:
    lowered = text.lower()
    return any(phrase.lower() in lowered for phrase in phrases)


def score_case(case: dict, answer: str, citations: list[dict]) -> CaseResult:
    if case.get("expect_unknown"):
        hedged = _matches_any(answer, UNKNOWN_HEDGE_PHRASES)
        return CaseResult(
            case_id=case["id"],
            question=case["question"],
            answer=answer,
            passed=hedged,
            keyword_coverage=1.0 if hedged else 0.0,
            citation_correct=None,
            detail="correctly declined to answer" if hedged else "should have said it didn't know, but didn't",
            elapsed_s=0.0,
        )

    groups = case.get("expected_keyword_groups", [])
    hits = [any(_matches_any(answer, [kw]) for kw in group) for group in groups]
    coverage = (sum(hits) / len(hits)) if hits else 1.0
    missing = [groups[i][0] for i, hit in enumerate(hits) if not hit]

    citation_correct: bool | None = None
    detail_parts = []
    expected_pages = case.get("expected_pages")
    if expected_pages:
        citation_correct = any(
            citation["page_start"] in expected_pages or citation["page_end"] in expected_pages for citation in citations
        )
        if not citation_correct:
            detail_parts.append(f"no citation matched expected page(s) {expected_pages}")

    if case.get("expect_both_papers_cited"):
        distinct_papers = {citation["paper_id"] for citation in citations}
        both_cited = len(distinct_papers) >= 2
        citation_correct = both_cited
        if not both_cited:
            detail_parts.append(f"expected citations from 2 papers, got {len(distinct_papers)}")

    if missing:
        detail_parts.append(f"missing: {missing}")

    passed = coverage == 1.0 and citation_correct is not False
    detail = "; ".join(detail_parts) if detail_parts else "ok"

    return CaseResult(
        case_id=case["id"],
        question=case["question"],
        answer=answer,
        passed=passed,
        keyword_coverage=coverage,
        citation_correct=citation_correct,
        detail=detail,
        elapsed_s=0.0,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://localhost:8000/api/v1")
    args = parser.parse_args()

    dataset = json.loads(DATASET_PATH.read_text(encoding="utf-8"))
    client = EvalClient(args.base_url)

    print(f"Eval target: {args.base_url}")
    client.ensure_account()

    # Upload (or reuse) fixture papers, wait until each is ready.
    paper_ids: dict[str, int] = {}
    for paper in dataset["papers"]:
        file_path = FIXTURES_DIR / paper["file"]
        record = client.upload_paper(file_path)
        status = record["processing_status"]
        if status not in ("ready", "failed"):
            print(f"Waiting for '{paper['id']}' (paper {record['id']}) to finish processing...")
            status = client.wait_until_ready(record["id"])
        if status != "ready":
            print(f"ERROR: fixture paper '{paper['id']}' failed to process (status={status})", file=sys.stderr)
            return 1
        paper_ids[paper["id"]] = record["id"]
        print(f"  {paper['id']} -> paper_id={record['id']} ({status})")

    results: list[CaseResult] = []
    for case in dataset["cases"]:
        real_ids = [paper_ids[key] for key in case["papers"]]
        anchor, additional = real_ids[0], real_ids[1:]

        print(f"\n[{case['id']}] {case['question']}")
        start = time.perf_counter()
        turn = client.ask(anchor, case["question"], additional)
        elapsed = time.perf_counter() - start

        answer = turn["assistant_message"]["content"]
        citations = turn["assistant_message"]["citations"] or []
        result = score_case(case, answer, citations)
        result.elapsed_s = elapsed
        results.append(result)

        status_label = "PASS" if result.passed else "FAIL"
        print(f"  -> {status_label} ({elapsed:.1f}s, coverage={result.keyword_coverage:.2f}) {result.detail}")

    passed_count = sum(1 for r in results if r.passed)
    total = len(results)
    avg_coverage = sum(r.keyword_coverage for r in results) / total if total else 0.0
    total_time = sum(r.elapsed_s for r in results)

    print("\n" + "=" * 60)
    print(f"RESULT: {passed_count}/{total} passed  (avg keyword coverage: {avg_coverage:.2f}, total time: {total_time:.1f}s)")
    print("=" * 60)
    for r in results:
        mark = "PASS" if r.passed else "FAIL"
        print(f"  [{mark}] {r.case_id}")

    report = {
        "base_url": args.base_url,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "total_cases": total,
        "passed": passed_count,
        "pass_rate": passed_count / total if total else 0.0,
        "avg_keyword_coverage": avg_coverage,
        "total_elapsed_s": total_time,
        "cases": [
            {
                "id": r.case_id,
                "question": r.question,
                "answer": r.answer,
                "passed": r.passed,
                "keyword_coverage": r.keyword_coverage,
                "citation_correct": r.citation_correct,
                "detail": r.detail,
                "elapsed_s": r.elapsed_s,
            }
            for r in results
        ],
    }
    REPORT_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"\nFull report written to {REPORT_PATH}")

    return 0 if passed_count == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
