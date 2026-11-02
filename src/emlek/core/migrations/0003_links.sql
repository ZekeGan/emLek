-- Links say how a newer revision relates to an older one (supersedes, supports, ...). Direction is
-- always new -> old, so the graph cannot contain a cycle. Like revisions, links are write-once;
-- only the purge routine (M9) may remove them.
CREATE TABLE links (
    id INTEGER PRIMARY KEY,
    revision_id INTEGER NOT NULL REFERENCES revisions (id),
    derived_from_revision_id INTEGER NOT NULL REFERENCES revisions (id),
    relation TEXT
        CHECK (relation IN ('supersedes', 'supports', 'supplements', 'derived', 'summarizes')),
    created_at TEXT NOT NULL,
    CHECK (revision_id <> derived_from_revision_id)
) STRICT;

CREATE UNIQUE INDEX idx_links_unique
    ON links (revision_id, derived_from_revision_id, ifnull(relation, ''));
CREATE INDEX idx_links_target ON links (derived_from_revision_id);

CREATE TRIGGER links_no_update BEFORE UPDATE ON links
WHEN emlek_purge_mode() = 0
BEGIN
    SELECT RAISE(ABORT, 'links are immutable');
END;

CREATE TRIGGER links_no_delete BEFORE DELETE ON links
WHEN emlek_purge_mode() = 0
BEGIN
    SELECT RAISE(ABORT, 'links can only be removed by purge');
END;
