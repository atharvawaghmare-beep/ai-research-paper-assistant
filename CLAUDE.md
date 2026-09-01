# AI Research Paper Assistant

## Project Purpose
Portfolio project for backend/AI-engineering internship applications. Users upload research papers (PDF), and the system uses RAG (Retrieval-Augmented Generation) to summarize them, answer questions grounded in the paper's actual content, and explain difficult concepts at different depths.

**This file reflects the ACTUAL current state of the codebase (verified by inspection, not assumed from prompt history) plus the roadmap forward. Do not assume anything not listed under "Already Implemented" exists — check the code first if unsure.**

---

## Already Implemented (do not rebuild — extend/harden instead)

### Backend (FastAPI, `backend/app/`)
- **Structure**: routers / models / schemas / services / auth / config / utils — keep using this pattern for all new code.
- **Auth**: JWT access tokens (PyJWT) + bcrypt (passlib), register/login/current-user, token blacklist table (`RevokedToken`) for logout. `app/auth/dependencies.py` has `get_current_user`.
- **DB**: PostgreSQL + SQLAlchemy 2.0 ORM, models in `app/models/`. Raw SQL migration also exists at `backend/migrations/001_create_ai_research_paper_assistant_schema.sql` — **note: `app/main.py` currently calls `Base.metadata.create_all()` on startup rather than running versioned migrations.** This works for solo dev but should move to Alembic before this gets more complex (see Phase 0 below).
- **Paper upload**: `POST /api/v1/papers/upload` — validates MIME/extension, dedupes by SHA-256 checksum, enforces size limit (`max_pdf_upload_size_mb`, default 25MB), stores files under `uploads/papers/user-{id}/`, writes `UploadedPaper` row.
- **PDF extraction (this was the "step 7" you weren't sure about — it exists and works)**: `extract_pdf_page_text()` in `app/services/paper_service.py` uses PyMuPDF, returns page-by-page text + PDF metadata (author, title, page count, etc). Exposed at `GET /api/v1/papers/{id}/extract`. **This currently extracts on-demand, synchronously, per request — not stored anywhere. Chunking/embedding pipeline (Phase 1 below) should persist extraction output instead of re-extracting every time.**
- **DB schema ready for RAG but unpopulated**: `document_chunks` and `document_embeddings` tables/models exist with sensible columns (chunk_index, page_start/end, character offsets, embedding_vector as JSONB, embedding_model/dimensions, embedding_status). Nothing currently writes to these tables — this is the first real gap to fill.
- **Chat schema also ready but unused**: `chat_sessions` and `chat_messages` tables exist (with a `citations` JSONB column already anticipating grounded answers) but there's no chat router/service yet.

### Frontend (React + Vite + Tailwind, `frontend/src/`)
- React Router set up (`App.tsx`), pages: Home, Login, Signup, Dashboard (protected), Projects, NotFound.
- `ProtectedRoute.tsx` + `AuthContext.tsx` for auth-gated routes.
- `PdfUploadDropzone.tsx` — drag-and-drop multi-upload component already wired to the upload endpoint.
- `AppLayout.tsx` for shared nav/sidebar shell.

### Known issues to fix early (found during inspection)
- **Real `.env` files (not just `.env.example`) were present in the project directory**, including a real `JWT_SECRET_KEY`. Confirm `.env` is in `.gitignore` and rotate the secret before pushing this repo anywhere public.
- `embedding_vector` is stored as JSONB, not a native vector type — fine for small scale with FAISS as the actual search index (Postgres is just metadata bookkeeping here), but don't try to do similarity search in Postgres itself with this schema.
- No authorization gap found in the paper endpoints (`get_user_paper_by_id` correctly scopes to `current_user.id`) — good, keep this pattern for every new resource (chunks, embeddings, chat sessions) added below.

---

## Tech Stack (confirmed + additions needed)
- **API**: FastAPI (existing)
- **DB**: PostgreSQL + SQLAlchemy (existing)
- **Frontend**: React + Vite + Tailwind + React Router (existing)
- **PDF extraction**: PyMuPDF (existing)
- **Embeddings**: `sentence-transformers` (e.g. `all-MiniLM-L6-v2` to start — fast, good enough, small) — **not yet in `pyproject.toml`, needs adding**
- **Vector index**: FAISS (local, in-process) — **not yet added**
- **LLM**: Llama or Mistral via a local inference server (e.g. Ollama) or a hosted API — **decide which before Phase 2** (see open question below)
- **Background jobs**: FastAPI `BackgroundTasks` to start; upgrade to a real queue (Celery/RQ + Redis) only if needed — see Phase 6

**Open question to resolve before Phase 2 (LLM integration):** local inference (Ollama running Llama/Mistral — free, private, but needs decent hardware and is slower) vs. a hosted API (faster/easier, costs money or requires a free-tier key, less "I ran my own model" credibility). Flag this back to the user before proceeding past Phase 1 if not already decided.

---

## Build Phases

### Phase 0 — Foundation hardening (do this before touching RAG features)
- Move schema management from `create_all()` to Alembic migrations (import the existing SQL migration as the baseline).
- Confirm `.env` is gitignored; rotate `JWT_SECRET_KEY`.
- Add `sentence-transformers` and `faiss-cpu` to `pyproject.toml`.
- DoD: `alembic upgrade head` works from a clean DB; secrets are not in git history going forward.

### Phase 1 — Chunking + embedding pipeline
- New service `chunking_service.py`: chunk extracted page text into `DocumentChunk` rows. Use **section-aware chunking** where possible (detect headings like "Abstract", "Introduction", "Methods", "Results", "Conclusion", "References" via font-size/heuristics from PyMuPDF's structured output) rather than naive fixed-size splitting — this is one of the "make it better" asks. Fall back to fixed-size with overlap when no headings are detected.
- New service `embedding_service.py`: run each chunk through Sentence Transformers, store the vector in `DocumentEmbedding.embedding_vector`, set `embedding_status`.
- Build a FAISS index per paper (or one global index with paper_id metadata filtering — prefer global index + metadata filter, simpler to keep in sync). Persist the FAISS index to disk, rebuild/update incrementally on new uploads.
- Trigger this pipeline automatically after upload (background task), update `UploadedPaper.processing_status` through `uploaded → chunking → embedding → ready` (or `failed`) so the frontend can show real progress instead of a fake spinner.
- DoD: upload a paper, poll its status, confirm it reaches `ready` and chunks+embeddings exist in the DB.

### Phase 2 — Retrieval + grounded Q&A
- Retrieval service: embed the user's question, FAISS search within the target paper(s), return top-k chunks with page numbers.
- **Hybrid search**: add BM25 (e.g. `rank_bm25`) over the same chunks, combine scores with vector search (simple weighted sum is fine to start) — pure embedding search misses exact terms like model names and acronyms.
- **Re-ranking**: pass the combined candidate set through a cross-encoder (`sentence-transformers` cross-encoder model) before picking final top-k to send to the LLM.
- LLM integration: send question + retrieved chunks as context, get an answer. **Always require the model to cite which chunk/page each claim came from** — store this in `ChatMessage.citations` (schema already supports it) and surface it in the UI.
- Chat endpoints: `POST /papers/{id}/chat` (create session + send message), `GET /papers/{id}/chat/{session_id}` (history). Scope every session to `current_user.id` like the existing paper endpoints do.
- DoD: ask a question about an uploaded paper, get an answer with correct page citations, verify via the actual PDF that the citation is accurate.

### Phase 3 — Summaries + concept explanations
- Summary endpoint: retrieve/aggregate whole-paper structure (e.g. concatenate section-level chunks) and summarize via LLM. Cache the result on `UploadedPaper` (add a `summary` column or store in `paper_metadata` JSONB) rather than regenerating every request.
- Concept explanation endpoint: takes a term/phrase + paper context, explains it. **Support difficulty levels** (e.g. `beginner` / `intermediate` / `expert`) via prompt variation — same retrieval, different system prompt.
- DoD: generate a summary once, confirm it's cached and not regenerated on repeat requests; explain the same concept at two difficulty levels and confirm the outputs are meaningfully different.

### Phase 4 — Multi-paper Q&A
- Extend chat to accept multiple `paper_id`s in a session — retrieval pulls from the combined chunk pool across those papers, answer should reference which paper each cited chunk came from.
- DoD: ask a comparison question across two uploaded papers and get an answer citing both correctly.

### Phase 5 — Frontend redesign
These items were deferred earlier in the project so functional work could proceed without getting blocked on visual polish. They're now in scope. Full detail lives in `TODO.md` at the project root — read it before starting this phase, since it may have been updated since this file was written.

- **Ask the user what kind of frontend/visual direction they want before writing any redesign code.** Do not default to a generic style — offer directions like clean/minimal, colorful/playful, or dashboard-dense (Linear/Notion-style), or ask if they have something else in mind. Get the direction first, then design.
- Homepage redesign — replace the current tech-stack/architecture description with an actual product-style homepage: hero section, value proposition ("Upload a paper, ask it anything"), CTA to sign up / go to dashboard.
- Full frontend redesign pass — not just the homepage. Covers dashboard, chat interface, upload flow, and overall visual polish across the app.
- Remove the Architecture page from user-facing navigation — either remove the page entirely or at minimum unlink it from nav.
- Citation label clarity — citation pills currently show abbreviated labels like "S1 · pp. 1-2" which isn't self-explanatory to a first-time viewer. Spell it out (e.g. "Source 1, pages 1-2") or add a tooltip/legend explaining the format. Likely folds naturally into the redesign pass.
- DoD: visual direction confirmed with the user before any redesign code is written; homepage and Architecture-page changes live; citation labels are self-explanatory without prior context.

### Phase 6 — Production polish
- Move long-running work (chunking/embedding) off `BackgroundTasks` and onto a real queue (Celery or RQ + Redis) if response times or reliability become an issue with `BackgroundTasks`.
- **Evaluation harness**: a small fixed set of test papers + hand-written expected Q&A pairs, plus a script that runs retrieval+answering against them and scores relevance/accuracy. This is a strong differentiator for the resume — most similar student projects have no eval at all.
- Rate limiting on LLM-calling endpoints; log LLM call latency/cost per request.
- Frontend: replace any placeholder/mock dashboard stats with real data (uploaded paper count, processing status, recent chat activity).
- DoD: eval script produces a score report; dashboard reflects real backend state end-to-end.

---

## Coding Conventions
- Keep the existing folder pattern: routers stay thin (validation + call service), services hold logic, models stay pure ORM.
- Every new resource (chunks, embeddings, chat sessions) must scope queries to `current_user.id`, following the existing `get_user_paper_by_id` pattern — don't introduce an authorization gap while adding features.
- Type hints throughout (existing code already does this — match the style).
- Long-running work triggered from a request handler must update a status field the frontend can poll — no silent background failures.

## Working Notes for Claude Code
- Read this file plus the actual current code before starting each phase — the codebase will have moved since this file was written.
- Work phase by phase, in order; Phase 1 (chunking/embeddings) is the actual foundation everything else depends on, so don't skip ahead to chat before it's solid.
- After each phase, report exact manual verification steps/commands, and don't proceed to the next phase until those are confirmed working.
- If the LLM provider decision (local vs hosted) hasn't been made yet, stop and ask before starting Phase 2 — it affects the service interface design.
- Backend phases (1-4, 6) come before the frontend redesign (Phase 5) is meant to start, but functional UI for each backend phase (chat interface, summary/concept-explanation UI, etc.) should still be built alongside its backend phase so the feature is actually usable — Phase 5 is about visual redesign of the whole app, not the first UI for a feature.
- Check `TODO.md` at the project root before starting Phase 5 — it's the source of truth for deferred frontend work and may have been updated since this file was last edited.
