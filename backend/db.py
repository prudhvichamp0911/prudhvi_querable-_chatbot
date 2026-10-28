"""Data access for the two stores this app uses.

    VeloDB (Apache Doris)  - business/analytical data the chatbot queries
    SQLite document store  - the app's own operational state

The split is deliberate. VeloDB is a columnar MPP warehouse: excellent at
scanning and grouping the business tables, poor at the point read plus point
write that every authenticated request performs against a session row. So
``db`` below is the operational store (what ``auth.py``, ``account.py`` and
``threads.py`` already expected, API-compatible with the PyMongo subset they
used), while analytical access goes through ``backend.velodb``.
"""

from backend.config import INTERNAL_COLLECTIONS, settings
from backend.docstore import DuplicateKeyError, get_store  # noqa: F401 (re-exported)
from backend import velodb

# Operational store: app_users, app_sessions, app_api_keys, app_usage, chat_threads
db = get_store()


def business_collection_names():
    """Tables in VeloDB the chatbot is allowed to read for analytics."""

    names = [
        name
        for name in velodb.list_tables()
        if name not in INTERNAL_COLLECTIONS and not name.startswith("information_schema")
    ]

    if settings.queryable_collections:
        allowed = set(settings.queryable_collections)
        names = [name for name in names if name in allowed]

    return sorted(names)


def ping():
    """True when VeloDB answers. Raises VeloDBError when it does not."""
    velodb.ping()
    return True


def health():
    return {"velodb": velodb.health(), "app_state": {"status": "ok"} if db.ping() else {}}
