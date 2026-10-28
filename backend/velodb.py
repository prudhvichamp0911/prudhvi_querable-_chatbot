"""VeloDB connection and query execution.

VeloDB is built on Apache Doris and speaks the MySQL wire protocol, so the
client here is plain PyMySQL pointed at the FE query port (9030 by default).
The same code works against VeloDB Cloud, VeloDB Enterprise, or the local
Apache Doris container in docker-compose.yml - only .env changes.

Everything this module runs is read-only: ``query()`` refuses anything that is
not a single SELECT/SHOW/DESCRIBE. Writes happen in velodb/load.py, which uses
its own connection and is never reachable from a chat request.
"""
from __future__ import annotations

import re
import threading
from decimal import Decimal

import pymysql
from pymysql.cursors import DictCursor

from backend.config import settings

# One statement, read-only. The query compiler already builds parameterised
# SQL; this is the second line of defence, mirroring what validator.py does
# for the JSON contract.
_READ_ONLY = re.compile(r"^\s*(select|show|describe|desc|with)\b", re.I)
_FORBIDDEN = re.compile(
    r"\b(insert|update|delete|drop|alter|create|truncate|grant|revoke|"
    r"load|outfile|dumpfile|into\s+outfile|set\s+global)\b", re.I)


class VeloDBError(RuntimeError):
    """Raised for connection or query failures against VeloDB."""


class ReadOnlyViolation(VeloDBError):
    """Raised when something tries to run a non-SELECT through the query path."""


_local = threading.local()


def _connect():
    try:
        return pymysql.connect(
            host=settings.velodb_host,
            port=settings.velodb_port,
            user=settings.velodb_user,
            password=settings.velodb_password,
            database=settings.velodb_db,
            charset="utf8mb4",
            cursorclass=DictCursor,
            connect_timeout=settings.velodb_connect_timeout,
            read_timeout=max(5, settings.velodb_query_timeout_seconds + 5),
            autocommit=True,
            program_name="queryable_chatbot",
        )
    except pymysql.Error as error:
        raise VeloDBError(
            f"cannot reach VeloDB at {settings.velodb_host}:{settings.velodb_port} - {error}"
        ) from error


def get_connection():
    """Reuse one connection per thread, reconnecting when the server drops it."""
    con = getattr(_local, "con", None)
    if con is not None:
        try:
            con.ping(reconnect=True)
            return con
        except pymysql.Error:
            try:
                con.close()
            except Exception:
                pass
            _local.con = None
    con = _connect()
    _local.con = con
    return con


def query(sql: str, params=None, *, max_rows: int | None = None) -> list[dict]:
    """Run one read-only statement and return rows as dicts.

    `params` are bound by the driver - values are never formatted into the SQL.
    """
    if not _READ_ONLY.match(sql or "") or _FORBIDDEN.search(sql or ""):
        raise ReadOnlyViolation("only read-only SELECT statements may be executed")
    if ";" in sql.strip().rstrip(";"):
        raise ReadOnlyViolation("multiple statements are not allowed")

    con = get_connection()
    try:
        with con.cursor() as cursor:
            # Doris honours a per-session query timeout, in seconds.
            cursor.execute(f"SET query_timeout = {int(settings.velodb_query_timeout_seconds)}")
            cursor.execute(sql, tuple(params) if params else None)
            rows = cursor.fetchmany(max_rows) if max_rows else cursor.fetchall()
            return [_plain(dict(row)) for row in (rows or [])]
    except pymysql.Error as error:
        # The message is handed to the LLM repair loop, so keep it specific.
        raise VeloDBError(str(error)) from error


def _plain(row: dict) -> dict:
    """DECIMAL -> float.

    MongoDB returned plain floats for money columns, and the answer
    grounding check and the OpenUI renderer both compare numbers against the
    result rows. Leaving Decimal objects in place would serialise them as
    strings and break that comparison.
    """
    return {k: (float(v) if isinstance(v, Decimal) else v) for k, v in row.items()}


def execute(sql: str, params=None) -> int:
    """Run a write statement. Used by the loader and schema setup only."""
    con = get_connection()
    try:
        with con.cursor() as cursor:
            return cursor.execute(sql, tuple(params) if params else None)
    except pymysql.Error as error:
        raise VeloDBError(str(error)) from error


def list_tables() -> list[str]:
    rows = query("SHOW TABLES")
    return sorted(next(iter(row.values())) for row in rows)


def describe_table(table: str) -> list[dict]:
    """Column metadata from the catalog - replaces MongoDB's document sampling."""
    rows = query(
        "SELECT COLUMN_NAME AS name, DATA_TYPE AS type, IS_NULLABLE AS nullable "
        "FROM information_schema.columns "
        "WHERE table_schema = %s AND table_name = %s "
        "ORDER BY ordinal_position",
        (settings.velodb_db, table))
    return rows


def ping() -> bool:
    query("SELECT 1 AS ok")
    return True


def health() -> dict:
    try:
        tables = list_tables()
        return {"status": "ok", "tables": len(tables),
                "host": f"{settings.velodb_host}:{settings.velodb_port}",
                "database": settings.velodb_db}
    except VeloDBError as error:
        return {"status": "unavailable", "error": str(error),
                "host": f"{settings.velodb_host}:{settings.velodb_port}"}
