-- Template v2: 14 prompts in four groups, built around task follow-through and social prep.
-- Old prompts are retired (active = 0), never deleted, so earlier answers stay readable.

ALTER TABLE sections ADD COLUMN category TEXT NOT NULL DEFAULT 'core';

-- Retire the prompts that v2 replaces or drops.
UPDATE sections SET active = 0, category = 'retired'
 WHERE key IN ('random_thoughts', 'grateful', 'work_wins', 'personal_wins', 'life_advice',
               'pattern', 'putting_off', 'noticed');

-- Same meaning, sharper wording: keep the key so history stays continuous.
UPDATE sections SET
    label = 'Did I finish yesterday''s tasks? For anything carried over or dropped, what happened at the exact moment I chose not to do it?',
    sort = 10, category = 'core'
 WHERE key = 'yesterday';
UPDATE sections SET
    label = 'Todo list (realistic commitments for today, not a wishlist)',
    sort = 20, category = 'core'
 WHERE key = 'todos';

INSERT INTO sections (key, label, sort, kind, category) VALUES
    ('moved_forward',   'What did I actually move forward or finish today (work or personal), however small?', 30, 'text', 'core'),
    ('mental_ram',      'What is occupying the most mental RAM right now?',                                    40, 'text', 'core'),

    ('atomic_breakdown','Pick one heavy task or project I''m avoiding: what are the first three stupidly small, physical steps to start it (less than 10 minutes each)?', 50, 'text', 'todo_incubator'),
    ('next_action',     'If I had 45 minutes of uninterrupted 4/5 energy right now, what is the single highest-leverage thing I should work on next, and what is blocking me from starting it immediately?', 60, 'text', 'todo_incubator'),
    ('horizon',         'Which of my bigger goals did today''s actions actually move forward, or did I spend the day reacting to urgent noise?', 70, 'text', 'todo_incubator'),
    ('good_enough',     'Where did I overcomplicate, over-research, or build a tool/system today instead of doing the thing itself?', 80, 'text', 'todo_incubator'),

    ('story_bank',      'One funny, weird, or interesting thing that happened, or a fact/rabbit-hole I learned today, phrased how I''d tell it to a friend in 3 sentences:', 90, 'text', 'social_incubator'),
    ('open_loops',      'Who did I talk to today, what did they mention they care about or are dealing with, and what is one question I should ask them next time I see them?', 100, 'text', 'social_incubator'),
    ('social_prep',     'Who am I likely to interact with tomorrow, and what are two topics, questions, or updates I can bring into that conversation?', 110, 'text', 'social_incubator'),
    ('mirror',          'What did I notice about someone else''s behavior today, and what did my reaction to them say about me?', 120, 'text', 'social_incubator'),

    ('escape_hatch',    'Where did my time or attention leak today when I was supposed to be doing something else, and what feeling was I trying to escape?', 130, 'text', 'psych'),
    ('loud_voice',      'What was the sharpest excuse, self-criticism, or "should" statement that ran through my head today?', 140, 'text', 'psych');

-- Keep retired prompts after the live ones, in their old relative order.
UPDATE sections SET sort = sort + 1000 WHERE active = 0;
