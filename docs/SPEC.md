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
- Template sections live in the `sections` table (key, label, sort, kind, active, category), so prompts
  can change later without breaking old entries. Kinds: `text`, `todos`, `yesterday`. A prompt is
  retired with `active = 0`, never deleted; an entry that has an answer under a retired prompt still
  shows it (day page, export, history, LLM context).
- Template v2 (migration 004), 14 prompts in four groups that can be collapsed on the day page:
  - **Daily spine** (`core`): yesterday's autopsy (`yesterday`), realistic commitments (`todos`),
    what I moved forward (`moved_forward`), grateful for (`grateful`, restored in migration 005),
    mental RAM (`mental_ram`).
  - **Next actions** (`todo_incubator`): first three tiny steps (`atomic_breakdown`), highest-leverage
    next action (`next_action`), which bigger goal moved (`horizon`), overcomplication check
    (`good_enough`).
  - **People and stories** (`social_incubator`): story bank (`story_bank`), open loops about people
    (`open_loops`), tomorrow's social prep (`social_prep`), the mirror (`mirror`).
  - **Inner signal** (`psych`): attention leaks and the feeling behind them (`escape_hatch`), loudest
    internal voice (`loud_voice`).
  - The `category` and the section keys are stable handles that future tools (a social prep app, a task
    decomposer) can query: `SELECT content FROM entry_sections WHERE section_key = 'story_bank'`.
  - Retired in v2: random thoughts, work wins, personal wins, life advice, mental pattern,
    putting off, noticed about another person.
- Autosave on an 800ms debounce and on blur, one request at a time per section. Empty days are not
  created just by viewing.
- Mood and energy (1–5, click again to clear) and free-form tags.

## Todos

- An item is created on a day and stays open until completed or dropped.
- Visible on day D when `created_day <= D`, not completed before D, and not dropped on or before D.
- "Carried Nd" badge shows days since creation (highlighted at 3+).
- Todo text can be edited in place (hover, "edit"; Enter saves, Escape cancels). A drop can be undone on
  the same day only ("Dropped today: … undo"), so earlier reports are never rewritten.
- Todos added from a review carry `source_review_id`, show a "panel" badge linking to the review, and
  are marked "(suggested by a panel review)" in LLM context so later reviews can judge follow-through.
- "Did I finish yesterday's tasks?" lists the items that were open yesterday with their outcome as of
  that day (done, finished later, dropped that day, not done and dropped later, not done), followed by
  a free-text reflection. A later drop never rewrites earlier reports.
- A day counts as having content if it has text, mood, energy or tags, or if a todo was added,
  finished or dropped that day.

## History and search

- Reverse-chronological list with mood, energy, word count, tags and first line.
- SQLite FTS5 (`unicode61`), each search word is a prefix match.

## Export

- `DATA_DIR/export/YYYY/YYYY-MM-DD.md` with YAML front matter (date, mood, energy, tags), one
  `##` heading per section that has content (empty prompts are left out), todos as task-list items.
- Runs nightly at `EXPORT_HOUR` and on demand from the History page; only changed files are written.

## Import (Phase 1b)

- One-off importer for existing Markdown entries written with the manual template. Format to be
  matched against real samples.

## LLM (Phases 2–4)

### Client
- `LLM_BASE_URL`, `LLM_MODEL` from env. 600s timeout, no retry (a slow model will not be faster the second
  time, and on a single-slot server the retry queues behind the abandoned request).
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
- Perspectives (11, each with a `default` flag for the Review page checkboxes): Stoic, Aristotelian\*,
  Existentialist, CBT, ACT\*, Psychodynamic, IFS\*, Skeptic, Strengths Coach, Systems Architect
  (task granularity, activation energy, productive procrastination), Social Coach (conversation prep,
  curiosity about others, follow-through on open loops). \* = off by default; the other eight are on.
- Markdown output, one `## <Perspective>` per perspective with **Read**, **Challenge**,
  **Action** (doable within 48h) and **Confidence**, then **Where the panel disagrees**.
- Optional final section **Distilled actions** (on by default): the panel's 1-3 most important actions,
  each a small physical step under 30 minutes, not duplicating open todos, as `- ACTION: …` lines. They
  are parsed into `reviews.actions` (JSON `[{text, todo_id}]`) and shown under the review with editable
  text and an "Add to tomorrow" button, which creates a todo dated the next logical day. Nothing is added
  automatically.
- Stored in `reviews` with a `parent_id` reserved for threaded follow-ups later.

### Summaries and profile (Phase 3, implemented)
- **Weekly summaries** (Monday–Sunday, 300–500 words, factual, dated citations). Only complete weeks
  are summarized. Mood/energy averages and todo flow are computed in code and handed to the model as
  facts. Generated with `LLM_SUMMARY_THINKING` (default off) at temperature 0.3.
- **Monthly summaries** are built from the weekly ones (about 600 words). A "month block" is the set of
  weeks whose Monday falls in a calendar month, so blocks never overlap or leave gaps. A block with only
  one content week gets no monthly summary.
- **Staleness:** a weekly summary records the newest `updated_at` of its entries; editing any of them
  later marks it outdated. A monthly summary is outdated if any of its weeks was regenerated.
- **Catch up summaries** (manual) regenerates every missing or outdated week, then the months. Each
  summary is saved as it completes, so a failure partway keeps the finished work and a rerun resumes.
- **Review/profile context layers:** profile, then monthly summaries for months older than 13 weeks
  before the verbatim part, weekly summaries after that, then verbatim entries (whole weeks, at least
  the last 14 days). Weeks with no summary yet are included verbatim. Over budget, the oldest verbatim
  weeks that have a summary are swapped for it first; only then are the oldest pieces dropped, and the
  task prompt says what was left out.
- **Profile** (read-only, versioned): stated vs. enacted values, strengths, weaknesses and blind spots,
  recurring patterns, relationships and social patterns (and how you see others), work, goals and task
  execution mechanics, what's still unknown, what changed. Every claim carries
  dated evidence and a confidence tag. The first version reads all history through yesterday; each update
  reads the previous profile plus only what is new since it. A banner suggests an update after 5 days of
  entries (first profile) or 7 new days (later updates).
- Pages: `/profile`, `/profile/{id}`, `/summaries`.

### Questions (Phase 4)
- The LLM generates batches of 3–5 questions as JSON (`question, category, why, repeat_of_id`),
  targeting profile gaps. Categories: values, strengths, weaknesses, relationships, work, habits,
  fears, goals, identity, `social_prep` (flesh out a story, name who to get closer to, dissect an awkward
  interaction) and `task_breakdown` (take a long-term goal from the profile or a todo carried 7+ days and
  break it down on the spot). Answer, skip, or regenerate.
- Questions can be re-asked after 60+ days; answers are kept as a history per question.

## Trends (Phase 5)

Mood and energy over time, todo completion rate, average days carried, entry streak.

## Security (LAN only, no login)

- Host check: only IPs, `localhost`, single-label names, `.local`/`.lan`/`.home`/`.home.arpa`/
  `.internal`/`.localdomain` names, and anything in `ALLOWED_HOSTS` are served. This blocks DNS
  rebinding, where a website points its own domain at the LAN address to read the journal.
- Origin check: POST/PUT/PATCH/DELETE with an `Origin` header from another site are refused (403).
- Autosave sends one request at a time per section, so an older save can never overwrite a newer one.

## Deployment

- `python:3.12-slim`, entrypoint chowns `/data` to `PUID:PGID` (99:100) and drops root.
- Port 8480, `/data` → `/mnt/user/appdata/know-thy-self`.
- GitHub Actions builds and pushes `ghcr.io/<owner>/know-thy-self` (`latest` on main,
  `sha-<short>`, tags). Private repo → GHCR pull token on Unraid.
- Unraid container template in `unraid/`.

## Later

Daily nudge, editing the profile, review follow-up threads, iOS app, mobile layout, backups.
