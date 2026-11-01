CREATE TABLE meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
) STRICT;

CREATE TABLE records (
    id INTEGER PRIMARY KEY,
    created_at TEXT NOT NULL,
    hidden INTEGER NOT NULL DEFAULT 0 CHECK (hidden IN (0, 1)),
    hidden_at TEXT,
    sensitivity TEXT NOT NULL DEFAULT 'none' CHECK (sensitivity IN ('none', 'medium', 'high'))
) STRICT;

CREATE TABLE revisions (
    id INTEGER PRIMARY KEY,
    record_id INTEGER NOT NULL REFERENCES records (id),
    version_no INTEGER NOT NULL CHECK (version_no >= 1),
    body TEXT NOT NULL CHECK (length(body) > 0),
    body_norm TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('original', 'ai_summary', 'inference')),
    created_at TEXT NOT NULL,
    event_time TEXT,
    event_time_precision TEXT
        CHECK (event_time_precision IN ('year', 'month', 'day', 'hour', 'minute', 'second')),
    source TEXT,
    CHECK ((event_time IS NULL) = (event_time_precision IS NULL)),
    UNIQUE (record_id, version_no)
) STRICT;

CREATE INDEX idx_revisions_event_time ON revisions (event_time);

-- Immutability is enforced in the database. The WHEN clause calls a function that only emlek
-- connections register; any other client fails closed with "no such function".
-- The purge routine (M9) is the only code that switches emlek_purge_mode() on.
CREATE TRIGGER revisions_no_update BEFORE UPDATE ON revisions
WHEN emlek_purge_mode() = 0
BEGIN
    SELECT RAISE(ABORT, 'revisions are immutable');
END;

CREATE TRIGGER revisions_no_delete BEFORE DELETE ON revisions
WHEN emlek_purge_mode() = 0
BEGIN
    SELECT RAISE(ABORT, 'revisions are immutable');
END;

CREATE TRIGGER records_no_delete BEFORE DELETE ON records
WHEN emlek_purge_mode() = 0
BEGIN
    SELECT RAISE(ABORT, 'records can only be removed by purge');
END;

CREATE TRIGGER records_identity_immutable BEFORE UPDATE OF id, created_at ON records
WHEN emlek_purge_mode() = 0
BEGIN
    SELECT RAISE(ABORT, 'record identity is immutable');
END;
