-- Template v3: long-term goals at the top, eight prompts in two groups, everything else retired.

-- Long-term goals: a title, tracked until achieved or dropped. No dates to hit, no daily check-ins.
CREATE TABLE goals (
    id            INTEGER PRIMARY KEY,
    text          TEXT NOT NULL,
    created_day   TEXT NOT NULL,
    done_day      TEXT,              -- achieved
    dropped_day   TEXT,
    created_at    TEXT NOT NULL
);

-- A todo can be a step toward a goal (added with the goal's "+ today" button).
ALTER TABLE todos ADD COLUMN source_goal_id INTEGER REFERENCES goals(id);

-- Retire the prompts v3 removes. Answers under them stay readable on their days.
UPDATE sections SET active = 0, category = 'retired', sort = sort + 1000
 WHERE active = 1 AND key IN ('atomic_breakdown', 'next_action', 'horizon', 'good_enough', 'story_bank',
                              'open_loops', 'social_prep', 'mirror', 'escape_hatch', 'loud_voice');

INSERT INTO sections (key, label, sort, kind, category) VALUES
    ('long_goals', 'Long-term goals', 10, 'goals', 'core');

UPDATE sections SET label = 'Goals for today', sort = 20, category = 'core' WHERE key = 'todos';
UPDATE sections SET label = 'Did I finish yesterday''s goals? If not, what got in the way?', sort = 30, category = 'core'
 WHERE key = 'yesterday';
UPDATE sections SET label = 'What did I move forward or finish today, however small?', sort = 40, category = 'core'
 WHERE key = 'moved_forward';
UPDATE sections SET sort = 50, category = 'core' WHERE key = 'grateful';
-- Same intent as "mental RAM", in plain words; the key stays so the history is continuous.
UPDATE sections SET label = 'What''s on my mind right now?', sort = 60, category = 'core' WHERE key = 'mental_ram';

INSERT INTO sections (key, label, sort, kind, category) VALUES
    ('conversation', 'Something worth talking about: a topic, an idea, or something I''ve been into lately', 70, 'text', 'grab_bag'),
    ('dreams', 'Did I dream last night? What do I remember?', 80, 'text', 'grab_bag');
