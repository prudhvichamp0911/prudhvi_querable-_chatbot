"""Discover the VeloDB schema the chatbot is allowed to query.

Under MongoDB this sampled 1000 documents per collection and guessed each
field's type from the first document that happened to contain it. VeloDB has
a real catalog, so this now reads ``information_schema`` instead: the types
are exact, no field can hide beyond a sample window, and an empty table still
reports its columns.

The output shape is unchanged, because the validator, the query prompt and
``insights.py`` all consume it:

    {"<table>": {"<column>": {"type": "<sql type>", "sample_values": [...]}}}
"""

import copy
import threading
import time

from backend.config import settings
from backend.db import business_collection_names
from backend import velodb

SAMPLE_VALUES = 3
SCHEMA_CACHE_SECONDS = 60

_cache = {"at": 0.0, "value": None}
_lock = threading.Lock()

# SQL types that behave as numbers, for insights.py's metric detection.
NUMERIC_TYPES = frozenset({
    "tinyint", "smallint", "int", "integer", "bigint", "largeint",
    "float", "double", "decimal", "decimalv3", "decimal128",
})


def is_numeric(type_name):
    return str(type_name or "").split("(")[0].strip().lower() in NUMERIC_TYPES


def discover_schema():
    schema = {}

    for table in business_collection_names():
        columns = {}
        for column in velodb.describe_table(table):
            name = column["name"]
            columns[name] = {
                "type": str(column["type"]).lower(),
                "sample_values": [],
            }

        if not columns:
            continue

        # A few real values per column help the model pick filter values.
        # One grouped query per table keeps this cheap.
        for name in list(columns):
            try:
                rows = velodb.query(
                    f"SELECT DISTINCT `{name}` AS v FROM `{table}` "
                    f"WHERE `{name}` IS NOT NULL LIMIT {SAMPLE_VALUES}")
                columns[name]["sample_values"] = [r["v"] for r in rows]
            except Exception:
                # A sample is a nicety; never fail discovery over one column.
                columns[name]["sample_values"] = []

        schema[table] = columns

    return schema


def get_schema(force=False):
    """Cached schema. Raises if VeloDB is unreachable and nothing is cached."""
    with _lock:
        fresh = (time.time() - _cache["at"]) < SCHEMA_CACHE_SECONDS
        if not force and fresh and _cache["value"] is not None:
            return copy.deepcopy(_cache["value"])

    value = discover_schema()

    with _lock:
        _cache["at"] = time.time()
        _cache["value"] = value
        return copy.deepcopy(value)


def clear_schema_cache():
    with _lock:
        _cache["at"] = 0.0
        _cache["value"] = None


if __name__ == "__main__":
    for table, columns in get_schema().items():
        print(f"\n{table}")
        for name, info in columns.items():
            print(f"  {name:<28} {info['type']:<16} {info['sample_values']}")
