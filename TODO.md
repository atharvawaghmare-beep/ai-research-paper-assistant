# TODO — Deferred Work

These items are intentionally deferred until after Phase 3/4 (RAG feature set) are functionally complete, per project decision on 2026-08-29. Do not start on these until the user explicitly says to.

## Frontend Redesign (deferred)

1. **Homepage redesign** — current homepage describes the tech stack/architecture (leftover from initial scaffolding). Replace with an actual product-style homepage: hero section, value proposition ("Upload a paper, ask it anything"), CTA to sign up / go to dashboard.

2. **Full frontend redesign pass** — not just the homepage. Covers dashboard, chat interface, upload flow, and overall visual polish across the app. Scope is the whole UI, not a single page.

3. **Remove the Architecture page from user-facing navigation** — user decided against keeping a tech-stack/architecture page visible to end users. Either remove the page entirely or at minimum unlink it from nav (user's call when this is picked up).

4. **Citation label clarity** — in the chat interface, citation pills currently show abbreviated labels like "S1 · pp. 1-2" which isn't self-explanatory to a first-time viewer. Spell it out (e.g. "Source 1, pages 1-2") or add a tooltip/legend explaining the citation format. This will likely be folded into the redesign pass rather than done standalone.

## IMPORTANT — Before starting the redesign

**Ask the user what kind of frontend/visual direction they want before writing any redesign code.** Do not default to a generic style. Examples of directions to offer as options: clean/minimal, colorful/playful, dashboard-dense (Linear/Notion-style), or something else the user has in mind. "Make it better" without a stated direction tends to produce generic-looking output — get the direction first, then design.

---

*This file is a working checklist, not a spec. Once the redesign begins, feel free to expand each item into its own section with more detail, or delete completed items.*
