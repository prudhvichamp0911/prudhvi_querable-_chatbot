"""Deterministic data insights (no LLM call, every number from VeloDB).

* ``result_insights`` reads one chat answer's rows and finds the story in
  them: leader share, concentration, spread, skew, trend, peak.
* ``overview`` builds the Insights dashboard: KPI tiles and chart panels
  from fixed, read-only aggregations over the business collections.
* ``geo_datasets`` / ``geo_explore`` power the Geo Explorer page.
"""

import re
import statistics

from backend.config import settings
from backend import velodb
from backend.db import db
from backend.geo import build_geo_payload, lookup
from backend.schema_discovery import get_schema, is_numeric

MAX_ROWS = settings.max_result_rows
_FIELD = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")
_SKIP_METRIC = re.compile(r"(^_?id$|_id$|^year$|^month$|^day$)", re.IGNORECASE)
_TIME_KEY = re.compile(r"(date|month|year|period|week|day|quarter)", re.IGNORECASE)
_PERIOD = re.compile(r"^\d{4}(-\d{1,2})?(-\d{1,2})?$")


def _fmt(value):
    if abs(value) >= 1_000_000:
        return f"{value / 1_000_000:.1f}M"
    if abs(value) >= 10_000:
        return f"{value / 1_000:.1f}K"
    if float(value).is_integer():
        return f"{value:,.0f}"
    return f"{value:,.2f}"


def _label_of(row):
    """(label, is_time) for a result row."""

    ident = row.get("_id")
    if isinstance(ident, dict):
        if "year" in ident and "month" in ident:
            return f"{ident['year']}-{int(ident['month']):02d}", True
        return " · ".join(str(v) for v in ident.values()), any(_TIME_KEY.search(k) for k in ident)
    if isinstance(ident, str):
        return ident, bool(_PERIOD.match(ident))
    if isinstance(ident, (int, float)) and not isinstance(ident, bool):
        return str(ident), 1900 <= ident <= 2100
    if "year" in row and "month" in row:
        return f"{row['year']}-{int(row['month']):02d}", True
    for key, value in row.items():
        if isinstance(value, str):
            return value, bool(_TIME_KEY.search(key)) or bool(_PERIOD.match(value))
    return None, False


def _value_of(row):
    for key, value in row.items():
        if key == "_id" or isinstance(value, bool) or _SKIP_METRIC.search(key):
            continue
        if isinstance(value, (int, float)):
            return key, float(value)
    return None, None


def label_value_rows(rows):
    """[(label, value)], metric key, is_time — or ([], None, False)."""

    pairs, metric, time_votes = [], None, 0
    for row in rows:
        if not isinstance(row, dict):
            continue
        label, is_time = _label_of(row)
        key, value = _value_of(row)
        if label is None or key is None:
            continue
        metric = metric or key
        time_votes += is_time
        pairs.append((label, value))
    is_time = bool(pairs) and time_votes >= len(pairs) / 2
    return pairs, metric, is_time


def _pretty(key):
    text = (key or "value").replace("_", " ")
    text = re.sub(r"\busd\b", "(USD)", text, flags=re.IGNORECASE)
    return text[:1].upper() + text[1:]


def _category_insights(pairs, metric):
    values = [v for _, v in pairs]
    total = sum(values)
    ranked = sorted(pairs, key=lambda p: p[1], reverse=True)
    out = []
    if re.search(r"avg|average|mean|rate|ratio|pct|percent", metric, re.IGNORECASE):
        # Shares of an average are meaningless: report the highest value instead.
        leader, value = ranked[0]
        out.append({"kind": "leader", "title": f"{leader} is highest",
                    "value": _fmt(value), "detail": metric.lower()})
    elif total > 0:
        leader, value = ranked[0]
        out.append({"kind": "leader", "title": f"{leader} leads",
                    "value": f"{value / total:.0%}", "detail": f"share of total {metric.lower()}"})
    if len(ranked) >= 2 and ranked[-1][1] > 0:
        ratio = ranked[0][1] / ranked[-1][1]
        out.append({"kind": "spread", "title": "Highest vs lowest",
                    "value": f"{ratio:.1f}×", "detail": f"{ranked[0][0]} vs {ranked[-1][0]}"})
    if len(ranked) >= 5 and total > 0:
        top3 = sum(v for _, v in ranked[:3]) / total
        out.append({"kind": "concentration", "title": "Top 3 concentration",
                    "value": f"{top3:.0%}", "detail": f"of {len(ranked)} groups"})
    if len(values) >= 4:
        mean, median = statistics.fmean(values), statistics.median(values)
        if median > 0 and mean / median >= 1.3:
            out.append({"kind": "skew", "title": "Skewed by a few large groups",
                        "value": f"{mean / median:.1f}×", "detail": "mean vs median"})
        else:
            out.append({"kind": "average", "title": "Typical group",
                        "value": _fmt(median), "detail": f"median {metric.lower()}"})
    return out


def _time_insights(pairs, metric):
    pairs = sorted(pairs, key=lambda p: p[0])
    values = [v for _, v in pairs]
    out = []
    first, last = values[0], values[-1]
    if first:
        change = (last - first) / abs(first)
        out.append({"kind": "trend", "title": "Up over the period" if change >= 0 else "Down over the period",
                    "value": f"{change:+.0%}", "detail": f"{pairs[0][0]} → {pairs[-1][0]}"})
    peak = max(pairs, key=lambda p: p[1])
    out.append({"kind": "peak", "title": "Peak period", "value": peak[0],
                "detail": f"{_fmt(peak[1])} {metric.lower()}"})
    if len(values) >= 3:
        moves = [(pairs[i][0], values[i] - values[i - 1]) for i in range(1, len(values))]
        best = max(moves, key=lambda m: m[1])
        worst = min(moves, key=lambda m: m[1])
        if best[1] > 0:
            out.append({"kind": "jump", "title": "Biggest jump", "value": f"+{_fmt(best[1])}", "detail": best[0]})
        if worst[1] < 0:
            out.append({"kind": "drop", "title": "Sharpest drop", "value": f"−{_fmt(-worst[1])}", "detail": worst[0]})
        out.append({"kind": "average", "title": "Average per period",
                    "value": _fmt(statistics.fmean(values)), "detail": metric.lower()})
    return out[:4]


def result_insights(rows):
    """``data_insights`` tool result for a grouped (aggregate) answer, or None."""

    grouped = rows and all(isinstance(row, dict) and ("_id" in row or len(row) <= 3) for row in rows)
    if not grouped:
        return None  # raw documents: no group/value story to tell
    pairs, metric, is_time = label_value_rows(rows)
    if len(pairs) < 2:
        return None
    label = _pretty(metric)
    cards = _time_insights(pairs, label) if is_time else _category_insights(pairs, label)
    if not cards:
        return None
    values = [v for _, v in pairs]
    return {
        "metric": label,
        "shape": "time" if is_time else "category",
        "groups": len(pairs),
        "total": sum(values),
        "series": [{"label": l, "value": v} for l, v in (sorted(pairs) if is_time else pairs)][:24],
        "insights": cards,
    }


# ---------------------------------------------------------------- dashboard

def _row_count(table):
    """COUNT(*) replaces Mongo's estimated_document_count; on a columnar
    store this is cheap enough to be exact."""
    try:
        return int(velodb.query(f"SELECT COUNT(*) AS n FROM `{table}`")[0]["n"])
    except Exception:
        return 0


def _agg(collection, pipeline):
    """Run a dashboard pipeline against VeloDB.

    These pipelines were written for MongoDB. Rather than rewrite all eight
    of them as SQL by hand, they go through the same compiler the chatbot
    uses (backend/query_compiler.py), which also means the dashboard and the
    chat answers can never disagree about what a grouping means.
    """
    from backend.query_compiler import Compiler, rebuild_rows

    columns = list(get_schema().get(collection, {}).keys())
    if not columns:
        return []
    compiled = Compiler(collection, columns, max_rows=MAX_ROWS).aggregate(pipeline)
    rows = velodb.query(compiled.sql, compiled.params, max_rows=MAX_ROWS)
    return rebuild_rows(rows, compiled)


def _group(collection, by, value=None, op="$sum", limit=12, sort_by_label=False):
    accumulator = {op: f"${value}"} if value else {"$sum": 1}
    pipeline = [
        {"$group": {"_id": f"${by}", "value": accumulator}},
        {"$sort": {"_id": 1} if sort_by_label else {"value": -1}},
        {"$limit": limit},
    ]
    return [{"label": str(r["_id"]), "value": round(float(r["value"] or 0), 2)}
            for r in _agg(collection, pipeline) if r["_id"] is not None]


def _has(schema, collection, *fields):
    return collection in schema and all(f in schema[collection] for f in fields)


def _headline(panel):
    pairs = [(r["label"], r["value"]) for r in panel["rows"]]
    if len(pairs) < 2:
        return None
    if panel["kind"] == "line":
        return _time_insights(pairs, panel["metric"])[0]
    return _category_insights(pairs, panel["metric"])[0]


def overview():
    schema = get_schema()
    kpis, panels = [], []

    counts = []
    for name in sorted(schema):
        counts.append({"id": f"count:{name}", "label": _pretty(name), "value": _row_count(name),
                     "format": "number", "hint": "documents"})

    if _has(schema, "span_companies", "annual_hr_tech_spend_usd"):
        stats = _agg("span_companies", [{"$group": {
            "_id": None, "total": {"$sum": "$annual_hr_tech_spend_usd"},
            "avg": {"$avg": "$annual_hr_tech_spend_usd"}, "employees": {"$sum": "$employee_count"}}}])
        if stats:
            kpis.insert(0, {"id": "hr_spend", "label": "HR tech spend", "value": stats[0]["total"],
                            "format": "currency", "hint": f"avg {_fmt(stats[0]['avg'])} per company"})
            if stats[0].get("employees"):
                kpis.insert(1, {"id": "employees", "label": "Employees covered", "value": stats[0]["employees"],
                                "format": "number", "hint": "across all companies"})
        if _has(schema, "span_companies", "industry"):
            panels.append({"id": "industry_spend", "title": "HR tech spend by industry", "kind": "bar",
                           "metric": "Spend (USD)", "format": "currency",
                           "rows": _group("span_companies", "industry", "annual_hr_tech_spend_usd")})
        if _has(schema, "span_companies", "deployment_type"):
            panels.append({"id": "deployment", "title": "Deployment mix", "kind": "donut",
                           "metric": "Companies", "format": "number",
                           "rows": _group("span_companies", "deployment_type", limit=6)})
        if _has(schema, "span_companies", "hr_technology"):
            panels.append({"id": "technologies", "title": "Most used HR technologies", "kind": "bar",
                           "metric": "Companies", "format": "number",
                           "rows": _group("span_companies", "hr_technology", limit=8)})

    if _has(schema, "sales_cleaned", "Revenue", "year", "month"):
        rows = _agg("sales_cleaned", [
            {"$group": {"_id": {"year": "$year", "month": "$month"}, "value": {"$sum": "$Revenue"}}},
            {"$sort": {"_id.year": 1, "_id.month": 1}},
        ])
        series = [{"label": f"{r['_id']['year']}-{int(r['_id']['month']):02d}", "value": round(float(r["value"]), 2)}
                  for r in rows if r["_id"].get("year") and r["_id"].get("month")]
        if series:
            kpis.insert(0, {"id": "revenue", "label": "Revenue", "value": sum(r["value"] for r in series),
                            "format": "currency", "hint": f"{len(series)} months of sales"})
            panels.append({"id": "revenue_trend", "title": "Monthly revenue", "kind": "line",
                           "metric": "Revenue", "format": "currency", "rows": series[-24:]})

    if _has(schema, "orders", "status"):
        status = _group("orders", "status", limit=8)
        panels.append({"id": "order_status", "title": "Orders by status", "kind": "donut",
                       "metric": "Orders", "format": "number", "rows": status})
        total = sum(r["value"] for r in status)
        done = sum(r["value"] for r in status if r["label"].lower() in {"completed", "delivered"})
        if total:
            kpis.append({"id": "completion", "label": "Order completion", "value": done / total,
                         "format": "percent", "hint": f"{_fmt(done)} of {_fmt(total)} orders"})

    if _has(schema, "products", "category"):
        panels.append({"id": "products", "title": "Products by category", "kind": "bar",
                       "metric": "Products", "format": "number", "rows": _group("products", "category", limit=8)})

    maps = []
    for dataset in geo_datasets(schema):
        payload = geo_explore(dataset["collection"], dataset["place_field"], schema=schema)
        if payload:
            maps.append({"id": dataset["collection"], "title": f"{_pretty(dataset['collection'])} by "
                         f"{dataset['place_field']}", **payload})

    panels = [p for p in panels if p["rows"]]
    headlines = []
    for panel in panels:
        insight = _headline(panel)
        if insight:
            headlines.append({**insight, "source": panel["title"]})
    for geo in maps:
        for insight in geo.get("insights", [])[:1]:
            headlines.append({"kind": "geo", "title": insight["title"], "value": "",
                              "detail": insight["detail"], "source": geo["title"]})

    return {"kpis": (kpis + counts)[:8], "panels": panels, "maps": maps, "headlines": headlines[:8]}


# ---------------------------------------------------------------- geo explorer

def geo_datasets(schema=None):
    """Collections with a country/city field, and their numeric fields."""

    schema = schema or get_schema()
    datasets = []
    for collection, fields in sorted(schema.items()):
        place_field = None
        for field, info in fields.items():
            samples = info.get("sample_values") or []
            if any(lookup(s) for s in samples if isinstance(s, str)):
                place_field = field
                if "country" in field.lower():
                    break
        if not place_field:
            continue
        numeric = [f for f, info in fields.items()
                   if is_numeric(info.get("type")) and not _SKIP_METRIC.search(f)]
        datasets.append({"collection": collection, "place_field": place_field, "numeric_fields": numeric})
    return datasets


def geo_explore(collection, place_field, value_field=None, op="count", schema=None):
    schema = schema or get_schema()
    if collection not in schema or place_field not in schema[collection]:
        raise ValueError("Unknown collection or field.")
    if value_field and (value_field not in schema[collection] or not _FIELD.match(value_field)):
        raise ValueError("Unknown value field.")
    if op not in {"count", "sum", "avg"}:
        raise ValueError("op must be count, sum or avg.")
    accumulator = {"$sum": 1} if op == "count" or not value_field else {f"${op}": f"${value_field}"}
    metric_name = "records" if op == "count" or not value_field else f"{op}_{value_field}"
    rows = _agg(collection, [
        {"$group": {"_id": f"${place_field}", metric_name: accumulator}},
        {"$sort": {metric_name: -1}},
        {"$limit": 250},
    ])
    rows = [{"_id": r["_id"], metric_name: round(float(r[metric_name] or 0), 2)} for r in rows if r["_id"]]
    return build_geo_payload("", rows)
