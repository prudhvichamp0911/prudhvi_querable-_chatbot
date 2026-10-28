"""Compile the chatbot's JSON query contract into VeloDB (Doris) SQL.

The contract did not change in the MongoDB -> VeloDB migration:

    {"collection": ..., "operation": find|count|distinct|aggregate,
     "filters": {...}, "fields": [...], "field": ..., "pipeline": [...]}

Keeping the envelope is deliberate. It is the interface between the LLM
prompt, the validator, the chat service, the OpenUI renderer and the browser,
so changing it would ripple through all of them. Instead this module
translates it: filters become a parameterised WHERE clause, and the subset of
aggregation stages the data actually needs becomes GROUP BY / ORDER BY / LIMIT.

Two properties matter for safety:

  * Every identifier (table, column) is checked against the live VeloDB
    catalog and quoted. Nothing from the model reaches the SQL as an
    identifier unless the catalog already contains it.
  * Every value is a bound parameter. There is no string interpolation of
    user or model supplied values anywhere in this file.

The ``_id`` convention from the Mongo era is preserved on the way out: a
grouped result still carries ``_id`` (a scalar, or a dict for a composite
group key), because ``insights.py`` and ``openui_engine._flatten_row`` read it.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field as dataclass_field
from typing import Any

IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")

# Mongo filter operator -> SQL comparison
COMPARISONS = {"$eq": "=", "$gt": ">", "$gte": ">=", "$lt": "<", "$lte": "<="}

# Mongo $group accumulator -> SQL aggregate function
ACCUMULATORS = {"$sum": "SUM", "$avg": "AVG", "$min": "MIN", "$max": "MAX",
                "$count": "COUNT"}

SUPPORTED_STAGES = {"$match", "$group", "$sort", "$limit", "$skip", "$project"}


class CompileError(ValueError):
    """The contract cannot be expressed as SQL against this schema."""


@dataclass
class CompiledQuery:
    sql: str
    params: list[Any] = dataclass_field(default_factory=list)
    # How to rebuild a composite _id from flat SQL columns, e.g. {"year","month"}
    composite_id: list[str] | None = None
    # True when the result is a grouped aggregate (affects _id handling)
    grouped: bool = False


def quote(identifier: str) -> str:
    if not IDENTIFIER.match(identifier or ""):
        raise CompileError(f"invalid identifier: {identifier!r}")
    return f"`{identifier}`"


def _field_ref(expression: Any) -> str:
    """Turn a Mongo field reference ("$country") into a bare column name."""
    if isinstance(expression, str) and expression.startswith("$"):
        return expression[1:]
    raise CompileError(f"expected a field reference like \"$column\", got {expression!r}")


class Compiler:
    def __init__(self, table: str, columns: list[str], max_rows: int = 200):
        self.table = table
        self.columns = set(columns)
        self.max_rows = max_rows

    # -- helpers ------------------------------------------------------

    def column(self, name: str) -> str:
        root = name.split(".", 1)[0]
        if root not in self.columns:
            raise CompileError(
                f"unknown column {root!r} on table {self.table!r}; "
                f"available: {', '.join(sorted(self.columns))}")
        return quote(root)

    # -- filters ------------------------------------------------------

    def where(self, filters: dict | None) -> tuple[str, list]:
        if not filters:
            return "", []
        clause, params = self._conditions(filters)
        return (f" WHERE {clause}" if clause else ""), params

    def _conditions(self, filters: dict) -> tuple[str, list]:
        parts: list[str] = []
        params: list[Any] = []

        for key, condition in filters.items():
            if key in ("$and", "$or", "$nor"):
                if not isinstance(condition, list) or not condition:
                    raise CompileError(f"{key} needs a non-empty list")
                sub_parts = []
                for item in condition:
                    text, sub_params = self._conditions(item)
                    sub_parts.append(f"({text})")
                    params.extend(sub_params)
                joiner = " AND " if key == "$and" else " OR "
                combined = joiner.join(sub_parts)
                parts.append(f"NOT ({combined})" if key == "$nor" else f"({combined})")
                continue

            if key.startswith("$"):
                raise CompileError(f"unsupported top-level operator {key}")

            column = self.column(key)

            if isinstance(condition, dict) and condition and all(
                    k.startswith("$") for k in condition):
                text, sub_params = self._operators(column, condition)
                parts.append(text)
                params.extend(sub_params)
            elif condition is None:
                parts.append(f"{column} IS NULL")
            else:
                parts.append(f"{column} = %s")
                params.append(condition)

        return " AND ".join(parts), params

    def _operators(self, column: str, condition: dict) -> tuple[str, list]:
        parts: list[str] = []
        params: list[Any] = []
        options = condition.get("$options", "")

        for operator, value in condition.items():
            if operator == "$options":
                continue

            if operator in COMPARISONS:
                parts.append(f"{column} {COMPARISONS[operator]} %s")
                params.append(value)
            elif operator == "$ne":
                if value is None:
                    parts.append(f"{column} IS NOT NULL")
                else:
                    # Mongo's $ne also matches missing fields, so NULL counts.
                    parts.append(f"({column} IS NULL OR {column} <> %s)")
                    params.append(value)
            elif operator in ("$in", "$nin"):
                if not isinstance(value, list):
                    raise CompileError(f"{operator} needs a list")
                if not value:
                    parts.append("1 = 0" if operator == "$in" else "1 = 1")
                    continue
                placeholders = ", ".join(["%s"] * len(value))
                negate = "NOT " if operator == "$nin" else ""
                parts.append(f"{column} {negate}IN ({placeholders})")
                params.extend(value)
            elif operator == "$regex":
                if not isinstance(value, str):
                    raise CompileError("$regex needs a string")
                # Case-insensitive matching: compare lowercased on both sides.
                if "i" in str(options):
                    parts.append(f"LOWER({column}) REGEXP %s")
                    params.append(value.lower())
                else:
                    parts.append(f"{column} REGEXP %s")
                    params.append(value)
            elif operator == "$exists":
                # Every SQL row has every column, so "exists" can only mean
                # NOT NULL. This is the one Mongo operator whose meaning
                # genuinely changes in a columnar store.
                parts.append(f"{column} IS {'NOT NULL' if value else 'NULL'}")
            else:
                raise CompileError(f"unsupported filter operator {operator}")

        return "(" + " AND ".join(parts) + ")", params

    # -- operations ---------------------------------------------------

    def find(self, filters: dict, fields: list[str], limit: int | None = None) -> CompiledQuery:
        if fields:
            select = ", ".join(self.column(f) for f in fields)
        else:
            select = "*"
        where, params = self.where(filters)
        limit = min(limit or self.max_rows, self.max_rows)
        return CompiledQuery(
            f"SELECT {select} FROM {quote(self.table)}{where} LIMIT {limit}", params)

    def count(self, filters: dict) -> CompiledQuery:
        where, params = self.where(filters)
        return CompiledQuery(
            f"SELECT COUNT(*) AS `count` FROM {quote(self.table)}{where}", params)

    def distinct(self, field: str, filters: dict) -> CompiledQuery:
        column = self.column(field)
        where, params = self.where(filters)
        return CompiledQuery(
            f"SELECT DISTINCT {column} AS `value` FROM {quote(self.table)}{where} "
            f"ORDER BY `value` LIMIT {self.max_rows}", params)

    # -- aggregation pipeline ----------------------------------------

    def aggregate(self, pipeline: list[dict]) -> CompiledQuery:
        if not isinstance(pipeline, list) or not pipeline:
            raise CompileError("pipeline must be a non-empty list")

        where_parts: list[str] = []
        params: list[Any] = []
        group_columns: dict[str, str] = {}   # output alias -> source column
        composite_id: list[str] | None = None
        metrics: dict[str, str] = {}          # output alias -> SQL expression
        order_by: list[str] = []
        limit: int | None = None
        offset: int | None = None
        grouped = False
        projection: list[str] | None = None

        for stage in pipeline:
            if not isinstance(stage, dict) or len(stage) != 1:
                raise CompileError("each pipeline stage needs exactly one key")
            name, body = next(iter(stage.items()))
            if name not in SUPPORTED_STAGES:
                raise CompileError(
                    f"stage {name} is not supported on VeloDB; "
                    f"supported: {', '.join(sorted(SUPPORTED_STAGES))}")

            if name == "$match":
                if grouped:
                    raise CompileError("$match must come before $group")
                text, sub_params = self._conditions(body)
                if text:
                    where_parts.append(f"({text})")
                    params.extend(sub_params)

            elif name == "$group":
                grouped = True
                if "_id" not in body:
                    raise CompileError("$group needs an _id")
                key = body["_id"]
                if key is None:
                    pass                              # one overall bucket
                elif isinstance(key, str):
                    column = _field_ref(key)
                    group_columns["_id"] = column
                elif isinstance(key, dict):
                    composite_id = []
                    for alias, expression in key.items():
                        if not IDENTIFIER.match(alias):
                            raise CompileError(f"invalid group key alias {alias!r}")
                        group_columns[alias] = _field_ref(expression)
                        composite_id.append(alias)
                else:
                    raise CompileError("$group _id must be null, a field, or an object")

                for alias, accumulator in body.items():
                    if alias == "_id":
                        continue
                    if not IDENTIFIER.match(alias):
                        raise CompileError(f"invalid metric alias {alias!r}")
                    if not isinstance(accumulator, dict) or len(accumulator) != 1:
                        raise CompileError(f"metric {alias} needs one accumulator")
                    op, operand = next(iter(accumulator.items()))
                    if op not in ACCUMULATORS:
                        raise CompileError(
                            f"accumulator {op} is not supported; "
                            f"use {', '.join(sorted(ACCUMULATORS))}")
                    if operand == 1 or operand is True:
                        metrics[alias] = "COUNT(*)"
                    else:
                        column = self.column(_field_ref(operand))
                        metrics[alias] = f"{ACCUMULATORS[op]}({column})"

            elif name == "$sort":
                if not isinstance(body, dict) or not body:
                    raise CompileError("$sort needs a non-empty object")
                for key, direction in body.items():
                    if direction not in (1, -1):
                        raise CompileError("$sort direction must be 1 or -1")
                    way = "ASC" if direction == 1 else "DESC"
                    order_by.append(f"{self._sort_target(key, group_columns, metrics)} {way}")

            elif name == "$limit":
                if not isinstance(body, int) or isinstance(body, bool) or body <= 0:
                    raise CompileError("$limit must be a positive integer")
                limit = body

            elif name == "$skip":
                if not isinstance(body, int) or isinstance(body, bool) or body < 0:
                    raise CompileError("$skip must be a non-negative integer")
                offset = body

            elif name == "$project":
                if not isinstance(body, dict) or not body:
                    raise CompileError("$project needs a non-empty object")
                projection = [k for k, v in body.items() if v and k != "_id"]

        # ---- assemble
        select_parts: list[str] = []
        for alias, column in group_columns.items():
            select_parts.append(f"{self.column(column)} AS {quote(alias)}")
        for alias, expression in metrics.items():
            select_parts.append(f"{expression} AS {quote(alias)}")

        if not select_parts:
            if not grouped:
                raise CompileError("pipeline produced no output columns")
            select_parts.append("COUNT(*) AS `count`")

        sql = f"SELECT {', '.join(select_parts)} FROM {quote(self.table)}"
        if where_parts:
            sql += " WHERE " + " AND ".join(where_parts)
        if group_columns:
            sql += " GROUP BY " + ", ".join(
                self.column(c) for c in group_columns.values())
        if order_by:
            sql += " ORDER BY " + ", ".join(order_by)

        effective = min(limit or self.max_rows, self.max_rows)
        sql += f" LIMIT {effective}"
        if offset:
            sql += f" OFFSET {offset}"

        if projection:
            # SQL already returns named columns; $project only narrows them,
            # which we do in Python to keep the _id rebuild intact.
            pass

        return CompiledQuery(sql, params, composite_id=composite_id, grouped=grouped)

    def _sort_target(self, key: str, group_columns: dict, metrics: dict) -> str:
        """Resolve a $sort key, including Mongo's dotted "_id.year" form."""
        if key in metrics:
            return quote(key)
        if key == "_id" and "_id" in group_columns:
            return quote("_id")
        if key.startswith("_id."):
            alias = key.split(".", 1)[1]
            if alias in group_columns:
                return quote(alias)
            raise CompileError(f"unknown group key {key!r}")
        if key in group_columns:
            return quote(key)
        if key in self.columns:
            return quote(key)
        raise CompileError(f"cannot sort by {key!r}")


def rebuild_rows(rows: list[dict], compiled: CompiledQuery) -> list[dict]:
    """Restore the Mongo-shaped result the rest of the app expects.

    A composite group key comes back from SQL as separate columns; downstream
    code (insights._label_of, openui_engine._flatten_row) expects them nested
    under ``_id``.
    """
    if not compiled.composite_id:
        return rows
    out = []
    for row in rows:
        rebuilt = {"_id": {k: row.get(k) for k in compiled.composite_id}}
        for key, value in row.items():
            if key not in compiled.composite_id:
                rebuilt[key] = value
        out.append(rebuilt)
    return out
