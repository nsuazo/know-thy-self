-- Job progress, shown while a multi-step job (summary catch-up) runs.
ALTER TABLE llm_jobs ADD COLUMN progress_done  INTEGER NOT NULL DEFAULT 0;
ALTER TABLE llm_jobs ADD COLUMN progress_total INTEGER NOT NULL DEFAULT 0;
ALTER TABLE llm_jobs ADD COLUMN progress_label TEXT;

ALTER TABLE reviews ADD COLUMN summaries_used INTEGER NOT NULL DEFAULT 0;

-- Weekly summaries (Monday..Sunday) and monthly summaries (built from weekly ones).
-- A month block is the set of weeks whose Monday falls in that calendar month, so
-- start_day/end_day for a month are the first Monday and the last Sunday of the block.
CREATE TABLE summaries (
    id                INTEGER PRIMARY KEY,
    period            TEXT NOT NULL CHECK (period IN ('week', 'month')),
    start_day         TEXT NOT NULL,
    end_day           TEXT NOT NULL,
    content           TEXT NOT NULL,
    -- week: newest entries.updated_at it was built from; month: newest weekly created_at.
    -- A summary is stale when the current value is newer than this.
    source_updated_at TEXT NOT NULL,
    entries_count     INTEGER NOT NULL DEFAULT 0,
    model             TEXT,
    seconds           REAL,
    created_at        TEXT NOT NULL,
    UNIQUE (period, start_day)
);

-- Read-only, versioned profile of the author.
CREATE TABLE profile_versions (
    id                INTEGER PRIMARY KEY,
    version           INTEGER NOT NULL UNIQUE,
    content           TEXT NOT NULL,
    covers_from       TEXT NOT NULL,
    covers_through    TEXT NOT NULL,
    entries_count     INTEGER NOT NULL DEFAULT 0,
    summaries_used    INTEGER NOT NULL DEFAULT 0,
    model             TEXT,
    prompt_tokens     INTEGER,
    completion_tokens INTEGER,
    seconds           REAL,
    created_at        TEXT NOT NULL
);
