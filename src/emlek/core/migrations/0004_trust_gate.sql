-- M6 trust gate: trigger phrases, the medium-sensitivity notice switch, one-time confirmation
-- tokens. The PIN itself is NOT stored here (see security.json), so backups never carry it.
CREATE TABLE phrases (
    id INTEGER PRIMARY KEY,
    kind TEXT NOT NULL CHECK (kind IN ('save', 'purge', 'exclude')),
    text TEXT NOT NULL CHECK (length(text) BETWEEN 1 AND 100),
    text_key TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0, 1)),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (kind, text_key)
) STRICT;

INSERT INTO phrases (kind, text, text_key, created_at, updated_at)
SELECT kind, text, text, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'),
       strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
FROM (
    SELECT 'save' AS kind, '記住' AS text
    UNION ALL SELECT 'save', '幫我記一下'
    UNION ALL SELECT 'save', '存起來'
    UNION ALL SELECT 'save', '記憶'
    UNION ALL SELECT 'purge', '完全刪除'
    UNION ALL SELECT 'exclude', '上週記住了文法'
);

CREATE TABLE notice_settings (
    level TEXT PRIMARY KEY CHECK (level IN ('medium')),
    enabled INTEGER NOT NULL CHECK (enabled IN (0, 1)),
    acknowledged_at TEXT
) STRICT;

INSERT INTO notice_settings (level, enabled) VALUES ('medium', 1);

CREATE TABLE confirm_tokens (
    token_hash TEXT PRIMARY KEY,
    kind TEXT NOT NULL CHECK (kind IN ('confirm', 'notice')),
    content_hash TEXT NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    used_at TEXT
) STRICT;
