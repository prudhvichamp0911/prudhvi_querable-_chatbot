"""OpenUI Lang generation, validation and fallbacks.

The browser renders assistant messages with the official OpenUI renderer
(``openuiChatLibrary`` from ``@openuidev/react-ui``). This module produces
those messages on the server:

1. ``stream_openui`` asks an LLM for OpenUI Lang using the official system
   prompt generated from the same library (``backend/openui/``). The provider
   is OpenRouter by default or the Thesys OpenUI Gateway when configured.
2. ``LineSanitizer`` validates the stream statement by statement before
   anything reaches the browser: unknown components, non-https URLs,
   ``javascript:`` and prose are dropped.
3. ``grounding_issues`` checks that numbers in a data answer come from the
   VeloDB result.
4. ``fallback_*`` builders produce deterministic OpenUI Lang from real data
   when the model fails, is unavailable, or its output is not grounded.
   Appending a new ``root = ...`` statement replaces an earlier one, because
   the OpenUI parser keeps the last definition of a name.
"""

import json
import math
import re
import time
from pathlib import Path

import httpx

from backend.config import openrouter_speed_options, settings
from backend.observability import logger, record_llm

ASSET_DIR = Path(__file__).resolve().parent / "openui"

MAX_OUTPUT_CHARS = 60_000
MAX_RESULT_CHARS_FOR_LLM = 14_000


class OpenUIUnavailable(RuntimeError):
    """No OpenUI generation provider is configured or reachable."""


# --------------------------------------------------
# Assets generated from the frontend component library
# --------------------------------------------------

_assets = {}


def _load_assets():
    if not _assets:
        prompt_path = ASSET_DIR / "system_prompt.txt"
        library_path = ASSET_DIR / "library.json"
        if not prompt_path.exists() or not library_path.exists():
            raise OpenUIUnavailable(
                "OpenUI assets are missing. Run `npm run openui:assets` in openui_test/."
            )
        _assets["prompt"] = prompt_path.read_text(encoding="utf-8")
        library = json.loads(library_path.read_text(encoding="utf-8"))
        _assets["components"] = frozenset(library["components"])
    return _assets


def system_prompt():
    return _load_assets()["prompt"]


def allowed_components():
    return _load_assets()["components"]


# --------------------------------------------------
# Escaping helpers for building OpenUI Lang
# --------------------------------------------------

def lit(value):
    """Encode a Python value as an OpenUI Lang literal."""

    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        if isinstance(value, float) and not math.isfinite(value):
            return "null"
        return json.dumps(value)
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(lit(item) for item in value) + "]"
    if isinstance(value, dict):
        return "{" + ", ".join(f"{_key(k)}: {lit(v)}" for k, v in value.items()) + "}"
    return json.dumps(str(value), ensure_ascii=False)


def _key(name):
    name = str(name)
    return name if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name) else json.dumps(name)


# --------------------------------------------------
# Stream sanitizer
# --------------------------------------------------

STRING_RE = re.compile(r'"(?:[^"\\]|\\.)*"')
STATEMENT_RE = re.compile(r"^\s*\$?[A-Za-z_][A-Za-z0-9_]*\s*=")
COMPONENT_CALL_RE = re.compile(r"(?<![@\w.$])([A-Z][A-Za-z0-9]*)\s*\(")
URL_RE = re.compile(
    r"\b(?:https?://|javascript:|vbscript:|data:[a-z]+/|file://)[^\s\"')]*",
    re.IGNORECASE,
)
BUILTIN_CALLS = frozenset({"Action"})


def _strip_strings(line):
    return STRING_RE.sub('""', line)


TEXT_VARIANTS = ('"text"', '"number"')
POSITIONAL_FIX_RE = re.compile(
    r"(?<![@\w.$])(Text|SnippetCardItem|OverviewCardItem|CompositeCardItem)\s*\(\s*"
)


def fix_positional_args(line):
    """Repair the two positional slips the model makes most often.

    * ``Text("Retail")`` skips the leading variant: becomes
      ``Text("text", "Retail")``.
    * ``OverviewCardItem(Text(...))`` (and the Snippet/Composite items)
      skips the leading optional id: becomes ``OverviewCardItem(null, ...)``.

    Both are rejected by the official parser and used to cost a full LLM
    repair round trip. Calls inside string literals are left alone.
    Returns ``(line, number_of_fixes)``.
    """

    strings = [match.span() for match in STRING_RE.finditer(line)]
    pieces, last, fixes = [], 0, 0
    for match in POSITIONAL_FIX_RE.finditer(line):
        if any(start <= match.start() < end for start, end in strings):
            continue
        name, args_at = match.group(1), match.end()
        rest = line[args_at:]
        if not rest.strip():
            continue  # arguments continue on the next line; leave as written
        if name == "Text":
            literal = STRING_RE.match(rest)
            if not literal or literal.group(0) in TEXT_VARIANTS:
                continue
            insert = '"text", '
        else:
            if rest.startswith(('"', "null", ")")):
                continue
            insert = "null, "
        pieces += [line[last:args_at], insert]
        last = args_at
        fixes += 1
    pieces.append(line[last:])
    return "".join(pieces), fixes


def _bracket_delta(line):
    code = _strip_strings(line)
    return sum(code.count(c) for c in "([{") - sum(code.count(c) for c in ")]}")


class LineSanitizer:
    """Validate OpenUI Lang line by line while it streams.

    ``feed`` returns the text that is safe to forward; ``finish`` flushes the
    last line. Dropped lines are recorded in ``dropped`` for logging/tests.
    """

    def __init__(self, components=None):
        self.components = components or allowed_components()
        self.buffer = ""
        self.depth = 0
        self.dropped = []
        self.prose = []
        self.emitted = []
        self.total_chars = 0
        self.truncated = False
        self.autofixed = 0

    def feed(self, chunk):
        if self.truncated:
            return ""
        self.buffer += chunk
        self.total_chars += len(chunk)
        if self.total_chars > MAX_OUTPUT_CHARS:
            self.truncated = True
            self.buffer = ""
            return ""
        out = []
        while "\n" in self.buffer:
            line, self.buffer = self.buffer.split("\n", 1)
            accepted = self._check(line)
            if accepted is not None:
                out.append(accepted + "\n")
        return "".join(out)

    def finish(self):
        if self.buffer and not self.truncated:
            line, self.buffer = self.buffer, ""
            accepted = self._check(line)
            if accepted is not None:
                return accepted + "\n"
        return ""

    def _check(self, line):
        stripped = line.strip()

        if not stripped:
            return None if self.depth == 0 else line

        if stripped.startswith("```"):
            return None

        is_statement = STATEMENT_RE.match(line) is not None

        if self.depth == 0 and not is_statement:
            # The model wrote prose instead of OpenUI Lang. Keep it aside so
            # it can be shown safely as text if no UI was produced.
            self.prose.append(stripped)
            return None

        line, fixes = fix_positional_args(line)
        self.autofixed += fixes

        reason = self._violation(line)
        if reason:
            self.dropped.append({"line": stripped[:200], "reason": reason})
            # Keep bracket balance consistent even for a dropped line.
            self.depth = max(0, self.depth + _bracket_delta(line))
            return None

        self.depth = max(0, self.depth + _bracket_delta(line))
        self.emitted.append(line)
        return line

    def _violation(self, line):
        code = _strip_strings(line)
        for name in COMPONENT_CALL_RE.findall(code):
            if name not in self.components and name not in BUILTIN_CALLS:
                return f"unknown component {name}"

        for match in URL_RE.finditer(line):
            url = match.group(0)
            if not url.lower().startswith("https://"):
                return f"blocked url scheme in {url[:40]}"

        if re.search(r"<\s*/?\s*(script|iframe|object|embed|style)\b", line, re.IGNORECASE):
            return "html tag"

        return None

    @property
    def text(self):
        return "\n".join(self.emitted)

    @property
    def has_root(self):
        return any(re.match(r"^\s*root\s*=\s*Card\s*\(", line) for line in self.emitted)


# --------------------------------------------------
# Grounding check for database answers
# --------------------------------------------------

NUMBER_RE = re.compile(r"(?<![A-Za-z_\d.])-?\d[\d,]*(?:\.\d+)?")


def _numbers_in(value, out):
    if isinstance(value, bool):
        return
    if isinstance(value, (int, float)):
        if math.isfinite(value):
            out.append(float(value))
    elif isinstance(value, str):
        for match in NUMBER_RE.findall(value):
            try:
                out.append(float(match.replace(",", "")))
            except ValueError:
                pass
    elif isinstance(value, dict):
        for item in value.values():
            _numbers_in(item, out)
    elif isinstance(value, list):
        for item in value:
            _numbers_in(item, out)


def allowed_numbers(result, question=""):
    """Numbers a grounded answer may contain, including common derivations."""

    base = []
    _numbers_in(result, base)
    _numbers_in(question, base)

    derived = set()
    rows = result if isinstance(result, list) else [result]
    derived.add(float(len(rows)))

    # Column totals, means and shares of total are common, legitimate
    # derivations when presenting grouped results.
    columns = {}
    for row in rows:
        if isinstance(row, dict):
            for key, value in row.items():
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    columns.setdefault(key, []).append(float(value))
    for values in columns.values():
        total = sum(values)
        derived.update({total, total / len(values), max(values), min(values)})
        if total:
            derived.update(v / total * 100 for v in values)
        if len(values) == 2 and values[1]:
            derived.add(values[0] - values[1])
            derived.add(abs(values[0] / values[1] - 1) * 100)

    allowed = set()
    for number in list(base) + list(derived):
        for scale in (1, 1e3, 1e6, 1e9, 0.01):
            allowed.add(number / scale)
    return allowed


def _is_close(value, allowed):
    for candidate in allowed:
        tolerance = max(0.051, abs(candidate) * 0.006)
        if abs(value - candidate) <= tolerance:
            return True
    return False


# Suggested follow-up questions ("What are the top 10 ...?") are not claims
# about the data, so their text is not grounding-checked.
FOLLOW_UP_TEXT_RE = re.compile(r'(FollowUpItem\(\s*)"(?:[^"\\]|\\.)*"')


def grounding_issues(openui_text, result, question=""):
    """Return numbers in the UI that do not trace back to the data."""

    allowed = allowed_numbers(result, question)
    checked_text = FOLLOW_UP_TEXT_RE.sub(r'\1""', openui_text)
    found = []
    for match in NUMBER_RE.findall(checked_text):
        try:
            value = float(match.replace(",", ""))
        except ValueError:
            continue
        # Small integers are layout values (sizes, ranks, list positions).
        if abs(value) < 10 and float(value).is_integer():
            continue
        found.append(value)

    return sorted({value for value in found if not _is_close(value, allowed)})


# --------------------------------------------------
# Deterministic fallbacks
# --------------------------------------------------

def _flatten_row(row):
    if not isinstance(row, dict):
        return {"value": row}
    flat = {}
    for key, value in row.items():
        if key == "_id" and isinstance(value, dict):
            for sub_key, sub_value in value.items():
                flat[sub_key] = sub_value
        elif key == "_id":
            flat["group" if value is not None else "_id"] = value
        elif isinstance(value, dict):
            for sub_key, sub_value in value.items():
                flat[f"{key}.{sub_key}"] = sub_value
        else:
            flat[key] = value
    return flat


def _cell(value):
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, (int, float)):
        return round(value, 2) if isinstance(value, float) else value
    if value is None:
        return ""
    if isinstance(value, (list, dict)):
        return json.dumps(value, default=str, ensure_ascii=False)[:120]
    return str(value)[:200]


def _is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _label(key):
    return str(key).replace("_", " ").replace(".", " ").strip().title()


def _format_number(value):
    if isinstance(value, float) and not value.is_integer():
        return f"{value:,.2f}"
    return f"{int(value):,}"


def fallback_data_ui(question, query, rows, note=None, follow_ups=None):
    """Build an OpenUI Card from real VeloDB rows without an LLM."""

    rows = rows if isinstance(rows, list) else [rows]
    flat = [_flatten_row(row) for row in rows][: settings.max_result_rows]
    lines = []
    children = ["fb_header"]

    lines.append(
        f"fb_header = CardHeader({lit('Database result')}, {lit(question[:140])})"
    )

    if not flat:
        children.append("fb_empty")
        lines.append(
            f"fb_empty = Callout(\"info\", {lit('No matching records')}, "
            f"{lit('The query ran successfully but returned no rows.')})"
        )
    else:
        columns = []
        for row in flat:
            for key in row:
                if key not in columns:
                    columns.append(key)
        columns = columns[:8]

        numeric = [c for c in columns if all(_is_number(r.get(c)) for r in flat if r.get(c) is not None) and any(_is_number(r.get(c)) for r in flat)]
        labels = [c for c in columns if c not in numeric]

        if len(flat) == 1:
            row = flat[0]
            entries = [
                {"left": _label(key), "right": _format_number(row[key]) if _is_number(row.get(key)) else str(_cell(row.get(key))), "rightVariant": "number" if _is_number(row.get(key)) else "text"}
                for key in columns
            ]
            children.append("fb_values")
            lines.append(f"fb_values = EntityList({lit(entries)}, \"default\")")
        else:
            if numeric and labels and 2 <= len(flat) <= 30:
                label_col = labels[0]
                chart_labels = [str(_cell(row.get(label_col))) or "(none)" for row in flat]
                series_names = []
                for index, col in enumerate(numeric[:3]):
                    name = f"fb_series{index}"
                    series_names.append(name)
                    values = [row.get(col) if _is_number(row.get(col)) else 0 for row in flat]
                    lines.append(f"{name} = Series({lit(_label(col))}, {lit(values)})")
                chart = "HorizontalBarChart" if max(len(l) for l in chart_labels) > 14 else "BarChart"
                children.append("fb_chart")
                lines.append(
                    f"fb_chart = {chart}({lit(chart_labels)}, [{', '.join(series_names)}], "
                    f"\"grouped\", {lit(_label(label_col))}, {lit(_label(numeric[0]))})"
                )

            col_names = []
            for index, col in enumerate(columns):
                name = f"fb_col{index}"
                col_names.append(name)
                values = [_cell(row.get(col)) for row in flat]
                kind = "number" if col in numeric else "string"
                if kind == "number":
                    values = [v if _is_number(v) else 0 for v in values]
                else:
                    values = [str(v) for v in values]
                lines.append(f"{name} = Col({lit(_label(col))}, {lit(values)}, \"{kind}\")")
            children.append("fb_table")
            lines.append(f"fb_table = Table([{', '.join(col_names)}])")

    if note:
        children.append("fb_note")
        lines.append(f"fb_note = TextCallout(\"neutral\", {lit('Note')}, {lit(note)})")

    if query:
        children.append("fb_details")
        lines.append("fb_details = Accordion([fb_query])")
        lines.append(
            f"fb_query = AccordionItem(\"query\", {lit('How this was calculated')}, [fb_code])"
        )
        lines.append(
            f"fb_code = CodeBlock(\"json\", {lit(json.dumps(query, indent=2, default=str))})"
        )

    if follow_ups:
        names = []
        for index, text in enumerate(follow_ups[:3]):
            names.append(f"fb_fu{index}")
            lines.append(f"fb_fu{index} = FollowUpItem({lit(text)})")
        children.append("fb_followups")
        lines.append(f"fb_followups = FollowUpBlock([{', '.join(names)}])")

    return "\n".join([f"root = Card([{', '.join(children)}])"] + lines) + "\n"


def fallback_message_ui(title, message, variant="info", body=None):
    """A small Card for notices, refusals and errors."""

    children = ["fb_notice"]
    lines = [f"fb_notice = Callout({lit(variant)}, {lit(title)}, {lit(message)})"]
    if body:
        children.append("fb_body")
        lines.append(f"fb_body = TextContent({lit(body)})")
    return "\n".join([f"root = Card([{', '.join(children)}])"] + lines) + "\n"


def wrap_prose(prose):
    """Present plain-text model output safely when no UI was produced."""

    text = "\n".join(prose).strip()
    return "root = Card([fb_text])\nfb_text = TextContent(" + lit(text[:8000]) + ")\n"


# --------------------------------------------------
# Prompts
# --------------------------------------------------

# The positional-argument slips the model makes most often (from the
# validation problems in logs/requests.jsonl). Each one used to cost a full
# repair round trip, so the correct forms are spelled out up front.
POSITIONAL_REMINDERS = """Positional-argument reminders (arguments are positional; pass null for skipped optional ones):
- Text(variant, value, ...): the FIRST argument is "text" or "number", the value comes second.
  Right: Text("text", "Hybrid")   Right: Text("number", "1,234")   Wrong: Text("Hybrid")
- SnippetCardItem / OverviewCardItem / ContextCardItem / CompositeCardItem start with an optional id STRING.
  Pass null (or a short string id) first. Right: OverviewCardItem(null, Text("text", "SaaS"))   Wrong: OverviewCardItem(Text("text", "SaaS"))"""


def data_messages(question, query, result, history=None, truncated=False):
    rows = result if isinstance(result, list) else [result]
    payload = json.dumps(rows, default=str, ensure_ascii=False)
    shown = len(rows)
    while len(payload) > MAX_RESULT_CHARS_FOR_LLM and shown > 1:
        shown = max(1, shown // 2)
        payload = json.dumps(rows[:shown], default=str, ensure_ascii=False)
        truncated = True

    content = f"""USER QUESTION:
{question}

The question was answered by running this validated, read-only VeloDB query:
{json.dumps(query, default=str)}

DATABASE RESULT ({shown} of {len(rows)} rows{', result truncated' if truncated else ''}):
<<<DATABASE RESULT
{payload}
DATABASE RESULT>>>

Present this result as OpenUI Lang:
- Answer the question directly in the first lines (CardHeader plus a short TextContent).
- Use KPI cards for headline numbers, a chart for comparisons or groups, and a Table with the exact rows.
- Use ONLY values from the DATABASE RESULT. Do not invent rows, totals or percentages.
- Round displayed decimals to at most 2 places (e.g. 287128.43) and format money with a currency symbol in text.
- If the result cannot fully answer the question, say what is missing.
- End with a FollowUpBlock of 2-3 useful follow-up questions about this data.

{POSITIONAL_REMINDERS}
"""
    return _with_history(history) + [{"role": "user", "content": content}]


def general_messages(question, history=None, extra_context=None, browser=False):
    notes = []
    if browser:
        notes.append(
            "This deployment has no live web browsing. If the request needs current "
            "web information, say so plainly and help with what you know."
        )
    notes.append(
        "Do not claim to have queried the user's database. If the question needs "
        "stored business records, suggest asking it as a data question."
    )
    if extra_context:
        notes.append(f"Relevant context from the knowledge graph:\n{extra_context}")

    content = question + "\n\n(" + " ".join(notes) + ")\n\n" + POSITIONAL_REMINDERS
    return _with_history(history) + [{"role": "user", "content": content}]


def repair_messages(program, problems, original_messages):
    """Ask for a corrected program, given the official parser's errors."""

    request = original_messages[-1]["content"] if original_messages else ""
    listed = "\n".join("- " + p for p in problems[:15])
    content = (
        "Your previous OpenUI Lang response has problems. Fix ALL of them.\n\n"
        f"PROBLEMS:\n{listed}\n\n"
        f"ORIGINAL REQUEST:\n{request[:MAX_RESULT_CHARS_FOR_LLM]}\n\n"
        f"PREVIOUS RESPONSE:\n{program[:20000]}\n\n"
        "Return the complete corrected OpenUI Lang program only, starting with root = Card(...).\n"
        "Arguments are positional: pass every argument up to the last one you use, in signature "
        "order, using null for optional arguments you skip. Keep every value exactly as it "
        "appears in the data."
    )
    return [{"role": "system", "content": system_prompt()}, {"role": "user", "content": content}]


def _with_history(history):
    messages = [{"role": "system", "content": system_prompt()}]
    for item in (history or [])[-8:]:
        role = item.get("role")
        text = item.get("content")
        if role in {"user", "assistant"} and isinstance(text, str) and text.strip():
            messages.append({"role": role, "content": text[:3000]})
    return messages


# --------------------------------------------------
# Streaming providers
# --------------------------------------------------

def _providers(model_override=None):
    providers = []
    if settings.openui_provider == "thesys" and settings.thesys_api_key:
        providers.append(
            ("thesys", settings.thesys_base_url, settings.thesys_api_key, settings.thesys_model)
        )
    if settings.openrouter_api_key:
        providers.append(
            (
                "openrouter",
                settings.openrouter_base_url,
                settings.openrouter_api_key,
                model_override or settings.openui_model,
            )
        )
    return providers


async def stream_openui(messages, model_override=None, stage="openui generation"):
    """Yield OpenUI Lang text chunks from the first working provider."""

    providers = _providers(model_override)
    if not providers:
        raise OpenUIUnavailable(
            "No OpenUI generation provider is configured (set OPENROUTER_API_KEY "
            "or OPENUI_PROVIDER=thesys with THESYS_API_KEY)."
        )

    last_error = None
    for name, base_url, api_key, model in providers:
        started = time.perf_counter()
        usage = {}
        produced = False
        try:
            body = {
                "model": model,
                "messages": messages,
                "stream": True,
                "temperature": 0.2,
            }
            if name == "openrouter":
                body["usage"] = {"include": True}
                body.update(openrouter_speed_options())
            headers = {"Authorization": f"Bearer {api_key}"}
            if name == "openrouter":
                headers["X-Title"] = "Queryable Chatbot"

            timeout = httpx.Timeout(settings.llm_timeout_seconds, connect=10)
            async with httpx.AsyncClient(timeout=timeout) as client:
                async with client.stream(
                    "POST", f"{base_url.rstrip('/')}/chat/completions", json=body, headers=headers
                ) as response:
                    if response.status_code >= 400:
                        detail = (await response.aread()).decode("utf-8", "replace")[:300]
                        raise OpenUIUnavailable(f"{name} returned {response.status_code}: {detail}")

                    async for line in response.aiter_lines():
                        if not line.startswith("data:"):
                            continue
                        data = line[5:].strip()
                        if not data or data == "[DONE]":
                            continue
                        try:
                            event = json.loads(data)
                        except json.JSONDecodeError:
                            continue
                        if event.get("error"):
                            raise OpenUIUnavailable(f"{name} stream error: {event['error']}")
                        if event.get("usage"):
                            usage = event["usage"]
                        for choice in event.get("choices") or []:
                            delta = (choice.get("delta") or {}).get("content")
                            if delta:
                                produced = True
                                yield delta

            record_llm(
                f"{stage} ({name})",
                model,
                time.perf_counter() - started,
                input_tokens=usage.get("prompt_tokens"),
                output_tokens=usage.get("completion_tokens"),
                cost=usage.get("cost"),
            )
            return
        except (httpx.HTTPError, OpenUIUnavailable) as error:
            last_error = error
            logger.warning("OpenUI provider %s failed: %s", name, error)
            record_llm(f"{stage} ({name}) failed", model, time.perf_counter() - started)
            if produced:
                # Part of the answer was already streamed; do not mix providers.
                raise OpenUIUnavailable(str(error)) from error

    raise OpenUIUnavailable(str(last_error))
