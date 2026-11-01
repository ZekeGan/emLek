-- Calendar-date interval of the event, taken from the text as written (no time-zone shift):
-- year/month/day use the date itself; hour/minute/second use the date part in their own offset.
ALTER TABLE revisions ADD COLUMN event_date_start TEXT GENERATED ALWAYS AS (
    CASE event_time_precision
        WHEN 'year' THEN event_time || '-01-01'
        WHEN 'month' THEN event_time || '-01'
        WHEN 'day' THEN event_time
        WHEN 'hour' THEN substr(event_time, 1, 10)
        WHEN 'minute' THEN substr(event_time, 1, 10)
        WHEN 'second' THEN substr(event_time, 1, 10)
    END
) VIRTUAL;

ALTER TABLE revisions ADD COLUMN event_date_end TEXT GENERATED ALWAYS AS (
    CASE event_time_precision
        WHEN 'year' THEN event_time || '-12-31'
        WHEN 'month' THEN date(event_time || '-01', '+1 month', '-1 day')
        WHEN 'day' THEN event_time
        WHEN 'hour' THEN substr(event_time, 1, 10)
        WHEN 'minute' THEN substr(event_time, 1, 10)
        WHEN 'second' THEN substr(event_time, 1, 10)
    END
) VIRTUAL;

CREATE INDEX idx_revisions_event_dates ON revisions (event_date_start, event_date_end);

-- Full-text index over the normalized copy. External content: the text is stored once.
CREATE VIRTUAL TABLE revisions_fts USING fts5 (
    body_norm,
    content = 'revisions',
    content_rowid = 'id',
    tokenize = 'trigram'
);

CREATE TRIGGER revisions_fts_insert AFTER INSERT ON revisions
BEGIN
    INSERT INTO revisions_fts (rowid, body_norm) VALUES (new.id, new.body_norm);
END;

CREATE TRIGGER revisions_fts_delete AFTER DELETE ON revisions
BEGIN
    INSERT INTO revisions_fts (revisions_fts, rowid, body_norm)
    VALUES ('delete', old.id, old.body_norm);
END;

INSERT INTO revisions_fts (revisions_fts) VALUES ('rebuild');
