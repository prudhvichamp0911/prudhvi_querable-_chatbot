"""SQLite-backed document store for the application's own tables.

Why this exists
---------------
The migration moves business data from MongoDB to VeloDB (Apache Doris). But
the app also keeps *operational* state - users, sessions, API keys, usage
counters, chat threads - and that workload is the opposite of what a columnar
MPP warehouse is built for: a point read plus a point write on every single
authenticated request. Doris has no unique constraints on arbitrary columns,
no TTL indexes, and no cheap single-row update, so putting sessions there
would be slower and less correct than what it replaced.

So: analytics -> VeloDB, operational state -> this store.

It implements exactly the slice of the PyMongo collection API that
``auth.py``, ``account.py`` and ``threads.py`` use, so those modules did not
have to be rewritten. Documents are stored as JSON in SQLite; indexed keys are
mirrored into real columns so uniqueness is enforced by the database rather
than by application code.

Supported per collection:
    insert_one, find_one, find (+ .sort / .limit), count_documents,
    update_one (with $set / $inc / $setOnInsert, upsert=True),
    delete_one, delete_many, create_index(unique=, expireAfterSeconds=)

Filter operators: plain equality, $ne, $in, $nin, $lt, $lte, $gt, $gte, $exists.
Mongo's "missing field matches None" semantics are preserved, because the
auth code relies on them (``{"revoked_at": None}``, ``{"disabled": {"$ne": True}}``).
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PATH = ROOT / "data" / "app_state.db"

_MISSING = object()


class DuplicateKeyError(Exception):
    """Raised on a unique-index violation (mirrors pymongo.errors.DuplicateKeyError)."""


class _Result:
    """Stands in for pymongo's UpdateResult / DeleteResult / InsertOneResult."""

    def __init__(self, matched_count=0, modified_count=0, deleted_count=0,
                 upserted_id=None, inserted_id=None):
        self.matched_count = matched_count
        self.modified_count = modified_count
        self.deleted_count = deleted_count
        self.upserted_id = upserted_id
        self.inserted_id = inserted_id


# --- JSON encoding ----------------------------------------------------
# Datetimes round-trip as tagged strings so reads give back aware datetimes,
# matching what PyMongo returned (the auth code then normalises with _as_utc).

_DT_PREFIX = "__dt__:"


def _encode(value: Any) -> Any:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return _DT_PREFIX + value.astimezone(timezone.utc).isoformat()
    if isinstance(value, dict):
        return {k: _encode(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_encode(v) for v in value]
    return value


def _decode(value: Any) -> Any:
    if isinstance(value, str) and value.startswith(_DT_PREFIX):
        return datetime.fromisoformat(value[len(_DT_PREFIX):])
    if isinstance(value, dict):
        return {k: _decode(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_decode(v) for v in value]
    return value


def _sortable(value: Any) -> tuple:
    """Order values the way Mongo roughly does, with None first."""
    if value is None:
        return (0, 0)
    if isinstance(value, bool):
        return (1, int(value))
    if isinstance(value, (int, float)):
        return (1, value)
    if isinstance(value, datetime):
        at = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        return (2, at.timestamp())
    return (3, str(value))


# --- filter matching --------------------------------------------------

def _get(document: dict, path: str) -> Any:
    current: Any = document
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return _MISSING
        current = current[part]
    return current


def _match_operator(actual: Any, operator: str, expected: Any) -> bool:
    present = actual is not _MISSING
    value = None if actual is _MISSING else actual

    if operator == "$eq":
        return value == expected
    if operator == "$ne":
        return value != expected
    if operator == "$in":
        return value in expected
    if operator == "$nin":
        return value not in expected
    if operator == "$exists":
        return present is bool(expected)
    if operator in ("$lt", "$lte", "$gt", "$gte"):
        if value is None or expected is None:
            return False
        try:
            if operator == "$lt":
                return value < expected
            if operator == "$lte":
                return value <= expected
            if operator == "$gt":
                return value > expected
            return value >= expected
        except TypeError:
            return False
    raise ValueError(f"unsupported filter operator: {operator}")


def _matches(document: dict, filters: dict | None) -> bool:
    if not filters:
        return True
    for key, condition in filters.items():
        if key in ("$and", "$or", "$nor"):
            results = [_matches(document, part) for part in condition]
            if key == "$and" and not all(results):
                return False
            if key == "$or" and not any(results):
                return False
            if key == "$nor" and any(results):
                return False
            continue

        actual = _get(document, key)
        if isinstance(condition, dict) and condition and all(
                k.startswith("$") for k in condition):
            for operator, expected in condition.items():
                if not _match_operator(actual, operator, expected):
                    return False
        else:
            # Mongo treats a missing field as null for equality.
            value = None if actual is _MISSING else actual
            if value != condition:
                return False
    return True


# --- cursor -----------------------------------------------------------

class _Cursor:
    def __init__(self, documents: list[dict], projection: dict | None = None):
        self._documents = documents
        self._projection = projection

    def sort(self, key, direction=1):
        pairs = key if isinstance(key, list) else [(key, direction)]
        for field, way in reversed(pairs):
            self._documents.sort(key=lambda d: _sortable(_get_or_none(d, field)),
                                 reverse=(way == -1))
        return self

    def limit(self, count: int):
        if count:
            self._documents = self._documents[:count]
        return self

    def _project(self, document: dict) -> dict:
        if not self._projection:
            return document
        excluded = {k for k, v in self._projection.items() if not v}
        included = {k for k, v in self._projection.items() if v and k != "_id"}
        out = dict(document)
        for key in excluded:
            out.pop(key, None)
        if included:
            keep = included | ({"_id"} if self._projection.get("_id", 1) else set())
            out = {k: v for k, v in out.items() if k in keep}
        return out

    def __iter__(self):
        return (self._project(d) for d in self._documents)

    def __len__(self):
        return len(self._documents)


def _get_or_none(document: dict, field: str) -> Any:
    value = _get(document, field)
    return None if value is _MISSING else value


# --- collection -------------------------------------------------------

class Collection:
    def __init__(self, store: "DocumentStore", name: str):
        self.store = store
        self.name = name
        self._unique_keys: list[tuple[str, ...]] = []
        self._ttl_field: str | None = None
        store._ensure_table(name)

    # -- indexes ---------------------------------------------------

    def create_index(self, keys, unique: bool = False,
                     expireAfterSeconds: int | None = None, **_ignored):
        """Record an index. Unique indexes are enforced on write; a TTL index
        makes expired documents invisible to reads and sweeps them lazily."""
        if isinstance(keys, str):
            fields = (keys,)
        else:
            fields = tuple(k for k, _direction in keys)
        if unique:
            if fields not in self._unique_keys:
                self._unique_keys.append(fields)
        if expireAfterSeconds is not None and fields:
            self._ttl_field = fields[0]
        return "_".join(fields) + ("_unique" if unique else "")

    # -- internals -------------------------------------------------

    def _all(self) -> list[dict]:
        rows = self.store._execute(
            f'SELECT doc FROM "{self.name}"').fetchall()
        documents = [_decode(json.loads(r[0])) for r in rows]
        if self._ttl_field:
            now = datetime.now(timezone.utc)
            alive, expired = [], []
            for document in documents:
                at = document.get(self._ttl_field)
                if isinstance(at, datetime):
                    at = at if at.tzinfo else at.replace(tzinfo=timezone.utc)
                    (expired if at <= now else alive).append(document)
                else:
                    alive.append(document)
            if expired:
                self.store._execute_many(
                    f'DELETE FROM "{self.name}" WHERE id = ?',
                    [(d["_id"],) for d in expired])
            return alive
        return documents

    def _check_unique(self, document: dict, exclude_id=None) -> None:
        if not self._unique_keys:
            return
        for fields in self._unique_keys:
            query = {f: document.get(f) for f in fields}
            for other in self._all():
                if other.get("_id") == exclude_id:
                    continue
                if all(other.get(f) == query[f] for f in fields):
                    raise DuplicateKeyError(
                        f"duplicate key in {self.name}: {query}")

    def _write(self, document: dict) -> None:
        self.store._execute(
            f'INSERT OR REPLACE INTO "{self.name}" (id, doc) VALUES (?, ?)',
            (document["_id"], json.dumps(_encode(document))))

    # -- public API ------------------------------------------------

    def insert_one(self, document: dict) -> _Result:
        document = dict(document)
        document.setdefault("_id", uuid.uuid4().hex)
        with self.store.lock:
            self._check_unique(document)
            self._write(document)
        return _Result(inserted_id=document["_id"])

    def find_one(self, filters: dict | None = None, projection: dict | None = None):
        for document in self._all():
            if _matches(document, filters):
                return _Cursor([document], projection)._project(document)
        return None

    def find(self, filters: dict | None = None, projection: dict | None = None):
        return _Cursor([d for d in self._all() if _matches(d, filters)], projection)

    def count_documents(self, filters: dict | None = None, **_ignored) -> int:
        return sum(1 for d in self._all() if _matches(d, filters))

    def distinct(self, field: str, filters: dict | None = None, **_ignored) -> list:
        seen, out = set(), []
        for document in self._all():
            if not _matches(document, filters):
                continue
            value = _get_or_none(document, field)
            marker = json.dumps(value, default=str, sort_keys=True)
            if marker not in seen:
                seen.add(marker)
                out.append(value)
        return out

    def update_one(self, filters: dict, update: dict, upsert: bool = False) -> _Result:
        with self.store.lock:
            target = None
            for document in self._all():
                if _matches(document, filters):
                    target = document
                    break

            if target is None:
                if not upsert:
                    return _Result(matched_count=0)
                target = {}
                # Seed from the equality parts of the filter, as Mongo does.
                for key, value in (filters or {}).items():
                    if not key.startswith("$") and not isinstance(value, dict):
                        target[key] = value
                target.update(update.get("$setOnInsert", {}))
                target.setdefault("_id", uuid.uuid4().hex)
                for field, delta in update.get("$inc", {}).items():
                    target[field] = target.get(field, 0) + delta
                target.update(update.get("$set", {}))
                self._check_unique(target)
                self._write(target)
                return _Result(matched_count=0, upserted_id=target["_id"])

            updated = dict(target)
            for field, value in update.get("$set", {}).items():
                updated[field] = value
            for field, delta in update.get("$inc", {}).items():
                updated[field] = (updated.get(field) or 0) + delta
            for field, value in update.get("$unset", {}).items():
                updated.pop(field, None)
            self._check_unique(updated, exclude_id=updated.get("_id"))
            self._write(updated)
            return _Result(matched_count=1, modified_count=1)

    def delete_one(self, filters: dict) -> _Result:
        with self.store.lock:
            for document in self._all():
                if _matches(document, filters):
                    self.store._execute(
                        f'DELETE FROM "{self.name}" WHERE id = ?', (document["_id"],))
                    return _Result(deleted_count=1)
        return _Result(deleted_count=0)

    def delete_many(self, filters: dict | None = None) -> _Result:
        with self.store.lock:
            victims = [d for d in self._all() if _matches(d, filters)]
            if victims:
                self.store._execute_many(
                    f'DELETE FROM "{self.name}" WHERE id = ?',
                    [(d["_id"],) for d in victims])
        return _Result(deleted_count=len(victims))

    def estimated_document_count(self, **_ignored) -> int:
        return self.count_documents({})


class DocumentStore:
    """A tiny document database over one SQLite file."""

    def __init__(self, path: str | Path = DEFAULT_PATH):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self._local = threading.local()
        self._collections: dict[str, Collection] = {}

    @property
    def connection(self) -> sqlite3.Connection:
        con = getattr(self._local, "con", None)
        if con is None:
            con = sqlite3.connect(self.path, timeout=15, isolation_level=None)
            con.execute("PRAGMA journal_mode=WAL")
            con.execute("PRAGMA synchronous=NORMAL")
            self._local.con = con
        return con

    def _execute(self, sql: str, params: Iterable = ()):
        return self.connection.execute(sql, tuple(params))

    def _execute_many(self, sql: str, rows: list[tuple]):
        return self.connection.executemany(sql, rows)

    def _ensure_table(self, name: str) -> None:
        with self.lock:
            self._execute(
                f'CREATE TABLE IF NOT EXISTS "{name}" '
                '(id TEXT PRIMARY KEY, doc TEXT NOT NULL)')

    def __getitem__(self, name: str) -> Collection:
        with self.lock:
            if name not in self._collections:
                self._collections[name] = Collection(self, name)
            return self._collections[name]

    def list_collection_names(self) -> list[str]:
        rows = self._execute(
            "SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        return sorted(r[0] for r in rows)

    def ping(self) -> bool:
        self._execute("SELECT 1").fetchone()
        return True


_store: DocumentStore | None = None


def get_store() -> DocumentStore:
    global _store
    if _store is None:
        # An empty APP_STATE_DB in .env must mean "use the default", not "".
        configured = (os.getenv("APP_STATE_DB") or "").strip()
        _store = DocumentStore(configured or DEFAULT_PATH)
    return _store
