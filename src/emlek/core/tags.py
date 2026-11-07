"""Tags: a hand-made index on top of the records (DESIGN_TAGS, "M7 規格").

Tags never touch the text. They live on the record, carry who added them (user or ai), form a
small hierarchy (parent contains child, no cycles) and can have aliases. Everything here that
changes tags is also written to `tag_events` (names and ids only, never record text).
"""

from __future__ import annotations

import logging
import re
import sqlite3
import unicodedata
from collections import Counter
from collections.abc import Iterable, Sequence
from typing import Any

from emlek.core import sensitivity as scanner
from emlek.core import versions
from emlek.core.db import Database
from emlek.core.errors import EmlekError, ErrorCode
from emlek.core.permissions import Caller, Channel, require
from emlek.core.refs import parse_ref
from emlek.core.timeutil import utc_now_iso

TYPES = ("place", "person", "topic", "activity", "emotion", "status")
STATUS_TAGS = ("待辦", "截止", "約定", "已完成")
MAX_NAME_CHARS = 64
MAX_DESCRIPTION_CHARS = 200
MAX_TAGS_PER_RECORD = 20
MAX_NEW_PER_CALL = 10
MAX_ALIASES_PER_TAG = 50
MAX_TAGS_TOTAL = 5000
MAX_EXPANSION = 200
MAX_DEPTH = 3
LIST_LIMIT = 200
INSTRUCTION_LIMIT = 50  # how many names the opening instructions carry
INSTRUCTION_NAME = re.compile(r"^[\w-]{1,24}$")
_HASHTAG = re.compile(
    r"(?:(?<=^)|(?<=[\s　，。、；：！？（）()\[\]「」『』【】,.;:!?]))#([\w-]{1,64})"
)

_log = logging.getLogger("emlek")


def normalize(text: str) -> str:
    return unicodedata.normalize("NFKC", text).casefold().strip()


def _check_text(value: object, label: str, *, limit: int) -> str:
    cleaned = value.strip() if isinstance(value, str) else ""
    if not cleaned or len(cleaned) > limit:
        raise EmlekError(ErrorCode.INVALID_INPUT, f"{label}長度須為 1–{limit} 字元")
    if any(ord(c) < 32 or ord(c) == 127 for c in cleaned):
        raise EmlekError(ErrorCode.INVALID_INPUT, f"{label}不可含控制字元或換行")
    if scanner.scan(cleaned):
        # These strings show up in lists and in the AI's opening instructions: no secrets in them.
        raise EmlekError(ErrorCode.INVALID_INPUT, f"{label}含敏感資訊，不能當作標籤文字")
    return cleaned


def check_name(value: object, label: str = "標籤名稱") -> str:
    name = _check_text(value, label, limit=MAX_NAME_CHARS)
    if name.startswith("#"):
        raise EmlekError(ErrorCode.INVALID_INPUT, f"{label}不要以 # 開頭")
    return name


def parse_hashtags(body: str) -> list[str]:
    """Hashtags the user typed. `C#`, URL fragments, `#1` and `# title` do not count."""
    seen: dict[str, str] = {}
    for match in _HASHTAG.finditer(body):
        name = match.group(1)
        if name.isdigit():
            continue
        seen.setdefault(normalize(name), name)
    return list(seen.values())


def actor_for(caller: Caller) -> str:
    """A person at a real terminal is the user; anything arriving over MCP (or a script) is ai."""
    return "user" if caller.channel is Channel.CLI and caller.interactive else "ai"


# --- storage helpers -------------------------------------------------------------------------


def event(
    conn: sqlite3.Connection, actor: str, action: str, detail: str, record_id: int | None = None
) -> None:
    conn.execute(
        "INSERT INTO tag_events (at, actor, action, record_id, detail) VALUES (?, ?, ?, ?, ?)",
        (utc_now_iso(), actor, action, record_id, detail),
    )


def refresh_search(conn: sqlite3.Connection, tag_id: int) -> None:
    row = conn.execute("SELECT name_key, description FROM tags WHERE id = ?", (tag_id,)).fetchone()
    conn.execute("DELETE FROM tags_fts WHERE rowid = ?", (tag_id,))
    if row is None:
        return
    aliases = [
        r[0] for r in conn.execute("SELECT alias_key FROM tag_aliases WHERE tag_id = ?", (tag_id,))
    ]
    text = " ".join([row[0], *aliases, normalize(row[1])])
    conn.execute("INSERT INTO tags_fts (rowid, text) VALUES (?, ?)", (tag_id, text))


def resolve_id(conn: sqlite3.Connection, name: str) -> int | None:
    key = normalize(name)
    row = conn.execute("SELECT id FROM tags WHERE name_key = ?", (key,)).fetchone()
    if row is None:
        row = conn.execute("SELECT tag_id FROM tag_aliases WHERE alias_key = ?", (key,)).fetchone()
    return None if row is None else int(row[0])


def tag_name(conn: sqlite3.Connection, tag_id: int) -> str:
    return str(conn.execute("SELECT name FROM tags WHERE id = ?", (tag_id,)).fetchone()[0])


def edit_distance(a: str, b: str) -> int:
    if abs(len(a) - len(b)) > 2:
        return 3
    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        current = [i]
        for j, cb in enumerate(b, 1):
            current.append(min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (ca != cb)))
        previous = current
    return previous[-1]


def _is_near(key: str, other: str) -> bool:
    if key == other:
        return False
    if len(key) >= 4 and len(other) >= 4 and edit_distance(key, other) <= 1:
        return True
    shorter, longer = sorted((key, other), key=len)
    return len(shorter) >= 2 and shorter in longer and len(shorter) / len(longer) >= 0.6


def similar_names(
    conn: sqlite3.Connection, key: str, limit: int = 5, cap: str | None = None
) -> list[str]:
    """Near-duplicate names. With a cap, only tags a reader at that cap could already see."""
    found: dict[int, str] = {}
    for tag_id, name, name_key in conn.execute("SELECT id, name, name_key FROM tags"):
        if _is_near(key, name_key):
            found[tag_id] = name
    for tag_id, alias_key in conn.execute("SELECT tag_id, alias_key FROM tag_aliases"):
        if tag_id not in found and _is_near(key, alias_key):
            found[tag_id] = tag_name(conn, tag_id)
    if cap is not None:
        counts = _visible_counts(conn, cap)
        found = {i: n for i, n in found.items() if _listable(counts, i)}
    return list(found.values())[:limit]


def _count_tags(conn: sqlite3.Connection) -> int:
    return int(conn.execute("SELECT count(*) FROM tags").fetchone()[0])


def _normalize_specs(items: Iterable[object]) -> list[dict[str, str]]:
    specs: list[dict[str, str]] = []
    for item in items:
        if isinstance(item, str):
            specs.append({"name": item})
        elif (
            isinstance(item, dict)
            and "name" in item
            and set(item) <= {"name", "type", "description"}
        ):
            specs.append({k: str(v) for k, v in item.items()})
        else:
            raise EmlekError(
                ErrorCode.INVALID_INPUT, "標籤格式應為名稱字串，或 {name, type?, description?}"
            )
    return specs


def attach(
    conn: sqlite3.Connection,
    record_id: int,
    items: Iterable[object],
    *,
    actor: str,
    allow_new: Iterable[str] = (),
    created_by: str | None = None,
) -> tuple[list[str], list[dict[str, Any]]]:
    """Put tags on a record. Returns (names now on the record from this call, pending names).

    A name that equals an existing tag or alias reuses it. A name that is merely *close* to an
    existing one is not created unless the caller lists it in `allow_new`."""
    allowed = {normalize(n) for n in allow_new}
    applied: list[str] = []
    pending: list[dict[str, Any]] = []
    created = 0
    now = utc_now_iso()
    for spec in _normalize_specs(items):
        name = check_name(spec["name"])
        key = normalize(name)
        tag_id = resolve_id(conn, name)
        if tag_id is None:
            near = similar_names(conn, key)
            if near and key not in allowed:
                pending.append({"name": name, "similar": near})
                continue
            kind = spec.get("type", "topic")
            if kind not in TYPES:
                raise EmlekError(
                    ErrorCode.INVALID_INPUT, f"type 必須是 {', '.join(TYPES)} 其中之一"
                )
            if kind == "status" and actor == "ai":
                raise EmlekError(ErrorCode.INVALID_INPUT, "status 標籤是固定的，不能新增")
            description = spec.get("description", "")
            if description:
                description = _check_text(description, "標籤說明", limit=MAX_DESCRIPTION_CHARS)
            created += 1
            if created > MAX_NEW_PER_CALL:
                raise EmlekError(ErrorCode.INVALID_INPUT, f"一次最多新建 {MAX_NEW_PER_CALL} 個標籤")
            if _count_tags(conn) >= MAX_TAGS_TOTAL:
                raise EmlekError(ErrorCode.INVALID_INPUT, f"標籤總數已達上限 {MAX_TAGS_TOTAL}")
            cursor = conn.execute(
                "INSERT INTO tags (name, name_key, type, description, created_by, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (name, key, kind, description, actor, now),
            )
            assert cursor.lastrowid is not None
            tag_id = cursor.lastrowid
            refresh_search(conn, tag_id)
            event(conn, actor, "tag_create", name, record_id)
        has = conn.execute(
            "SELECT 1 FROM record_tags WHERE record_id = ? AND tag_id = ?", (record_id, tag_id)
        ).fetchone()
        if has is None:
            count = conn.execute(
                "SELECT count(*) FROM record_tags WHERE record_id = ?", (record_id,)
            ).fetchone()[0]
            if count >= MAX_TAGS_PER_RECORD:
                raise EmlekError(
                    ErrorCode.INVALID_INPUT, f"每筆記錄最多 {MAX_TAGS_PER_RECORD} 個標籤"
                )
            conn.execute(
                "INSERT INTO record_tags (record_id, tag_id, added_by, added_at)"
                " VALUES (?, ?, ?, ?)",
                (record_id, tag_id, created_by or actor, now),
            )
            event(conn, actor, "tag_add", tag_name(conn, tag_id), record_id)
        applied.append(tag_name(conn, tag_id))
    return applied, pending


def detach(conn: sqlite3.Connection, record_id: int, names: Iterable[str], actor: str) -> list[str]:
    removed: list[str] = []
    for name in names:
        tag_id = resolve_id(conn, name)
        if tag_id is None:
            continue
        cursor = conn.execute(
            "DELETE FROM record_tags WHERE record_id = ? AND tag_id = ?", (record_id, tag_id)
        )
        if cursor.rowcount:
            removed.append(tag_name(conn, tag_id))
            event(conn, actor, "tag_remove_from_record", tag_name(conn, tag_id), record_id)
    return removed


def tags_of(conn: sqlite3.Connection, record_id: int) -> list[dict[str, str]]:
    return [
        {"name": name, "type": kind, "added_by": added_by}
        for name, kind, added_by in conn.execute(
            "SELECT t.name, t.type, rt.added_by FROM record_tags rt JOIN tags t ON t.id = rt.tag_id"
            " WHERE rt.record_id = ? ORDER BY t.name_key",
            (record_id,),
        )
    ]


# --- hierarchy and expansion -----------------------------------------------------------------


def descendants(
    conn: sqlite3.Connection, tag_id: int, depth: int = MAX_DEPTH
) -> tuple[list[int], bool]:
    """The tag itself plus everything below it (at most `depth` levels, `MAX_EXPANSION` tags)."""
    order = [tag_id]
    seen = {tag_id}
    frontier = [tag_id]
    truncated = False
    for _ in range(depth):
        nxt: list[int] = []
        for parent in frontier:
            for (child,) in conn.execute(
                "SELECT child_tag_id FROM tag_links WHERE parent_tag_id = ? ORDER BY child_tag_id",
                (parent,),
            ):
                if child in seen:
                    continue
                if len(order) >= MAX_EXPANSION:
                    truncated = True
                    continue
                seen.add(child)
                order.append(child)
                nxt.append(child)
        frontier = nxt
    return order, truncated


def resolve_filter(
    conn: sqlite3.Connection, names: Sequence[str], *, expand: bool
) -> tuple[list[list[int]], list[str], list[str], bool]:
    """For a search: one id list per known tag, unknown names, expanded names, truncated."""
    groups: list[list[int]] = []
    unknown: list[str] = []
    shown: list[str] = []
    truncated = False
    for name in names:
        tag_id = resolve_id(conn, name)
        if tag_id is None:
            unknown.append(name)
            continue
        if expand:
            ids, cut = descendants(conn, tag_id)
            truncated = truncated or cut
        else:
            ids = [tag_id]
        groups.append(ids)
        shown.extend(tag_name(conn, i) for i in ids if tag_name(conn, i) not in shown)
    return groups, unknown, shown, truncated


# --- visibility (hidden records and the sensitivity cap never count) ------------------------


def _allowed(cap: str) -> str:
    order = scanner.LEVELS
    return ", ".join(f"'{level}'" for level in order[: order.index(cap) + 1])


def _visible_counts(
    conn: sqlite3.Connection, cap: str, *, withhold_invalidated: bool = True
) -> dict[int, tuple[int, int]]:
    """tag id -> (visible uses, all uses)."""
    rows = conn.execute(
        "SELECT rt.tag_id, SUM(CASE WHEN rec.hidden = 0 AND rec.sensitivity IN ("
        + _allowed(cap)
        + ") THEN 1 ELSE 0 END), count(*) FROM record_tags rt JOIN records rec"
        " ON rec.id = rt.record_id GROUP BY rt.tag_id"
    ).fetchall()
    counts = {int(t): (int(v or 0), int(a)) for t, v, a in rows}
    if withhold_invalidated and versions.has_links(conn):
        for record_id, tag_id in conn.execute(
            "SELECT rt.record_id, rt.tag_id FROM record_tags rt JOIN records rec"
            " ON rec.id = rt.record_id WHERE rec.hidden = 0 AND rec.sensitivity IN ("
            + _allowed(cap)
            + ")"
        ).fetchall():
            if versions.hidden_sources(conn, record_id):
                visible, total = counts[tag_id]
                counts[tag_id] = (visible - 1, total)
    return counts


def matching(
    conn: sqlite3.Connection, terms: list[str], cap: str, limit: int = 5
) -> list[dict[str, Any]]:
    """Tags whose name or alias is exactly one of the query words (visible records only), so a
    search answer can say "there is a tag for this" without a second call."""
    keys = {normalize(t) for t in terms} - {""}
    if not keys:
        return []
    counts = _visible_counts(conn, cap)
    found: dict[int, str] = {}
    for tag_id, name, name_key in conn.execute("SELECT id, name, name_key FROM tags"):
        if name_key in keys:
            found.setdefault(int(tag_id), name)
    for tag_id, alias_key in conn.execute("SELECT tag_id, alias_key FROM tag_aliases"):
        if alias_key in keys and int(tag_id) not in found:
            row = conn.execute("SELECT name FROM tags WHERE id = ?", (tag_id,)).fetchone()
            if row:
                found[int(tag_id)] = row[0]
    return [
        {"name": name, "records": counts.get(i, (0, 0))[0]}
        for i, name in found.items()
        if _listable(counts, i) and counts.get(i, (0, 0))[0] > 0
    ][:limit]


def _listable(counts: dict[int, tuple[int, int]], tag_id: int) -> bool:
    visible, total = counts.get(tag_id, (0, 0))
    return total == 0 or visible > 0  # a tag known only from hidden or capped records stays hidden


def visible_names(conn: sqlite3.Connection, names: list[str], cap: str) -> list[str]:
    """Filter expanded tag names before returning them to an AI reader."""
    counts = _visible_counts(conn, cap)
    return [name for name in names if _listable(counts, resolve_id(conn, name) or -1)]


def popular_names(conn: sqlite3.Connection, cap: str, limit: int = INSTRUCTION_LIMIT) -> list[str]:
    """Names for the AI's opening instructions: safe characters only, most used first.

    Only tags a person made or has used count (created by the user, or put on a record by the
    user): a tag an AI invented could carry a sentence of instructions into the prompt, so those
    stay reachable through `tags_list` but never in the opening text."""
    counts = _visible_counts(conn, cap)
    trusted = {
        int(r[0])
        for r in conn.execute(
            "SELECT id FROM tags WHERE created_by IN ('user', 'system')"
            " UNION SELECT tag_id FROM record_tags WHERE added_by = 'user'"
        )
    }
    ranked = sorted(
        (
            (counts.get(i, (0, 0))[0], name)
            for i, name in conn.execute("SELECT id, name FROM tags")
            if i in trusted and counts.get(i, (0, 0))[0] > 0 and INSTRUCTION_NAME.match(name)
        ),
        key=lambda pair: (-pair[0], pair[1]),
    )
    return [name for _, name in ranked[:limit]]


# --- tools -----------------------------------------------------------------------------------


def set_tags(
    db: Database,
    caller: Caller,
    *,
    ref: str,
    add: Sequence[object] | None = None,
    remove: Sequence[str] | None = None,
    allow_new: Sequence[str] = (),
) -> dict[str, Any]:
    require(caller, "set_tags")
    record_id, _ = parse_ref(ref)
    actor = actor_for(caller)
    with db.transaction() as conn:
        if conn.execute("SELECT 1 FROM records WHERE id = ?", (record_id,)).fetchone() is None:
            raise EmlekError(ErrorCode.NOT_FOUND, "找不到這筆記錄")
        applied, pending = attach(conn, record_id, add or [], actor=actor, allow_new=allow_new)
        removed = detach(conn, record_id, remove or [], actor)
        now_on = tags_of(conn, record_id)
    return {
        "ref": f"r{record_id}",
        "added": applied,
        "removed": removed,
        "tags_pending": pending,
        "tags": now_on,
    }


def link(db: Database, caller: Caller, *, parent: str, child: str) -> dict[str, Any]:
    require(caller, "tag_link")
    actor = actor_for(caller)
    with db.transaction() as conn:
        parent_id, child_id = resolve_id(conn, parent), resolve_id(conn, child)
        if parent_id is None or child_id is None:
            raise EmlekError(ErrorCode.NOT_FOUND, "找不到指定的標籤（先建立它們）")
        if parent_id == child_id:
            raise EmlekError(ErrorCode.INVALID_INPUT, "標籤不能包含自己")
        below, _ = descendants(conn, child_id, depth=1000)
        if parent_id in below:
            raise EmlekError(ErrorCode.INVALID_INPUT, "這個關係會形成循環，已拒絕")
        cursor = conn.execute(
            "INSERT OR IGNORE INTO tag_links (parent_tag_id, child_tag_id, created_by, created_at)"
            " VALUES (?, ?, ?, ?)",
            (parent_id, child_id, actor, utc_now_iso()),
        )
        if cursor.rowcount:
            event(
                conn, actor, "tag_link", f"{tag_name(conn, parent_id)} > {tag_name(conn, child_id)}"
            )
        return {
            "parent": tag_name(conn, parent_id),
            "child": tag_name(conn, child_id),
            "created": bool(cursor.rowcount),
        }


def alias(db: Database, caller: Caller, *, alias_text: str, tag: str) -> dict[str, Any]:
    require(caller, "tag_alias")
    actor = actor_for(caller)
    text = check_name(alias_text, "別名")
    key = normalize(text)
    with db.transaction() as conn:
        tag_id = resolve_id(conn, tag)
        if tag_id is None:
            raise EmlekError(ErrorCode.NOT_FOUND, "找不到指定的標籤")
        owner = resolve_id(conn, text)
        if owner == tag_id:
            return {"alias": text, "tag": tag_name(conn, tag_id), "created": False}
        if owner is not None:
            raise EmlekError(ErrorCode.CONFLICT, "這個別名已被其他標籤或別名使用")
        total = conn.execute(
            "SELECT count(*) FROM tag_aliases WHERE tag_id = ?", (tag_id,)
        ).fetchone()[0]
        if total >= MAX_ALIASES_PER_TAG:
            raise EmlekError(ErrorCode.INVALID_INPUT, f"每個標籤最多 {MAX_ALIASES_PER_TAG} 個別名")
        conn.execute(
            "INSERT INTO tag_aliases (alias, alias_key, tag_id, created_by, created_at)"
            " VALUES (?, ?, ?, ?, ?)",
            (text, key, tag_id, actor, utc_now_iso()),
        )
        refresh_search(conn, tag_id)
        event(conn, actor, "tag_alias", f"{text} = {tag_name(conn, tag_id)}")
        return {"alias": text, "tag": tag_name(conn, tag_id), "created": True}


def _describe_tag(
    conn: sqlite3.Connection, tag_id: int, counts: dict[int, tuple[int, int]]
) -> dict[str, Any]:
    name, kind, description = conn.execute(
        "SELECT name, type, description FROM tags WHERE id = ?", (tag_id,)
    ).fetchone()
    aliases = [
        r[0] for r in conn.execute("SELECT alias FROM tag_aliases WHERE tag_id = ?", (tag_id,))
    ]
    return {
        "name": name,
        "type": kind,
        "uses": counts.get(tag_id, (0, 0))[0],
        "aliases": aliases,
        "description": description,
    }


def find(
    db: Database,
    caller: Caller,
    *,
    text: str,
    limit: int = 10,
    max_sensitivity: str = "high",
) -> dict[str, Any]:
    require(caller, "tags_find")
    key = normalize(text)
    if not key:
        raise EmlekError(ErrorCode.INVALID_INPUT, "請給要找的字")
    conn = db.conn
    counts = _visible_counts(
        conn, max_sensitivity, withhold_invalidated=caller.channel != Channel.CLI
    )
    scored: dict[int, tuple[int, str]] = {}

    def offer(tag_id: int, rank: int, via: str) -> None:
        if tag_id not in scored or rank < scored[tag_id][0]:
            scored[tag_id] = (rank, via)

    for tag_id, name_key in conn.execute("SELECT id, name_key FROM tags"):
        if name_key == key:
            offer(tag_id, 0, "name")
        elif name_key.startswith(key):
            offer(tag_id, 2, "prefix")
        elif len(key) >= 3 and edit_distance(key, name_key) <= 1:
            offer(tag_id, 4, "fuzzy")
    for tag_id, alias_key in conn.execute("SELECT tag_id, alias_key FROM tag_aliases"):
        if alias_key == key:
            offer(tag_id, 1, "alias")
        elif alias_key.startswith(key):
            offer(tag_id, 2, "prefix")
        elif len(key) >= 3 and edit_distance(key, alias_key) <= 1:
            offer(tag_id, 4, "fuzzy")
    if len(key) >= 3:
        quoted = '"' + key.replace('"', '""') + '"'
        for (tag_id,) in conn.execute(
            "SELECT rowid FROM tags_fts WHERE tags_fts MATCH ?", (quoted,)
        ):
            offer(int(tag_id), 3, "text")
    else:
        for (tag_id,) in conn.execute(
            "SELECT rowid FROM tags_fts WHERE text LIKE ? ESCAPE '\\'",
            ("%" + key.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%",),
        ):
            offer(int(tag_id), 3, "text")
    ranked = sorted(
        (i for i in scored if _listable(counts, i)),
        key=lambda i: (scored[i][0], -counts.get(i, (0, 0))[0], i),
    )
    results = []
    for tag_id in ranked[:limit]:
        item = _describe_tag(conn, tag_id, counts)
        item["matched_via"] = scored[tag_id][1]
        results.append(item)
    return {"query": text, "results": results, "total": len(ranked)}


def listing(
    db: Database,
    caller: Caller,
    *,
    tree: str | None = None,
    related_to: str | None = None,
    type_: str | None = None,
    limit: int = 50,
    max_sensitivity: str = "high",
) -> dict[str, Any]:
    require(caller, "tags_list")
    if not 1 <= limit <= LIST_LIMIT:
        raise EmlekError(ErrorCode.INVALID_INPUT, f"limit 必須介於 1 與 {LIST_LIMIT}")
    if type_ is not None and type_ not in TYPES:
        raise EmlekError(ErrorCode.INVALID_INPUT, f"type 必須是 {', '.join(TYPES)} 其中之一")
    if tree and related_to:
        raise EmlekError(ErrorCode.INVALID_INPUT, "tree 與 related_to 只能擇一")
    conn = db.conn
    counts = _visible_counts(
        conn, max_sensitivity, withhold_invalidated=caller.channel != Channel.CLI
    )
    if tree:
        root = resolve_id(conn, tree)
        if root is None or not _listable(counts, root):
            raise EmlekError(ErrorCode.NOT_FOUND, "找不到指定的標籤")
        return {"tree": _tree(conn, root, counts, MAX_DEPTH)}
    if related_to:
        base = resolve_id(conn, related_to)
        if base is None or not _listable(counts, base):
            raise EmlekError(ErrorCode.NOT_FOUND, "找不到指定的標籤")
        rows = conn.execute(
            "SELECT other.tag_id, own.record_id FROM record_tags own JOIN record_tags other"
            " ON other.record_id = own.record_id AND other.tag_id <> own.tag_id"
            " JOIN records rec ON rec.id = own.record_id"
            " WHERE own.tag_id = ? AND rec.hidden = 0 AND rec.sensitivity IN ("
            + _allowed(max_sensitivity)
            + ")",
            (base,),
        ).fetchall()
        together = Counter(
            tag_id
            for tag_id, record_id in rows
            if caller.channel == Channel.CLI or not versions.hidden_sources(conn, record_id)
        )
        return {
            "related": [
                {"name": tag_name(conn, int(i)), "together": int(n)}
                for i, n in together.most_common(20)
                if _listable(counts, int(i))
            ]
        }
    rows = [
        (i, name, kind)
        for i, name, kind in conn.execute("SELECT id, name, type FROM tags")
        if (type_ is None or kind == type_) and _listable(counts, i)
    ]
    rows.sort(key=lambda r: (-counts.get(r[0], (0, 0))[0], r[1]))
    return {
        "tags": [
            {"name": name, "type": kind, "uses": counts.get(i, (0, 0))[0]}
            for i, name, kind in rows[:limit]
        ],
        "total": len(rows),
    }


def _tree(
    conn: sqlite3.Connection, tag_id: int, counts: dict[int, tuple[int, int]], depth: int
) -> dict[str, Any]:
    node: dict[str, Any] = {"name": tag_name(conn, tag_id), "uses": counts.get(tag_id, (0, 0))[0]}
    if depth > 0:
        kids = [
            _tree(conn, int(child), counts, depth - 1)
            for (child,) in conn.execute(
                "SELECT child_tag_id FROM tag_links WHERE parent_tag_id = ? ORDER BY child_tag_id",
                (tag_id,),
            )
            if _listable(counts, int(child))
        ]
        if kids:
            node["children"] = kids
    return node


# --- command-line only: merge, remove, audit -------------------------------------------------


def merge(db: Database, caller: Caller, *, old: str, new: str) -> dict[str, Any]:
    require(caller, "tag_merge")
    with db.transaction() as conn:
        old_id, new_id = resolve_id(conn, old), resolve_id(conn, new)
        if old_id is None or new_id is None:
            raise EmlekError(ErrorCode.NOT_FOUND, "找不到指定的標籤")
        if old_id == new_id:
            raise EmlekError(ErrorCode.INVALID_INPUT, "兩個名稱指向同一個標籤")
        old_name, new_name = tag_name(conn, old_id), tag_name(conn, new_id)
        moved = conn.execute(
            "INSERT OR IGNORE INTO record_tags (record_id, tag_id, added_by, added_at)"
            " SELECT record_id, ?, added_by, added_at FROM record_tags WHERE tag_id = ?",
            (new_id, old_id),
        ).rowcount
        conn.execute("DELETE FROM record_tags WHERE tag_id = ?", (old_id,))
        skipped: list[str] = []
        for parent, child in conn.execute(
            "SELECT parent_tag_id, child_tag_id FROM tag_links WHERE parent_tag_id = ?"
            " OR child_tag_id = ?",
            (old_id, old_id),
        ).fetchall():
            new_parent = new_id if parent == old_id else parent
            new_child = new_id if child == old_id else child
            conn.execute(
                "DELETE FROM tag_links WHERE parent_tag_id = ? AND child_tag_id = ?",
                (parent, child),
            )
            below, _ = descendants(conn, new_child, depth=1000)
            if new_parent == new_child or new_parent in below:
                skipped.append(f"{tag_name(conn, new_parent)} > {tag_name(conn, new_child)}")
                continue
            conn.execute(
                "INSERT OR IGNORE INTO tag_links"
                " (parent_tag_id, child_tag_id, created_by, created_at)"
                " VALUES (?, ?, 'system', ?)",
                (new_parent, new_child, utc_now_iso()),
            )
        conn.execute("UPDATE tag_aliases SET tag_id = ? WHERE tag_id = ?", (new_id, old_id))
        conn.execute("DELETE FROM tags WHERE id = ?", (old_id,))
        conn.execute("DELETE FROM tags_fts WHERE rowid = ?", (old_id,))
        conn.execute(
            "INSERT OR IGNORE INTO tag_aliases (alias, alias_key, tag_id, created_by, created_at)"
            " VALUES (?, ?, ?, 'system', ?)",
            (old_name, normalize(old_name), new_id, utc_now_iso()),
        )
        refresh_search(conn, new_id)
        event(conn, "user", "tag_merge", f"{old_name} -> {new_name}")
    _log.info("tag merge records_moved=%d", moved)
    return {"merged": old_name, "into": new_name, "records_moved": moved, "links_skipped": skipped}


def usage(db: Database, *, name: str) -> dict[str, Any]:
    tag_id = resolve_id(db.conn, name)
    if tag_id is None:
        raise EmlekError(ErrorCode.NOT_FOUND, "找不到指定的標籤")
    uses = db.conn.execute(
        "SELECT count(*) FROM record_tags WHERE tag_id = ?", (tag_id,)
    ).fetchone()[0]
    return {"name": tag_name(db.conn, tag_id), "uses": int(uses)}


def remove(db: Database, caller: Caller, *, name: str) -> dict[str, Any]:
    require(caller, "tag_remove")
    with db.transaction() as conn:
        tag_id = resolve_id(conn, name)
        if tag_id is None:
            raise EmlekError(ErrorCode.NOT_FOUND, "找不到指定的標籤")
        label = tag_name(conn, tag_id)
        uses = conn.execute(
            "SELECT count(*) FROM record_tags WHERE tag_id = ?", (tag_id,)
        ).fetchone()[0]
        conn.execute("DELETE FROM record_tags WHERE tag_id = ?", (tag_id,))
        conn.execute(
            "DELETE FROM tag_links WHERE parent_tag_id = ? OR child_tag_id = ?", (tag_id, tag_id)
        )
        conn.execute("DELETE FROM tag_aliases WHERE tag_id = ?", (tag_id,))
        conn.execute("DELETE FROM tags WHERE id = ?", (tag_id,))
        conn.execute("DELETE FROM tags_fts WHERE rowid = ?", (tag_id,))
        event(conn, "user", "tag_remove", label)
    return {"removed": label, "records_untagged": int(uses)}


def audit(db: Database, caller: Caller) -> dict[str, Any]:
    require(caller, "tags_audit")
    conn = db.conn
    total = int(conn.execute("SELECT count(*) FROM records").fetchone()[0])
    tagged = int(conn.execute("SELECT count(DISTINCT record_id) FROM record_tags").fetchone()[0])
    uses = {
        int(i): int(n)
        for i, n in conn.execute("SELECT tag_id, count(*) FROM record_tags GROUP BY tag_id")
    }
    names = [(int(i), n, k) for i, n, k in conn.execute("SELECT id, name, name_key FROM tags")]
    duplicates = []
    for index, (_i, name, key) in enumerate(names):
        for _j, other, other_key in names[index + 1 :]:
            if _is_near(key, other_key):
                duplicates.append([name, other])
    return {
        "records": total,
        "records_with_tags": tagged,
        "coverage_percent": round(100 * tagged / total, 1) if total else None,
        "tags": len(names),
        "possible_duplicates": duplicates[:50],
        "used_once": [n for i, n, _ in names if uses.get(i, 0) == 1][:50],
        "too_common": [n for i, n, _ in names if total and uses.get(i, 0) > 0.8 * total][:50],
        "unused": [n for i, n, _ in names if uses.get(i, 0) == 0][:50],
    }


# --- backfill: attach existing tags to older records by their literal name ---------------------

BACKFILL_TYPES = ("place", "person", "topic", "activity")  # not status (intent) or emotion (guess)
BACKFILL_MIN_CHARS = 2
BACKFILL_MAX_SHARE = 0.5  # a tag that would land on more than half the records tells nothing
BACKFILL_SAMPLES = 3


def _keys_of(conn: sqlite3.Connection, tag_id: int, name_key: str) -> list[str]:
    keys = [name_key]
    keys += [
        r[0] for r in conn.execute("SELECT alias_key FROM tag_aliases WHERE tag_id = ?", (tag_id,))
    ]
    return [k for k in dict.fromkeys(keys) if len(k) >= BACKFILL_MIN_CHARS]


def _records_containing(conn: sqlite3.Connection, key: str) -> set[int]:
    """Visible records whose current text contains the key (index for 3+ characters)."""
    latest = (
        "r.version_no = (SELECT MAX(v.version_no) FROM revisions v WHERE v.record_id = r.record_id)"
    )
    if len(key) >= 3:
        quoted = '"' + key.replace('"', '""') + '"'
        rows = conn.execute(
            "SELECT DISTINCT r.record_id FROM revisions_fts f JOIN revisions r ON r.id = f.rowid"
            f" JOIN records rec ON rec.id = r.record_id WHERE revisions_fts MATCH ? AND {latest}"
            " AND rec.hidden = 0",
            (quoted,),
        )
    else:
        pattern = "%" + key.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        rows = conn.execute(
            "SELECT DISTINCT r.record_id FROM revisions r JOIN records rec ON rec.id = r.record_id"
            f" WHERE r.body_norm LIKE ? ESCAPE '\\' AND {latest} AND rec.hidden = 0",
            (pattern,),
        )
    return {int(r[0]) for r in rows}


def _outside_longer_names(
    conn: sqlite3.Connection, key: str, longer: list[str], ids: set[int]
) -> set[int]:
    """Drop records where the key only occurs inside a longer tag name (京都 in 東京都)."""
    kept: set[int] = set()
    for record_id in ids:
        body = conn.execute(
            "SELECT body_norm FROM revisions WHERE record_id = ? ORDER BY version_no DESC LIMIT 1",
            (record_id,),
        ).fetchone()[0]
        covered = [False] * len(body)
        for other in longer:
            start = body.find(other)
            while start != -1:
                for i in range(start, start + len(other)):
                    covered[i] = True
                start = body.find(other, start + 1)
        position = body.find(key)
        while position != -1:
            if not all(covered[position : position + len(key)]):
                kept.add(record_id)
                break
            position = body.find(key, position + 1)
    return kept


def backfill_plan(
    db: Database, caller: Caller, *, only: Sequence[str] | None = None
) -> dict[str, Any]:
    """What `backfill_apply` would add: per tag, how many records and a few examples."""
    require(caller, "tags_backfill_preview")
    conn = db.conn
    wanted = None
    if only:
        wanted = {tid for tid in (resolve_id(conn, n) for n in only) if tid is not None}
    total_records = int(conn.execute("SELECT count(*) FROM records WHERE hidden = 0").fetchone()[0])
    all_keys = [r[0] for r in conn.execute("SELECT name_key FROM tags")]
    all_keys += [r[0] for r in conn.execute("SELECT alias_key FROM tag_aliases")]
    plan: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    for tag_id, name, name_key, kind in conn.execute(
        "SELECT id, name, name_key, type FROM tags ORDER BY name_key"
    ).fetchall():
        if wanted is not None and tag_id not in wanted:
            continue
        if kind not in BACKFILL_TYPES:
            skipped.append({"tag": name, "reason": f"{kind} 標籤不用字面回補"})
            continue
        keys = _keys_of(conn, tag_id, name_key)
        if not keys:
            skipped.append({"tag": name, "reason": "名稱太短"})
            continue
        hit: set[int] = set()
        for key in keys:
            ids = _records_containing(conn, key)
            longer = [k for k in all_keys if k != key and key in k]
            if longer and ids:
                ids = _outside_longer_names(conn, key, longer, ids)
            hit |= ids
        have = {
            int(r[0])
            for r in conn.execute("SELECT record_id FROM record_tags WHERE tag_id = ?", (tag_id,))
        }
        new = sorted(hit - have)
        if not new:
            continue
        if total_records and len(hit) > BACKFILL_MAX_SHARE * total_records:
            skipped.append(
                {
                    "tag": name,
                    "reason": f"會落在超過 {int(BACKFILL_MAX_SHARE * 100)}% 的記錄上，沒有區辨力",
                }
            )
            continue
        samples = []
        for record_id in new[:BACKFILL_SAMPLES]:
            body = conn.execute(
                "SELECT body FROM revisions WHERE record_id = ? ORDER BY version_no DESC LIMIT 1",
                (record_id,),
            ).fetchone()[0]
            samples.append({"ref": f"r{record_id}", "text": " ".join(body.split())[:60]})
        plan.append(
            {
                "tag": name,
                "tag_id": tag_id,
                "records": len(new),
                "record_ids": new,
                "samples": samples,
            }
        )
    return {
        "plan": plan,
        "new_links": sum(item["records"] for item in plan),
        "skipped": skipped,
    }


def backfill_apply(
    db: Database, caller: Caller, *, only: Sequence[str] | None = None
) -> dict[str, Any]:
    """Attach the planned tags with provenance 'rule'. Needs a person at a terminal."""
    require(caller, "tags_backfill_apply")
    plan = backfill_plan(db, Caller(Channel.CLI), only=only)
    now = utc_now_iso()
    with db.transaction() as conn:
        for item in plan["plan"]:
            conn.executemany(
                "INSERT OR IGNORE INTO record_tags (record_id, tag_id, added_by, added_at)"
                " VALUES (?, ?, 'rule', ?)",
                ((rid, item["tag_id"], now) for rid in item["record_ids"]),
            )
            event(conn, "user", "tag_backfill", f"{item['tag']}: {item['records']} records")
    _log.info("tag backfill links=%d", plan["new_links"])
    return {
        "tags": [{"tag": p["tag"], "records": p["records"]} for p in plan["plan"]],
        "new_links": plan["new_links"],
    }


def backfill_undo(db: Database, caller: Caller) -> dict[str, Any]:
    """Remove every tag that a rule attached (people's and AI's choices stay)."""
    require(caller, "tags_backfill_apply")
    with db.transaction() as conn:
        removed = conn.execute("DELETE FROM record_tags WHERE added_by = 'rule'").rowcount
        event(conn, "user", "tag_backfill_undo", f"{removed} links")
    return {"removed": int(removed)}


# --- helpers for search ----------------------------------------------------------------------


def with_temp_ids(conn: sqlite3.Connection, record_ids: Iterable[int]) -> None:
    conn.execute("CREATE TEMP TABLE IF NOT EXISTS _hits (id INTEGER PRIMARY KEY)")
    conn.execute("DELETE FROM _hits")
    conn.executemany("INSERT OR IGNORE INTO _hits (id) VALUES (?)", ((i,) for i in record_ids))


def facets(
    conn: sqlite3.Connection, record_ids: Sequence[int], limit: int = 10
) -> list[dict[str, Any]]:
    if not record_ids:
        return []
    with_temp_ids(conn, record_ids)
    rows = conn.execute(
        "SELECT t.name, t.type, count(*) FROM _hits h JOIN record_tags rt ON rt.record_id = h.id"
        " JOIN tags t ON t.id = rt.tag_id GROUP BY t.id ORDER BY count(*) DESC, t.name LIMIT ?",
        (limit,),
    ).fetchall()
    return [{"name": n, "type": k, "count": int(c)} for n, k, c in rows]


def tagged_share(conn: sqlite3.Connection, record_ids: Sequence[int]) -> dict[str, int]:
    with_temp_ids(conn, record_ids)
    tagged = conn.execute(
        "SELECT count(*) FROM _hits h WHERE EXISTS"
        " (SELECT 1 FROM record_tags rt WHERE rt.record_id = h.id)"
    ).fetchone()[0]
    return {"tagged": int(tagged), "untagged": len(set(record_ids)) - int(tagged)}
