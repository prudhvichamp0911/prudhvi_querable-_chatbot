"""Create the VeloDB schema and load every CSV dataset into it.

    python -m velodb.load             # create schema (if needed) + load all
    python -m velodb.load --recreate  # drop and rebuild the tables first
    python -m velodb.load --only span_companies

Replaces scripts/import_span_companies.py (which did delete_many + insert_many
into MongoDB). Differences worth knowing:

  * Idempotent without emptying the table first. The UNIQUE KEY tables upsert
    on their natural key, so a re-run converges. The two DUPLICATE KEY tables
    (order_items, sales_cleaned) have no natural key, so those are truncated
    before loading - still idempotent, just by a different route.
  * Validation happens here. Doris enforces no CHECK or FOREIGN KEY
    constraints, so the checks the database can no longer make are made by
    the loader, which refuses a bad batch instead of writing it.
"""
from __future__ import annotations

import argparse
import csv
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend import velodb  # noqa: E402
from backend.config import settings  # noqa: E402

DATA = ROOT / "data"
SCHEMA_SQL = ROOT / "velodb" / "schema.sql"
BATCH = 500


class LoadError(RuntimeError):
    pass


def _int(value):
    if value is None or value == "":
        return None
    return int(float(value))


def _float(value):
    if value is None or value == "":
        return None
    return float(value)


def _date(value):
    if not value:
        return None
    return datetime.strptime(value.strip()[:10], "%Y-%m-%d").date()


def _text(value):
    value = (value or "").strip()
    return value or None


# table -> (csv path, columns, row builder, truncate_first)
DATASETS = {
    "span_companies": (
        DATA / "span_companies.csv",
        ["company_id", "company_name", "industry", "country", "employee_count",
         "hr_technology", "technology_category", "deployment_type",
         "annual_hr_tech_spend_usd"],
        lambda r: [r["company_id"], r["company_name"], r["industry"], r["country"],
                   _int(r["employee_count"]), r["hr_technology"],
                   r["technology_category"], r["deployment_type"],
                   _float(r["annual_hr_tech_spend_usd"])],
        False,
    ),
    "customers": (
        DATA / "kaggle_ecommerce" / "customers.csv",
        ["customer_id", "country", "signup_date"],
        lambda r: [_int(r["customer_id"]), _text(r["country"]), _date(r["signup_date"])],
        False,
    ),
    "products": (
        DATA / "kaggle_ecommerce" / "products.csv",
        ["product_id", "product_name", "category"],
        lambda r: [_int(r["product_id"]), _text(r["product_name"]), _text(r["category"])],
        False,
    ),
    "orders": (
        DATA / "kaggle_ecommerce" / "orders.csv",
        ["order_id", "customer_id", "order_date", "status"],
        lambda r: [_int(r["order_id"]), _int(r["customer_id"]),
                   _date(r["order_date"]), _text(r["status"])],
        False,
    ),
    "order_items": (
        DATA / "kaggle_ecommerce" / "order_items.csv",
        ["order_id", "product_id", "quantity", "price"],
        lambda r: [_int(r["order_id"]), _int(r["product_id"]),
                   _int(r["quantity"]), _float(r["price"])],
        True,
    ),
    "sales_cleaned": (
        DATA / "kaggle_ecommerce" / "sales_cleaned.csv",
        ["order_id", "product_id", "quantity", "price", "revenue", "customer_id",
         "order_date", "status", "year", "month"],
        lambda r: [_int(r["order_id"]), _int(r["product_id"]), _int(r["quantity"]),
                   _float(r["price"]), _float(r.get("Revenue") or r.get("revenue")),
                   _int(r["customer_id"]), _date(r["order_date"]), _text(r["status"]),
                   _int(r["year"]), _int(r["month"])],
        True,
    ),
}


def read_csv(path: Path) -> list[dict]:
    if not path.exists():
        raise LoadError(f"missing data file: {path}")
    with open(path, newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        raise LoadError(f"{path} has no data rows")
    return rows


def validate_span(rows: list[dict]) -> None:
    """Checks Doris cannot make for us.

    The important one is the vendor -> category dependency: in the source data
    every hr_technology maps to exactly one technology_category. The Mongo
    schema never enforced it either, but the chatbot's answers assume it, so
    a violation should stop the load rather than silently skew group-bys.
    """
    seen: dict[str, set] = {}
    for row in rows:
        seen.setdefault(row["hr_technology"], set()).add(row["technology_category"])
    broken = {k: sorted(v) for k, v in seen.items() if len(v) > 1}
    if broken:
        raise LoadError(f"hr_technology maps to multiple categories: {broken}")

    ids = [r["company_id"] for r in rows]
    if len(ids) != len(set(ids)):
        raise LoadError("duplicate company_id values in span_companies.csv")


def apply_schema(recreate: bool = False) -> None:
    # Strip comment lines out of each statement rather than skipping any
    # statement that merely starts with one - every CREATE TABLE in
    # schema.sql is preceded by a comment banner.
    raw = SCHEMA_SQL.read_text(encoding="utf-8")
    statements = []
    for chunk in raw.split(";"):
        body = "\n".join(line for line in chunk.splitlines()
                         if not line.strip().startswith("--")).strip()
        if body:
            statements.append(body)
    # CREATE DATABASE / USE must run before the session has a database.
    import pymysql
    con = pymysql.connect(
        host=settings.velodb_host, port=settings.velodb_port,
        user=settings.velodb_user, password=settings.velodb_password,
        connect_timeout=settings.velodb_connect_timeout, autocommit=True)
    try:
        with con.cursor() as cursor:
            cursor.execute(f"CREATE DATABASE IF NOT EXISTS `{settings.velodb_db}`")
            cursor.execute(f"USE `{settings.velodb_db}`")
            if recreate:
                for table in DATASETS:
                    cursor.execute(f"DROP TABLE IF EXISTS `{table}`")
            for statement in statements:
                lowered = statement.lower()
                if lowered.startswith("create database") or lowered.startswith("use "):
                    continue
                cursor.execute(statement)
    finally:
        con.close()


def load_table(table: str) -> int:
    path, columns, build, truncate_first = DATASETS[table]
    rows = read_csv(path)
    if table == "span_companies":
        validate_span(rows)

    values = []
    for index, row in enumerate(rows, start=2):   # line 1 is the header
        try:
            values.append(build(row))
        except (KeyError, ValueError) as error:
            raise LoadError(f"{path.name} line {index}: {error}") from error

    if truncate_first:
        velodb.execute(f"TRUNCATE TABLE `{table}`")

    placeholders = ", ".join(["%s"] * len(columns))
    column_list = ", ".join(f"`{c}`" for c in columns)
    sql = f"INSERT INTO `{table}` ({column_list}) VALUES ({placeholders})"

    con = velodb.get_connection()
    written = 0
    with con.cursor() as cursor:
        for start in range(0, len(values), BATCH):
            chunk = values[start:start + BATCH]
            cursor.executemany(sql, chunk)
            written += len(chunk)
    return written


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--recreate", action="store_true",
                        help="drop and rebuild the tables before loading")
    parser.add_argument("--only", action="append", choices=sorted(DATASETS),
                        help="load only these tables (repeatable)")
    parser.add_argument("--if-empty", action="store_true",
                        help="skip any table that already holds rows "
                             "(used by start.ps1 so restarts are cheap)")
    args = parser.parse_args(argv)

    try:
        # apply_schema connects without selecting a database, so this also
        # works on a fresh cluster where queryable_chatbot does not exist yet.
        apply_schema(recreate=args.recreate)
    except Exception as error:
        print(f"VeloDB is not reachable, or the schema could not be applied:\n"
              f"  {error}\n"
              f"Start the warehouse with:  docker compose up -d", file=sys.stderr)
        return 1

    try:
        targets = args.only or list(DATASETS)
        print(f"loading into {settings.velodb_db} "
              f"at {settings.velodb_host}:{settings.velodb_port}\n")
        for table in targets:
            if args.if_empty:
                existing = velodb.query(f"SELECT COUNT(*) AS n FROM `{table}`")[0]["n"]
                if existing:
                    print(f"  {table:<18} already holds {existing:>5} rows - skipped")
                    continue
            written = load_table(table)
            total = velodb.query(f"SELECT COUNT(*) AS n FROM `{table}`")[0]["n"]
            print(f"  {table:<18} wrote {written:>5}   table now holds {total:>5}")
    except (LoadError, Exception) as error:
        print(f"\nload failed: {error}", file=sys.stderr)
        return 1

    print("\nall datasets loaded")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
