"""Execute a validated query contract against VeloDB.

This is the module the MongoDB -> VeloDB migration replaced wholesale. The
contract it accepts is unchanged (see backend/query_compiler.py for why), so
callers - langchain_tools, chat_service, the OpenUI renderer - did not change.

Every query is read-only, time-limited and row-limited. The validator runs
before this module is called; the limits here are a second line of defence
against a slow or very large read, exactly as they were under Mongo.
"""

from backend.config import settings
from backend.db import business_collection_names
from backend.guardrails import redact_pii
from backend.query_compiler import CompileError, Compiler, rebuild_rows
from backend.schema_discovery import get_schema
from backend import velodb

MAX_ROWS = settings.max_result_rows


def _columns_for(table):
    schema = get_schema()
    if table not in schema:
        known = ", ".join(sorted(schema)) or "none"
        raise CompileError(f"unknown table {table!r}; available tables: {known}")
    return list(schema[table].keys())


def run_database_query(query):
    """Compile the contract to SQL, run it, and return rows as dicts.

    Raises CompileError for a contract that cannot be expressed, and
    VeloDBError when the warehouse rejects or cannot run the SQL. Both
    messages are propagated to the model's repair loop, which is why they
    carry the real reason rather than a generic string.
    """
    table = query["collection"]
    operation = query.get("operation", "find")
    filters = query.get("filters", {}) or {}
    fields = query.get("fields", []) or []
    pipeline = query.get("pipeline", []) or []
    field = query.get("field")

    if table not in business_collection_names():
        raise CompileError(f"table {table!r} is not queryable")

    compiler = Compiler(table, _columns_for(table), max_rows=MAX_ROWS)

    if operation == "find":
        compiled = compiler.find(filters, fields)
    elif operation == "count":
        compiled = compiler.count(filters)
    elif operation == "distinct":
        if not field:
            raise CompileError("field is required for a distinct operation")
        compiled = compiler.distinct(field, filters)
    elif operation == "aggregate":
        compiled = compiler.aggregate(pipeline)
    else:
        raise CompileError(f"unsupported operation {operation!r}")

    rows = velodb.query(compiled.sql, compiled.params, max_rows=MAX_ROWS)
    rows = rebuild_rows(rows, compiled)

    if operation == "count":
        # Same shape the Mongo tool returned: [{"count": n}]
        return [{"count": int(rows[0]["count"]) if rows else 0}]

    return redact_pii(rows)


def explain_query(query):
    """The SQL a contract compiles to, without running it (used by tests/debug)."""
    table = query["collection"]
    compiler = Compiler(table, _columns_for(table), max_rows=MAX_ROWS)
    operation = query.get("operation", "find")
    if operation == "find":
        compiled = compiler.find(query.get("filters", {}) or {}, query.get("fields", []) or [])
    elif operation == "count":
        compiled = compiler.count(query.get("filters", {}) or {})
    elif operation == "distinct":
        compiled = compiler.distinct(query["field"], query.get("filters", {}) or {})
    else:
        compiled = compiler.aggregate(query.get("pipeline", []) or [])
    return compiled.sql, compiled.params
