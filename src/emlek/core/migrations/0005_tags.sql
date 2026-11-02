-- M7 tags: a hand-made index on top of the records. Tags never alter the text. They hang on the
-- record (not on a version), know who added them, and have a small hierarchy plus aliases.
CREATE TABLE tags (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL CHECK (length(name) BETWEEN 1 AND 64),
    name_key TEXT NOT NULL UNIQUE,
    type TEXT NOT NULL CHECK (type IN ('place', 'person', 'topic', 'activity', 'emotion', 'status')),
    description TEXT NOT NULL DEFAULT '' CHECK (length(description) <= 200),
    created_by TEXT NOT NULL CHECK (created_by IN ('user', 'ai', 'system')),
    created_at TEXT NOT NULL
) STRICT;

CREATE TABLE record_tags (
    record_id INTEGER NOT NULL REFERENCES records (id),
    tag_id INTEGER NOT NULL REFERENCES tags (id),
    added_by TEXT NOT NULL CHECK (added_by IN ('user', 'ai')),
    added_at TEXT NOT NULL,
    PRIMARY KEY (record_id, tag_id)
) STRICT, WITHOUT ROWID;

CREATE INDEX idx_record_tags_tag ON record_tags (tag_id, record_id);

CREATE TABLE tag_links (
    parent_tag_id INTEGER NOT NULL REFERENCES tags (id),
    child_tag_id INTEGER NOT NULL REFERENCES tags (id),
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (parent_tag_id, child_tag_id),
    CHECK (parent_tag_id <> child_tag_id)
) STRICT, WITHOUT ROWID;

CREATE INDEX idx_tag_links_child ON tag_links (child_tag_id);

CREATE TABLE tag_aliases (
    alias TEXT NOT NULL,
    alias_key TEXT PRIMARY KEY,
    tag_id INTEGER NOT NULL REFERENCES tags (id),
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL
) STRICT, WITHOUT ROWID;

CREATE INDEX idx_tag_aliases_tag ON tag_aliases (tag_id);

-- What changed in the tag system, never record text. record_id lets a purge find its own rows.
CREATE TABLE tag_events (
    id INTEGER PRIMARY KEY,
    at TEXT NOT NULL,
    actor TEXT NOT NULL,
    action TEXT NOT NULL,
    record_id INTEGER,
    detail TEXT NOT NULL
) STRICT;

CREATE INDEX idx_tag_events_record ON tag_events (record_id);

-- Small full-text index over a tag's name, aliases and description (rowid = tag id).
CREATE VIRTUAL TABLE tags_fts USING fts5 (text, tokenize = 'trigram');

-- The four fixed status tags the daily briefing relies on.
INSERT INTO tags (name, name_key, type, created_by, created_at)
SELECT name, name, 'status', 'system', strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
FROM (
    SELECT '待辦' AS name
    UNION ALL SELECT '截止'
    UNION ALL SELECT '約定'
    UNION ALL SELECT '已完成'
);

INSERT INTO tags_fts (rowid, text) SELECT id, name_key FROM tags;
