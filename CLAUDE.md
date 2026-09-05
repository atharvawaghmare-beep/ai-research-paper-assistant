# AI Research Paper Assistant

## Project Purpose
Portfolio project for backend/AI-engineering internship applications. Users upload research papers (PDF), and the system uses RAG (Retrieval-Augmented Generation) to summarize them, answer questions grounded in the paper's actual content, and explain difficult concepts at different depths.

**Phases 0 through 11 are COMPLETE. This file has been updated to reflect that — do not treat language like "not yet added" or "decide before Phase 2" as still open; those decisions were already made and built. If you find code that contradicts what's described below as done, flag the mismatch to the user rather than silently assuming the file is right — the file may not perfectly reflect every implementation detail, but the core pipeline described here is built and working.**

**Bug found and fixed (during Phase 11 verification): `UploadedPaper.chat_sessions` (`app/models/uploaded_paper.py`) was declared with `cascade="all, delete-orphan"`. Deleting a paper that anchors a chat session cascade-deleted that session (and all its messages) at the ORM level — even a multi-paper (Phase 4) session with other papers still very much alive in the library — directly contradicting `delete_uploaded_paper`'s own docstring, which claims the anchor is set to NULL by the FK's `ondelete="SET NULL"` and the session survives. The ORM-level cascade was pre-empting that FK before it ever got a chance to apply. Fixed by dropping the cascade from that one relationship. Verified live with the exact failure scenario: created a session anchored on Paper A but also linked to Paper B (Phase 4 multi-paper), deleted Paper A, confirmed via direct DB query and the actual `GET /papers/{B}/chat/{session_id}` API call that the session survived with its anchor nulled, its link to Paper B intact, and both messages preserved.**

---

## Already Implemented (Phases 0-11 complete — do not rebuild, extend/harden instead)

### Backend (FastAPI, `backend/app/`)
- **Structure**: routers / models / schemas / services / auth / config / utils — keep using this pattern for all new code.
- **Auth**: JWT access tokens (PyJWT) + bcrypt (passlib), register/login/current-user, token blacklist table (`RevokedToken`) for logout. `app/auth/dependencies.py` has `get_current_user`.
- **DB migrations**: Alembic is set up and in use (migrated off `Base.metadata.create_all()` during Phase 0). Use `alembic revision` / `alembic upgrade head` for all schema changes going forward — do not add ad-hoc `create_all()` calls.
- **Secrets**: `.env` is gitignored, `JWT_SECRET_KEY` was rotated during Phase 0.
- **Paper upload**: `POST /api/v1/papers/upload` — validates MIME/extension, dedupes by SHA-256 checksum, enforces size limit, stores files under `uploads/papers/user-{id}/`, writes `UploadedPaper` row.
- **PDF extraction**: `extract_pdf_page_text()` in `app/services/paper_service.py` uses PyMuPDF, page-by-page text + metadata.
- **Chunking + embedding pipeline (Phase 1, complete)**: `chunking_service.py` does section-aware chunking with fallback to fixed-size+overlap. `embedding_service.py` runs chunks through Sentence Transformers and populates `document_embeddings`. A FAISS index is built and persisted to disk, updated incrementally on upload. `UploadedPaper.processing_status` moves through `uploaded → chunking → embedding → ready`/`failed`, triggered automatically as a background task after upload.
- **Retrieval + grounded chat (Phase 2, complete)**: hybrid search (FAISS + BM25) with cross-encoder re-ranking feeds retrieved chunks to the LLM. Chat endpoints (`POST /papers/{id}/chat`, `GET /papers/{id}/chat/{session_id}`) are live, scoped to `current_user.id`, and answers include page-level citations stored in `ChatMessage.citations` and surfaced in the UI.
- **LLM provider**: decided and wired up (Ollama local inference — see chat history/commits for the specific model if it matters going forward; the LLM call lives in an isolated service function so the provider can be swapped without touching retrieval/chunking/chat logic).
- **Summaries + concept explanations (Phase 3, complete)**: summary endpoint generates and caches a whole-paper summary (not regenerated on repeat requests). Concept explanation endpoint supports difficulty levels (beginner/intermediate/expert) via prompt variation. Both have working frontend UI on the paper detail page.
- **Multi-paper Q&A (Phase 4, complete)**: chat sessions can span multiple `paper_id`s, retrieval pulls from the combined chunk pool, answers reference which paper each citation came from.
- **Frontend redesign (Phase 5, complete)**: visual direction was chosen (clean/minimal) and applied across the homepage, dashboard, chat interface, and upload flow. Architecture page removed from user-facing nav. Citation labels are spelled out clearly (e.g. "Source 1, pages 1-2") rather than abbreviated.
- **Production polish (Phase 6, complete)**: evaluation harness exists (test papers + expected Q&A pairs + scoring script). Rate limiting is on LLM-calling endpoints with latency/cost logging. Dashboard shows real data, not placeholders.
- **Authorization**: every user-scoped resource (papers, chunks, embeddings, chat sessions) correctly scopes queries to `current_user.id`, following the pattern established in `get_user_paper_by_id`. Keep this pattern for every new resource added in Phase 12 onward.
- **Usage analytics dashboard (Phase 11, complete)**: `GET /analytics/summary` (`analytics_service.py`) aggregates, per current user: total papers, total questions asked, the "most active" paper (most user-message questions across sessions it's linked to, via `chat_session_papers` — a multi-paper session's questions count toward every paper it touches), the 5 most-cited chunks/pages (aggregated directly from `ChatMessage.citations`, no join back to `document_chunks` needed since each stored citation already embeds paper/page info), and a 14-day daily question-count series (zero-filled so the chart has no gaps). "Time spent per paper" is deliberately NOT implemented — the only view signal tracked (Phase 8's `last_viewed_at`) is a single timestamp, not a start/end pair, and faking a duration from that would be worse than omitting it; skipped per this phase's own instruction to skip rather than fake. Frontend: an "Activity" section on the dashboard (`AnalyticsPanel.tsx`) — three stat tiles, a hand-rolled single-series SVG bar chart (hover/focus tooltip, zero-filled days, no legend needed for one series, built following the dataviz skill's form/mark/interaction rules) for the 14-day trend, and a most-cited-pages list. Verified live against real Postgres: asked real questions across 2 imported papers, backdated one message 3 days via direct DB write to test day-bucketing, confirmed the API's per-day counts landed in the exact right day bucket and summed correctly to the total.
- **Compare mode (Phase 10, complete)**: `GET /papers/compare?paper_ids=1&paper_ids=2&...` (2-5 ids) reshapes the existing per-paper summary call (`summary_service.get_or_generate_summary`, same cache — no new summarization logic) into one response shaped for side-by-side display. The actual comparison Q&A has no new backend code at all: the frontend just calls the existing Phase 4 chat endpoint with the first selected paper as the URL anchor and the rest as `additional_paper_ids`. Frontend: `/compare` page (linked from nav) — pick 2-5 ready papers, see their summaries side by side, then ask a question in an inline chat panel that reuses `CitationList` for multi-paper citation display. Verified live end-to-end (real Postgres + Ollama): imported 2 papers, fetched side-by-side summaries (first call generated+cached both via Ollama, second call hit cache), asked a comparison question, confirmed the answer's citations correctly spanned both papers (`paper_id`/`paper_title`/pages for each) before cleaning up.
- **Citation graph + related papers (Phase 9, complete)**: `citation_graph_service.py` fetches references/citing-papers/citation-count from Semantic Scholar's paper-details endpoint (`fetch_semantic_scholar_paper_graph()` in `external_paper_service.py`, which accepts `ARXIV:<id>` so this works for arXiv imports too, not just Semantic Scholar ones) and caches the result on `paper_metadata['citation_graph']` — same cache-on-the-paper pattern Phase 3's summary uses. Prefetched best-effort at import time (never fails the import if Semantic Scholar is rate-limited or hasn't indexed the paper yet); lazily fetched-and-cached on first `GET /papers/{id}/citations` request otherwise. Reference/citing-paper entries reuse the Phase 7 `ExternalPaperResult` shape (now with an added optional `citation_count` field), so they're directly importable through the existing `/papers/import` endpoint — no separate code path. "Related papers" is a simple ranking (importable first, then by citation count) over that same reference+citing-paper data, not a real recommender. Frontend: a `CitationsPanel.tsx` tab on the paper detail page with a small radial SVG citation graph, a "Related papers" section, and full References/Cited-by lists, each row importable. Verified live against real Semantic Scholar data (BERT: 120,411 citations, 63 references; related suggestions surfaced "Attention Is All You Need", ELMo, GLUE — genuinely relevant); imported a suggested paper through the normal pipeline and confirmed it reached `ready`.
- **Reading history / recently viewed (Phase 8, complete)**: `UploadedPaper.last_viewed_at` (nullable, indexed) is stamped by `mark_paper_viewed()`, called only from `GET /papers/{id}` (the "open a paper" route) — not from the shared `get_user_paper_by_id` lookup other services use internally, so hitting summary/explain/chat doesn't masquerade as a view. `GET /papers/?sort=last_viewed_at&limit=N` filters to papers with a non-null `last_viewed_at` and orders by it descending; default `sort=uploaded_at` behavior is unchanged. Dashboard shows a "Recently viewed" strip above the main papers list, fetched via the same endpoint with `sort=last_viewed_at`. Verified live: opened two imported papers in sequence, confirmed the sort order tracked view time (not upload time) and flipped correctly on re-opening the older one.
- **Paper search integration (Phase 7, complete)**: `external_paper_service.py` queries arXiv (Atom XML) and Semantic Scholar (JSON) in parallel try/except blocks — one provider failing/rate-limiting surfaces as a `warnings` entry, not a 500. `GET /papers/search?q=` returns merged, deduped-by-provider results (`ExternalPaperResult`: title, authors, abstract, year, pdf_url, external_url, `importable`). `POST /papers/import` downloads the PDF server-side (retry with backoff, size-limit + `%PDF-` magic-byte validation) and calls the same `_persist_new_paper()` core that manual upload uses (`save_uploaded_pdf` and `save_imported_pdf` are now both thin wrappers over it) — so an imported paper hits the identical checksum-dedupe path and the identical `process_uploaded_paper` background task as a manual upload. Frontend: `/discover` page (linked from nav) with search bar, result cards showing an "Add to my library" action, and a warnings banner for partial results. Verified live end-to-end (real arXiv + Semantic Scholar calls, real Postgres): search → import → download → chunk → embed → `ready`, with chunk/embedding rows confirmed in the DB.

### Frontend (React + Vite + Tailwind, `frontend/src/`)
- React Router set up, pages: Home (redesigned), Login, Signup, Dashboard (protected, real data), Projects, NotFound. Architecture page removed from nav.
- `ProtectedRoute.tsx` + `AuthContext.tsx` for auth-gated routes.
- `PdfUploadDropzone.tsx` — drag-and-drop multi-upload, wired to the upload endpoint, shows real processing status (not a fake spinner).
- `AppLayout.tsx` for shared nav/sidebar shell, redesigned in clean/minimal style.
- Chat UI: message list, input, loading states, expandable citation display with clear labels.
- Summary + concept-explanation UI on the paper detail page, with difficulty-level selection.

---

## Tech Stack (as built)
- **API**: FastAPI
- **DB**: PostgreSQL + SQLAlchemy, Alembic migrations
- **Frontend**: React + Vite + Tailwind + React Router
- **PDF extraction**: PyMuPDF
- **Embeddings**: `sentence-transformers`
- **Vector index**: FAISS (local, in-process, persisted to disk)
- **Hybrid search**: FAISS + BM25 (`rank_bm25`) with cross-encoder re-ranking
- **LLM**: Ollama (local inference) — isolated behind a single service function for easy provider swapping
- **Background jobs**: FastAPI `BackgroundTasks`

---

## Build Phases

**Phases 0-11 are complete (see "Already Implemented" above). Starting point for new work is Phase 12.**

### Phase 7 — Paper search integration ✅ complete
- ~~New service `external_paper_service.py`...~~ Done — see "Already Implemented" above for what was built and how it was verified (live arXiv + Semantic Scholar calls, full search→import→ready run against real Postgres). DoD met.

### Phase 8 — Reading history / recently viewed ✅ complete
- ~~Track paper views...~~ Done — see "Already Implemented" above. DoD met: verified live against real Postgres (two imported papers opened in sequence, sort order tracked actual view time and flipped correctly on re-opening the older one).

### Phase 9 — Citation graph + suggested related papers ✅ complete
- ~~Depends on Phase 7...~~ Done — see "Already Implemented" above. DoD met: verified live against real Semantic Scholar data (BERT's actual 120,411 citations / 63 references, genuinely relevant related-paper suggestions, a suggested paper imported through the normal pipeline to `ready`).

### Phase 10 — Compare mode ✅ complete
- ~~Reuses the Phase 4 multi-paper Q&A backend...~~ Done — see "Already Implemented" above. DoD met: verified live against real Postgres + Ollama (2 papers imported, side-by-side summaries generated and cached, a comparison question answered with citations correctly spanning both papers).

### Phase 11 — Usage analytics dashboard ✅ complete
- ~~Track basic usage events...~~ Done — see "Already Implemented" above. DoD met: verified live against real Postgres (real questions asked across 2 papers, one message backdated 3 days to confirm day-bucketing lands correctly rather than just testing the trivial same-day case).

### Phase 12 — Live demo readiness (single-user, scheduled demo)
This phase is about preparing to demo the app running locally to a live audience via a tunnel — not deploying to a public host. Do this shortly before the actual scheduled demo, and re-verify close to demo day since local environment state can drift.
- Install a tunneling tool (ngrok or Cloudflare Tunnel) ahead of time, not on demo day.
- Update backend CORS settings to allow the tunnel's public URL (in addition to `localhost`) — temporarily allowing `*` is acceptable for a one-off demo, but should not be left that way if the app is ever exposed beyond a single demo.
- Confirm the frontend's API base URL is configurable (not hardcoded to `localhost`) so it still works when accessed through the tunnel.
- Verify the full flow once end-to-end before the demo: start Postgres (Docker), backend, frontend, and Ollama (with model loaded) locally, start the tunnel, and walk through upload → chat → citations → summary from a separate device or browser profile (not just localhost) to confirm the public URL actually works.
- Record a short screen-capture backup of the working demo in case of live network/tunnel/Ollama issues during the actual presentation.
- DoD: a person on a different device/network can access the app via the tunnel URL and complete the full upload-to-chat flow; a backup recording exists.

---

## Coding Conventions
- Keep the existing folder pattern: routers stay thin (validation + call service), services hold logic, models stay pure ORM.
- Every new resource (chunks, embeddings, chat sessions) must scope queries to `current_user.id`, following the existing `get_user_paper_by_id` pattern — don't introduce an authorization gap while adding features.
- Type hints throughout (existing code already does this — match the style).
- Long-running work triggered from a request handler must update a status field the frontend can poll — no silent background failures.

## Working Notes for Claude Code
- **Phases 0-6 are complete.** Read the "Already Implemented" section above as ground truth. If actual code contradicts it, flag the specific mismatch to the user rather than silently rebuilding or assuming the file is wrong.
- Read this file plus the actual current code before starting Phase 7 — get familiar with the existing chunking/embedding/retrieval/chat services before adding new features on top of them.
- After each phase, report exact manual verification steps/commands, and don't proceed to the next phase until those are confirmed working.
- Phases 9 (citation graph/related papers) depends on Phase 7 (paper search integration) — do not start Phase 9 before Phase 7 is done.
- Phase 12 (live demo readiness) is a pre-demo checklist to run through shortly before an actual scheduled demo, not a feature to build once and forget — re-verify it close to demo day.
