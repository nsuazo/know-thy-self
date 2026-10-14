-- Background LLM jobs (status is polled by the UI).
CREATE TABLE llm_jobs (
    id           INTEGER PRIMARY KEY,
    kind         TEXT NOT NULL,                       -- review | (later) summary | profile | questions
    status       TEXT NOT NULL,                       -- queued | running | done | error
    params       TEXT NOT NULL DEFAULT '{}',          -- JSON
    error        TEXT,
    result_id    INTEGER,
    created_at   TEXT NOT NULL,
    started_at   TEXT,
    finished_at  TEXT
);

-- Finished review panels. parent_id is reserved for threaded follow-ups later.
CREATE TABLE reviews (
    id                INTEGER PRIMARY KEY,
    parent_id         INTEGER REFERENCES reviews(id),
    scope             TEXT NOT NULL,                  -- today | 7d | 30d | all
    range_start       TEXT,
    range_end         TEXT,
    perspectives      TEXT NOT NULL,                  -- JSON list of perspective keys
    content           TEXT NOT NULL,                  -- Markdown, final answer only
    model             TEXT,
    prompt_tokens     INTEGER,
    completion_tokens INTEGER,
    seconds           REAL,
    entries_included  INTEGER,
    entries_omitted   INTEGER,
    created_at        TEXT NOT NULL
);
CREATE INDEX idx_reviews_created ON reviews(created_at);
