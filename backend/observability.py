"""Request tracing, token/cost tracking and latency metrics.

Every chat request gets a trace (a context variable) that collects the
stages it ran: Jev routing, LLM calls, the VeloDB tool and OpenUI
generation. When the request finishes the trace is:

* appended to ``logs/requests.jsonl`` (secrets and raw results excluded),
* added to in-memory metrics used by ``GET /api/metrics`` (p50/p95), and
* sent to Langfuse when LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY are set.
"""

import contextvars
import json
import logging
import os
import statistics
import threading
import time
import uuid
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

import httpx

from backend.config import settings

logger = logging.getLogger("queryable")
if not logger.handlers:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

LOG_DIR = Path(os.getenv("QUERYABLE_LOG_DIR") or Path(__file__).resolve().parent.parent / "logs")
REQUEST_LOG = LOG_DIR / "requests.jsonl"

_current_trace = contextvars.ContextVar("queryable_trace", default=None)
_lock = threading.Lock()
_recent = deque(maxlen=500)


class Trace:
    def __init__(self, user, question, thread_id=None):
        self.id = str(uuid.uuid4())
        self.user = user
        self.thread_id = thread_id
        self.question_chars = len(question or "")
        self.started = time.perf_counter()
        self.started_at = datetime.now(timezone.utc).isoformat()
        self.route = None
        self.route_source = None
        self.status = "ok"
        self.error = None
        self.spans = []
        self.fallback_used = False
        self.repaired = False

    def span(self, name, latency, **data):
        self.spans.append({"name": name, "latency_s": round(latency, 3), **data})

    @property
    def tokens(self):
        return sum(
            (s.get("input_tokens") or 0) + (s.get("output_tokens") or 0)
            for s in self.spans
        )

    @property
    def cost(self):
        return round(sum(s.get("cost") or 0 for s in self.spans), 6)

    def summary(self):
        return {
            "trace_id": self.id,
            "at": self.started_at,
            "user": self.user,
            "thread_id": self.thread_id,
            "route": self.route,
            "route_source": self.route_source,
            "status": self.status,
            "error": self.error,
            "fallback_used": self.fallback_used,
            "repaired": self.repaired,
            "latency_s": round(time.perf_counter() - self.started, 3),
            "total_tokens": self.tokens,
            "cost_usd": self.cost,
            "spans": self.spans,
            "question_chars": self.question_chars,
        }


def start_trace(user, question, thread_id=None):
    trace = Trace(user, question, thread_id)
    _current_trace.set(trace)
    return trace


def current_trace():
    return _current_trace.get()


def record_llm(stage, model, latency, input_tokens=None, output_tokens=None, cost=None):
    """Called by every LLM wrapper; safe to call outside a request."""

    trace = current_trace()
    if trace is not None:
        trace.span(
            stage,
            latency,
            kind="llm",
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost=cost,
        )


def record_span(name, latency, **data):
    trace = current_trace()
    if trace is not None:
        trace.span(name, latency, **data)


def finish_trace(trace):
    summary = trace.summary()

    with _lock:
        _recent.append(summary)

    try:
        LOG_DIR.mkdir(exist_ok=True)
        with REQUEST_LOG.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(summary, default=str) + "\n")
    except OSError as error:
        logger.warning("could not write request log: %s", error)

    logger.info(
        "chat trace=%s route=%s status=%s latency=%.2fs tokens=%s cost=%s",
        summary["trace_id"],
        summary["route"],
        summary["status"],
        summary["latency_s"],
        summary["total_tokens"],
        summary["cost_usd"],
    )

    if settings.langfuse_public_key and settings.langfuse_secret_key:
        threading.Thread(target=_send_langfuse, args=(summary,), daemon=True).start()

    return summary


def _percentile(values, pct):
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, round(pct / 100 * (len(ordered) - 1))))
    return round(ordered[index], 3)


def metrics_snapshot():
    with _lock:
        items = list(_recent)

    latencies = [item["latency_s"] for item in items]
    by_route = {}
    for item in items:
        by_route.setdefault(item["route"] or "unknown", 0)
        by_route[item["route"] or "unknown"] += 1

    return {
        "requests": len(items),
        "errors": sum(1 for item in items if item["status"] != "ok"),
        "fallbacks": sum(1 for item in items if item["fallback_used"]),
        "latency_p50_s": _percentile(latencies, 50),
        "latency_p95_s": _percentile(latencies, 95),
        "latency_mean_s": round(statistics.mean(latencies), 3) if latencies else None,
        "total_tokens": sum(item["total_tokens"] for item in items),
        "total_cost_usd": round(sum(item["cost_usd"] for item in items), 6),
        "by_route": by_route,
        "langfuse_enabled": bool(
            settings.langfuse_public_key and settings.langfuse_secret_key
        ),
    }


def _send_langfuse(summary):
    """Send one trace with its generations to the Langfuse ingestion API."""

    now = datetime.now(timezone.utc).isoformat()
    batch = [
        {
            "id": str(uuid.uuid4()),
            "type": "trace-create",
            "timestamp": now,
            "body": {
                "id": summary["trace_id"],
                "name": "queryable-chat",
                "userId": summary["user"],
                "sessionId": summary["thread_id"],
                "metadata": {
                    "route": summary["route"],
                    "status": summary["status"],
                    "latency_s": summary["latency_s"],
                },
            },
        }
    ]

    for span in summary["spans"]:
        if span.get("kind") != "llm":
            continue
        batch.append(
            {
                "id": str(uuid.uuid4()),
                "type": "generation-create",
                "timestamp": now,
                "body": {
                    "traceId": summary["trace_id"],
                    "name": span["name"],
                    "model": span.get("model"),
                    "usage": {
                        "input": span.get("input_tokens"),
                        "output": span.get("output_tokens"),
                        "unit": "TOKENS",
                    },
                    "metadata": {"latency_s": span["latency_s"], "cost": span.get("cost")},
                },
            }
        )

    try:
        httpx.post(
            f"{settings.langfuse_host.rstrip('/')}/api/public/ingestion",
            auth=(settings.langfuse_public_key, settings.langfuse_secret_key),
            json={"batch": batch},
            timeout=10,
        )
    except httpx.HTTPError as error:
        logger.warning("langfuse export failed: %s", error)
