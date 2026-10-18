-- Questions page: questions asked directly, your answers, and a few settings.

CREATE TABLE questions (
    id               INTEGER PRIMARY KEY,
    text             TEXT NOT NULL,
    category         TEXT NOT NULL,
    kind             TEXT NOT NULL DEFAULT 'open',    -- open | scale | choice | rank | claim_check
    options          TEXT,                            -- JSON: scale [low label, high label]; choice/rank items
    claim            TEXT,                            -- claim_check: the profile claim being checked
    why              TEXT,                            -- why it is being asked (shown small)
    source           TEXT NOT NULL,                   -- seed | llm | followup
    parent_id        INTEGER REFERENCES questions(id),-- follow-up of this question
    recurring_days   INTEGER,                         -- re-asked every N days after each answer
    status           TEXT NOT NULL DEFAULT 'waiting', -- waiting | answered | never | bad
    available_from   TEXT,                            -- YYYY-MM-DD; hidden from the queue until then
    bad_reason       TEXT,
    sort             INTEGER NOT NULL DEFAULT 0,
    created_at       TEXT NOT NULL,
    updated_at       TEXT NOT NULL
);
CREATE INDEX idx_questions_status ON questions(status);

-- One question can collect several answers over time (recurring or re-asked questions).
CREATE TABLE answers (
    id           INTEGER PRIMARY KEY,
    question_id  INTEGER NOT NULL REFERENCES questions(id) ON DELETE CASCADE,
    day          TEXT NOT NULL,                       -- logical day it was answered
    text         TEXT NOT NULL DEFAULT '',
    value        TEXT,                                -- JSON: scale number, choice, ranked list, claim verdict
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL
);
CREATE INDEX idx_answers_question ON answers(question_id);

CREATE TABLE settings (
    key    TEXT PRIMARY KEY,
    value  TEXT NOT NULL
);

-- Answers are read by the profile like entries: each version records the newest answer it included.
ALTER TABLE profile_versions ADD COLUMN answers_through INTEGER NOT NULL DEFAULT 0;

INSERT INTO settings (key, value) VALUES
    ('questions_focus', 'I want to build a psychological profile and personal history for myself. If I was getting to know a new person deeply, what questions would I ask them. I need to understand myself better, and get a more realistic view, so I can appreciate my strengths, and uncover and work on my weaknesses. I am striving for greatness.'),
    ('questions_muted', '[]');

-- Starter set: asked in this order, interleaved with the model's questions once a profile exists.
-- The first few are easier, the later ones go deeper. Three are recurring every 90 days.
INSERT INTO questions (text, category, kind, options, source, recurring_days, sort, created_at, updated_at) VALUES
('Walk me through your life so far in five chapters. Give each one a title and a sentence about what defined it.', 'history', 'open', NULL, 'seed', NULL, 10, strftime('%Y-%m-%dT%H:%M:%S+00:00', 'now'), strftime('%Y-%m-%dT%H:%M:%S+00:00', 'now')),
('Finish this sentence five different ways: "I am the kind of person who..."', 'identity', 'open', NULL, 'seed', NULL, 20, strftime('%Y-%m-%dT%H:%M:%S+00:00', 'now'), strftime('%Y-%m-%dT%H:%M:%S+00:00', 'now')),
('What do people reliably come to you for? What does that say about what you are actually good at?', 'strengths', 'open', NULL, 'seed', NULL, 30, strftime('%Y-%m-%dT%H:%M:%S+00:00', 'now'), strftime('%Y-%m-%dT%H:%M:%S+00:00', 'now')),
('What does "greatness" mean for you, specifically? Describe what your life looks like in ten years if you get there.', 'goals', 'open', NULL, 'seed', NULL, 40, strftime('%Y-%m-%dT%H:%M:%S+00:00', 'now'), strftime('%Y-%m-%dT%H:%M:%S+00:00', 'now')),
('What does a typical weekday look like for you, from waking up to going to sleep? Be honest, not aspirational.', 'habits', 'open', NULL, 'seed', NULL, 50, strftime('%Y-%m-%dT%H:%M:%S+00:00', 'now'), strftime('%Y-%m-%dT%H:%M:%S+00:00', 'now')),
('What was your home like growing up: who was in it, what was the mood, and what was expected of you?', 'history', 'open', NULL, 'seed', NULL, 60, strftime('%Y-%m-%dT%H:%M:%S+00:00', 'now'), strftime('%Y-%m-%dT%H:%M:%S+00:00', 'now')),
('Rank these by how much they actually drive your choices day to day, not by how much you would like them to.', 'values', 'rank', '["Achievement","Security","Freedom","Recognition","Relationships","Mastery"]', 'seed', NULL, 70, strftime('%Y-%m-%dT%H:%M:%S+00:00', 'now'), strftime('%Y-%m-%dT%H:%M:%S+00:00', 'now')),
('What feedback have you heard more than once, from different people, whether or not you agreed with it?', 'others_view', 'open', NULL, 'seed', NULL, 80, strftime('%Y-%m-%dT%H:%M:%S+00:00', 'now'), strftime('%Y-%m-%dT%H:%M:%S+00:00', 'now')),
('What is something you do well that you tend to dismiss because it comes easily to you?', 'strengths', 'open', NULL, 'seed', NULL, 90, strftime('%Y-%m-%dT%H:%M:%S+00:00', 'now'), strftime('%Y-%m-%dT%H:%M:%S+00:00', 'now')),
('What weakness have you known about for years and still not fixed? What has it cost you so far?', 'weaknesses', 'open', NULL, 'seed', NULL, 100, strftime('%Y-%m-%dT%H:%M:%S+00:00', 'now'), strftime('%Y-%m-%dT%H:%M:%S+00:00', 'now')),
('Who are the five people you spend the most time with, and how does each of them affect you?', 'relationships', 'open', NULL, 'seed', NULL, 110, strftime('%Y-%m-%dT%H:%M:%S+00:00', 'now'), strftime('%Y-%m-%dT%H:%M:%S+00:00', 'now')),
('What is the earliest moment you remember feeling proud of yourself? What had you done?', 'history', 'open', NULL, 'seed', NULL, 120, strftime('%Y-%m-%dT%H:%M:%S+00:00', 'now'), strftime('%Y-%m-%dT%H:%M:%S+00:00', 'now')),
('How accurately do you judge your own abilities? 3 means accurately.', 'weaknesses', 'scale', '["I consistently underrate myself","I consistently overrate myself"]', 'seed', NULL, 130, strftime('%Y-%m-%dT%H:%M:%S+00:00', 'now'), strftime('%Y-%m-%dT%H:%M:%S+00:00', 'now')),
('When do you do your best work? Describe the conditions: time of day, place, energy, people, stakes.', 'work', 'open', NULL, 'seed', NULL, 140, strftime('%Y-%m-%dT%H:%M:%S+00:00', 'now'), strftime('%Y-%m-%dT%H:%M:%S+00:00', 'now')),
('What do you refuse to compromise on, even when it costs you? Give a real example.', 'values', 'open', NULL, 'seed', NULL, 150, strftime('%Y-%m-%dT%H:%M:%S+00:00', 'now'), strftime('%Y-%m-%dT%H:%M:%S+00:00', 'now')),
('How would your closest friend describe you to a stranger? Now, how would someone who dislikes you describe you?', 'others_view', 'open', NULL, 'seed', NULL, 160, strftime('%Y-%m-%dT%H:%M:%S+00:00', 'now'), strftime('%Y-%m-%dT%H:%M:%S+00:00', 'now')),
('In a conflict, what do you usually do first?', 'relationships', 'choice', '["Withdraw and go quiet","Argue my case","Smooth it over","Try to fix the problem","Get even later"]', 'seed', NULL, 170, strftime('%Y-%m-%dT%H:%M:%S+00:00', 'now'), strftime('%Y-%m-%dT%H:%M:%S+00:00', 'now')),
('Describe a recent day that felt genuinely worth it. What made it so?', 'meaning', 'open', NULL, 'seed', NULL, 180, strftime('%Y-%m-%dT%H:%M:%S+00:00', 'now'), strftime('%Y-%m-%dT%H:%M:%S+00:00', 'now')),
('When you are stressed, what do you reach for first?', 'habits', 'choice', '["Screens or games","Food","Working harder","Other people","Exercise","Sleep or withdrawing"]', 'seed', NULL, 190, strftime('%Y-%m-%dT%H:%M:%S+00:00', 'now'), strftime('%Y-%m-%dT%H:%M:%S+00:00', 'now')),
('What is a failure or embarrassment from your past that still shapes how you act today?', 'history', 'open', NULL, 'seed', NULL, 200, strftime('%Y-%m-%dT%H:%M:%S+00:00', 'now'), strftime('%Y-%m-%dT%H:%M:%S+00:00', 'now')),
('What is the biggest project you keep not starting? Write its first three ten-minute steps.', 'task_breakdown', 'open', NULL, 'seed', NULL, 210, strftime('%Y-%m-%dT%H:%M:%S+00:00', 'now'), strftime('%Y-%m-%dT%H:%M:%S+00:00', 'now')),
('Who has influenced you most, for better or worse, and what did you take from them?', 'history', 'open', NULL, 'seed', NULL, 220, strftime('%Y-%m-%dT%H:%M:%S+00:00', 'now'), strftime('%Y-%m-%dT%H:%M:%S+00:00', 'now')),
('If you knew you could not fail, what would you start next month? What actually stops you?', 'fears', 'open', NULL, 'seed', NULL, 230, strftime('%Y-%m-%dT%H:%M:%S+00:00', 'now'), strftime('%Y-%m-%dT%H:%M:%S+00:00', 'now')),
('Tell a story about yourself that you would want a new friend to hear, in under five sentences.', 'social_prep', 'open', NULL, 'seed', NULL, 240, strftime('%Y-%m-%dT%H:%M:%S+00:00', 'now'), strftime('%Y-%m-%dT%H:%M:%S+00:00', 'now')),
('Looking at the picture of greatness you described: what is the gap between it and where you are now, and which part of that gap is fully in your control?', 'goals', 'open', NULL, 'seed', NULL, 250, strftime('%Y-%m-%dT%H:%M:%S+00:00', 'now'), strftime('%Y-%m-%dT%H:%M:%S+00:00', 'now')),
('What are you most afraid people would find out about you?', 'fears', 'open', NULL, 'seed', NULL, 260, strftime('%Y-%m-%dT%H:%M:%S+00:00', 'now'), strftime('%Y-%m-%dT%H:%M:%S+00:00', 'now')),
('What do you want most right now?', 'goals', 'open', NULL, 'seed', 90, 270, strftime('%Y-%m-%dT%H:%M:%S+00:00', 'now'), strftime('%Y-%m-%dT%H:%M:%S+00:00', 'now')),
('What are you avoiding right now?', 'fears', 'open', NULL, 'seed', 90, 280, strftime('%Y-%m-%dT%H:%M:%S+00:00', 'now'), strftime('%Y-%m-%dT%H:%M:%S+00:00', 'now')),
('What are you proudest of from the last three months?', 'strengths', 'open', NULL, 'seed', 90, 290, strftime('%Y-%m-%dT%H:%M:%S+00:00', 'now'), strftime('%Y-%m-%dT%H:%M:%S+00:00', 'now'));
