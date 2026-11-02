-- Import batches and what was imported from which file. The unique key (file, content hash) makes
-- a repeated import a no-op; record_id turns empty if the record is ever purged.
CREATE TABLE import_batches (
    id INTEGER PRIMARY KEY,
    created_at TEXT NOT NULL,
    file_count INTEGER NOT NULL,
    options_json TEXT NOT NULL,
    undone_at TEXT
) STRICT;

CREATE TABLE import_log (
    id INTEGER PRIMARY KEY,
    batch_id INTEGER NOT NULL REFERENCES import_batches (id),
    file_name TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    record_id INTEGER REFERENCES records (id),
    purged INTEGER NOT NULL DEFAULT 0 CHECK (purged IN (0, 1)),
    imported_at TEXT NOT NULL,
    UNIQUE (file_name, content_hash)
) STRICT;

CREATE INDEX idx_import_log_hash ON import_log (content_hash);
CREATE INDEX idx_import_log_batch ON import_log (batch_id);
