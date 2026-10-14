-- Template sections. kind: text | todos | yesterday
CREATE TABLE sections (
    key     TEXT PRIMARY KEY,
    label   TEXT NOT NULL,
    sort    INTEGER NOT NULL,
    kind    TEXT NOT NULL DEFAULT 'text',
    active  INTEGER NOT NULL DEFAULT 1
);

INSERT INTO sections (key, label, sort, kind) VALUES
    ('random_thoughts', 'Daily random thoughts',                                              10, 'text'),
    ('grateful',        'Things to be grateful for today',                                    20, 'text'),
    ('work_wins',       'Things you accomplished recently at work',                           30, 'text'),
    ('personal_wins',   'Recent personal successes',                                          40, 'text'),
    ('life_advice',     'Life advice',                                                        50, 'text'),
    ('todos',           'Todo list',                                                          60, 'todos'),
    ('pattern',         'Mental pattern you need to break out of',                            70, 'text'),
    ('putting_off',     'Something that I have been putting off that I will accomplish today', 80, 'text'),
    ('yesterday',       'Did I finish yesterday''s tasks?',                                    90, 'yesterday'),
    ('noticed',         'Something you noticed about another person',                         100, 'text');

-- One entry per logical day.
CREATE TABLE entries (
    id          INTEGER PRIMARY KEY,
    day         TEXT NOT NULL UNIQUE,              -- YYYY-MM-DD
    mood        INTEGER CHECK (mood BETWEEN 1 AND 5),
    energy      INTEGER CHECK (energy BETWEEN 1 AND 5),
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

CREATE TABLE entry_sections (
    entry_id     INTEGER NOT NULL REFERENCES entries(id) ON DELETE CASCADE,
    section_key  TEXT NOT NULL,
    content      TEXT NOT NULL DEFAULT '',
    updated_at   TEXT NOT NULL,
    PRIMARY KEY (entry_id, section_key)
);

CREATE TABLE tags (
    id    INTEGER PRIMARY KEY,
    name  TEXT NOT NULL UNIQUE COLLATE NOCASE
);

CREATE TABLE entry_tags (
    entry_id  INTEGER NOT NULL REFERENCES entries(id) ON DELETE CASCADE,
    tag_id    INTEGER NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
    PRIMARY KEY (entry_id, tag_id)
);

-- Todos carry forward until completed or dropped.
-- Visible on day D when created_day <= D
--   AND (completed_day IS NULL OR completed_day >= D)
--   AND (dropped_day IS NULL OR dropped_day > D).
CREATE TABLE todos (
    id             INTEGER PRIMARY KEY,
    text           TEXT NOT NULL,
    created_day    TEXT NOT NULL,
    completed_day  TEXT,
    dropped_day    TEXT,
    created_at     TEXT NOT NULL
);
CREATE INDEX idx_todos_created ON todos(created_day);

-- Full-text search over each entry's combined text; rowid = entries.id.
CREATE VIRTUAL TABLE entries_fts USING fts5(body, tokenize = 'unicode61 remove_diacritics 2');
