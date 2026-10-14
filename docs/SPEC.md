# Know Thy Self — v1 spec

Single-user, LAN-only, desktop-first, dark mode. One container on Unraid.

## Goals

- A daily journal with a fixed template, so writing every day is low-friction.
- Track follow-through (todos that carry over) and simple metadata (mood, energy, tags).
- A local LLM (Gemma via an OpenAI-compatible endpoint) that reviews entries bluntly from a panel
  of perspectives, maintains a read-only profile, and asks questions that fill gaps in it.
- Data stays portable: SQLite is the source of truth, with a nightly Markdown export.

## Stack

FastAPI + Jinja2 templates + small vanilla JS (no build step), stdlib `sqlite3` with a
`PRAGMA user_version` migration runner, `httpx` for LLM calls. Single Uvicorn worker.

## Journal

- One entry per **logical day**: a day rolls over at `DAY_CUTOFF_HOUR` (default 4am) local time.
- Template sections live in the `sections` table (key, label, sort, kind, active), so prompts can
  change later without breaking old entries. Kinds: `text`, `todos`, `yesterday`.
- Sections: daily random thoughts; grateful for; work accomplishments; personal successes; life
  advice; todo list; mental pattern to break; something I've put off; did I finish yesterday's
  tasks; something I noticed about another person.
- Autosave on an 800ms debounce and on blur. Empty days are not created just by viewing.
- Mood and energy (1–5, click again to clear) and free-form tags.

## Todos

- An item is created on a day and stays open until completed or dropped.
- Visible on day D when `created_day <= D`, not completed before D, and not dropped on or before D.
- "Carried Nd" badge shows days since creation (highlighted at 3+).
- "Did I finish yesterday's tasks?" lists the items that were open yesterday with their outcome
  (done, finished later, dropped, not done), followed by a free-text reflection.

## History and search

- Reverse-chronological list with mood, energy, word count, tags and first line.
- SQLite FTS5 (`unicode61`), each search word is a prefix match.

## Export

- `DATA_DIR/export/YYYY/YYYY-MM-DD.md` with YAML front matter (date, mood, energy, tags), one
  `##` heading per section, todos as task-list items.
- Runs nightly at `EXPORT_HOUR` and on demand from the History page; only changed files are written.

## Import (Phase 1b)

- One-off importer for existing Markdown entries written with the manual template. Format to be
  matched against real samples.

## LLM (Phases 2–4)

### Client
- `LLM_BASE_URL`, `LLM_MODEL` from env. 600s timeout, one retry on timeout.
- Reachability check (`GET /v1/models`, 3s) before each job; if unreachable, fail with a clear
  message and a retry button. No queueing.
- One LLM call at a time (asyncio lock), matching the server's single slot.
- Read `content` only; reasoning is discarded. `max_tokens` 16384 so thinking can't starve the
  answer; an empty `content` with `finish_reason: length` is reported as an error.
- Jobs run in the background; the page polls their status.

### Context (fixed order, for prefix caching)
1. Fixed system prompt
2. Current profile
3. Monthly summaries (oldest first)
4. Weekly summaries for the last ~3 months
5. Entries verbatim for the requested scope (at least the last 14 days)
6. Recent question/answer pairs
7. Task instruction (always last)

Budget `CONTEXT_BUDGET_TOKENS` (90k, chars/4 estimate). Over budget, the oldest verbatim
entries fall back to their weekly summaries.

### Shared rules
No flattery or filler; no reassurance the evidence doesn't support. Cite entries as
`[YYYY-MM-DD]`. Mark claims resting on fewer than 3 data points as *thin evidence*. Name
contradictions between stated values and behaviour. Challenge self-assessments that are inflated
and ones that are too harsh. No clinical diagnoses.

### Review panel (Phase 2)
- Scope: today / 7d (default) / 30d / all. Perspective checkboxes, all on by default.
- Perspectives: Stoic, Existentialist, CBT, ACT, Psychodynamic, IFS, Skeptic, Strengths Coach.
- Markdown output, one `## <Perspective>` per perspective with **Read**, **Challenge**,
  **Action** (doable within 48h) and **Confidence**, then **Where the panel disagrees**.
- Stored in `reviews` with a `parent_id` reserved for threaded follow-ups later.

### Summaries and profile (Phase 3)
- Weekly summaries (300–500 words, factual, dated citations); monthly summaries from weeklies.
- A summary is stale if any covered entry was edited after it was generated.
- Profile versions (read-only): stated vs enacted values, strengths, weaknesses and blind spots,
  recurring patterns, how I see others, work, what's still unknown, what changed. Each claim has
  evidence dates and a confidence level.
- Manual "Catch up summaries" and "Update profile" buttons that process only what's new, plus an
  overdue banner.

### Questions (Phase 4)
- The LLM generates batches of 3–5 questions as JSON (`question, category, why, repeat_of_id`),
  targeting profile gaps. Categories: values, strengths, weaknesses, relationships, work, habits,
  fears, goals, identity. Answer, skip, or regenerate.
- Questions can be re-asked after 60+ days; answers are kept as a history per question.

## Trends (Phase 5)

Mood and energy over time, todo completion rate, average days carried, entry streak.

## Deployment

- `python:3.12-slim`, entrypoint chowns `/data` to `PUID:PGID` (99:100) and drops root.
- Port 8480, `/data` → `/mnt/user/appdata/know-thy-self`.
- GitHub Actions builds and pushes `ghcr.io/<owner>/know-thy-self` (`latest` on main,
  `sha-<short>`, tags). Private repo → GHCR pull token on Unraid.
- Unraid container template in `unraid/`.

## Later

Daily nudge, editing the profile, review follow-up threads, iOS app, mobile layout, backups.
