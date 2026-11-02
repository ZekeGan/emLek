-- Tags that a rule attached (the tag's own name or alias found in the text) get their own
-- provenance, 'rule', so they can be told apart from what a person or an AI chose and removed
-- together. SQLite cannot change a CHECK, so the table is rebuilt.
CREATE TABLE record_tags_new (
    record_id INTEGER NOT NULL REFERENCES records (id),
    tag_id INTEGER NOT NULL REFERENCES tags (id),
    added_by TEXT NOT NULL CHECK (added_by IN ('user', 'ai', 'rule')),
    added_at TEXT NOT NULL,
    PRIMARY KEY (record_id, tag_id)
) STRICT, WITHOUT ROWID;

INSERT INTO record_tags_new (record_id, tag_id, added_by, added_at)
SELECT record_id, tag_id, added_by, added_at FROM record_tags;

DROP TABLE record_tags;
ALTER TABLE record_tags_new RENAME TO record_tags;
CREATE INDEX idx_record_tags_tag ON record_tags (tag_id, record_id);
