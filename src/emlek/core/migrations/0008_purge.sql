-- Audit of permanent purges: ids and counts only, never text or hashes. A row stays 'pending'
-- until the physical scrub (checkpoint, VACUUM, byte scan) has finished; doctor warns about it.
CREATE TABLE purge_log (
    id INTEGER PRIMARY KEY,
    at TEXT NOT NULL,
    record_ids TEXT NOT NULL,
    revision_count INTEGER NOT NULL,
    derived_count INTEGER NOT NULL,
    scrub_status TEXT NOT NULL CHECK (scrub_status IN ('pending', 'done', 'unverified'))
) STRICT;
