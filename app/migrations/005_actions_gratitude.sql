-- Distilled review actions, todos that came from them, and the gratitude prompt back in the template.

ALTER TABLE reviews ADD COLUMN actions TEXT;                                  -- JSON list of distilled actions
ALTER TABLE todos ADD COLUMN source_review_id INTEGER REFERENCES reviews(id);  -- set when added from a review

-- Same key as before, so earlier gratitude answers and new ones stay one continuous history.
UPDATE sections SET active = 1, category = 'core', sort = 35 WHERE key = 'grateful';
