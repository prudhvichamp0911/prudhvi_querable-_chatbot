import os
import requests
from dotenv import load_dotenv

from backend.config import settings

load_dotenv()

ROUTES = ("database_query", "browser_task", "general_chat")


def _schema_summary(schema):
    """Short collection/field summary so Jev knows what the data covers."""

    if not schema:
        return ""

    lines = []
    for collection, fields in schema.items():
        names = ", ".join(list(fields)[:12])
        lines.append(f"- {collection}: {names}")

    return "Available VeloDB tables and columns:\n" + "\n".join(lines)


def route_question(question, schema=None, timeout=None):
    url = "https://openrouter.ai/api/alpha/decisions"

    headers = {
        "Authorization": f"Bearer {os.getenv('OPENROUTER_API_KEY')}",
        "Content-Type": "application/json"
    }

    # Without the schema Jev cannot tell that "companies in India" lives in
    # the database, so the collection summary is part of the state.
    state = f"User question: {question}"
    summary = _schema_summary(schema)
    if summary:
        state = f"{state}\n\n{summary}"

    data = {
        "model": settings.jev_model,
        "state": state,
        "questions": {
            "route": {
                "type": "choice",
                "instructions": (
                    "Which path should handle this request? Questions about "
                    "counts, totals, averages, rankings, comparisons or records "
                    "stored in the listed collections need database_query."
                ),
                "criteria": {
                    "database_query": "The user is asking for information that should be retrieved from the VeloDB warehouse.",
                    "browser_task": "The user needs information or an action through a web browser.",
                    "general_chat": "The user is asking a general conversational question that does not require the database or browser."
                }
            }
        }
    }

    response = requests.post(
        url,
        headers=headers,
        json=data,
        timeout=timeout or settings.jev_timeout_seconds,
    )

    response.raise_for_status()

    return response.json()


def interpret_route(result):
    """Extract (route, confidence, cost) from a Jev decision response."""

    answer = (result or {}).get("answers", {}).get("route", {})
    route = answer.get("choice")
    confidence = answer.get("confidence")
    cost = (result or {}).get("usage", {}).get("cost")

    if route not in ROUTES:
        return None, 0.0, cost

    try:
        confidence = float(confidence)
    except (TypeError, ValueError):
        confidence = 0.0

    return route, confidence, cost
