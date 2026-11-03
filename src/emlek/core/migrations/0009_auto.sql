-- Auto-record policy (D85): which kinds of things the AI may save without asking. Everything
-- starts off: the switch is in `meta` (auto_enabled = '0') and every category is 'ask'.
CREATE TABLE auto_categories (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    description TEXT NOT NULL DEFAULT '',
    mode TEXT NOT NULL DEFAULT 'ask' CHECK (mode IN ('auto', 'ask', 'off')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
) STRICT;

INSERT INTO auto_categories (name, description, created_at, updated_at) VALUES
    ('生活點滴', '吃飯、去了哪裡、日常', strftime('%Y-%m-%dT%H:%M:%fZ', 'now'), strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    ('思考', '人生、意義等想法', strftime('%Y-%m-%dT%H:%M:%fZ', 'now'), strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    ('工作', '今天做了什麼（只存摘要，不存貼入的程式碼與文件）', strftime('%Y-%m-%dT%H:%M:%fZ', 'now'), strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    ('研究筆記', '學習與研究的筆記', strftime('%Y-%m-%dT%H:%M:%fZ', 'now'), strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    ('靈感', '突發奇想', strftime('%Y-%m-%dT%H:%M:%fZ', 'now'), strftime('%Y-%m-%dT%H:%M:%fZ', 'now'));

INSERT INTO meta (key, value) VALUES ('auto_enabled', '0'), ('auto_daily_limit', '30'), ('auto_excluded', '[]');
