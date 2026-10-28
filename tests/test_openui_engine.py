"""OpenUI generation safety: sanitizer, grounding check, fallbacks.

Generated or fallback programs are validated with the OFFICIAL OpenUI parser
(@openuidev/lang-core createParser + openuiChatLibrary) through
backend/openui_validator.py.
"""

import pytest

from backend.openui_engine import (
    LineSanitizer,
    fallback_data_ui,
    fallback_message_ui,
    grounding_issues,
    lit,
    system_prompt,
    wrap_prose,
)
from backend.openui_validator import validate


def official(text):
    verdict = validate(text)
    if verdict is None:
        pytest.skip("official OpenUI validator unavailable (node / npm install)")
    return verdict


def feed_all(text, chunk=7):
    sanitizer = LineSanitizer()
    out = "".join(sanitizer.feed(text[i:i + chunk]) for i in range(0, len(text), chunk))
    return sanitizer, out + sanitizer.finish()


def test_system_prompt_is_official_and_forbids_fabrication():
    prompt = system_prompt()
    assert "openui-lang" in prompt
    assert "NEVER invent, estimate or fabricate" in prompt
    assert "generate realistic/plausible data" not in prompt


def test_sanitizer_passes_valid_program_through_streaming_chunks():
    program = (
        'root = Card([h, t])\n'
        'h = CardHeader("Spend", "by type")\n'
        't = Table([Col("Type", ["SaaS", "Hybrid"]), Col("Avg", [1000, 4000], "number")])\n'
    )
    sanitizer, out = feed_all(program)
    assert out == program
    assert sanitizer.has_root and not sanitizer.dropped
    assert official(out)["ok"]


@pytest.mark.parametrize(
    "line,reason",
    [
        ('x = Script("alert(1)")', "unknown component"),
        ('b = Button("Go", @OpenUrl("javascript:alert(1)"))', "blocked url"),
        ('b = Button("Go", @OpenUrl("http://insecure.example"))', "blocked url"),
        ('t = TextContent("<script>alert(1)</script>")', "html tag"),
        ('i = ImageBlock("data:image/svg+xml;base64,AAAA")', "blocked url"),
    ],
)
def test_sanitizer_drops_unsafe_lines(line, reason):
    sanitizer, out = feed_all(f"root = Card([t])\nt = TextContent(\"ok\")\n{line}\n")
    assert line not in out
    assert any(reason in d["reason"] for d in sanitizer.dropped)


def test_sanitizer_keeps_text_mentioning_data_colon():
    sanitizer, out = feed_all('root = Card([t])\nt = TextContent("Raw data: 38 companies")\n')
    assert "Raw data: 38" in out and not sanitizer.dropped


def test_sanitizer_strips_fences_and_keeps_prose_aside():
    sanitizer, out = feed_all('Here is your answer:\n```\nroot = Card([t])\nt = TextContent("hi")\n```\n')
    assert out.startswith("root = Card")
    assert sanitizer.prose == ["Here is your answer:"]


def test_prose_only_output_is_wrapped_safely():
    sanitizer, out = feed_all("Paris is the capital of France.\nIt is lovely.")
    assert out == "" and not sanitizer.has_root
    wrapped = wrap_prose(sanitizer.prose)
    assert official(wrapped)["ok"]


def test_lit_escapes_quotes_and_newlines():
    value = 'He said "drop table"\nnext'
    program = f"root = Card([t])\nt = TextContent({lit(value)})\n"
    assert official(program)["ok"]


RESULT = [{"_id": "Hybrid", "avg": 287128.43}, {"_id": "SaaS", "avg": 211753.9}]


def test_grounding_accepts_values_from_result_and_scaled_forms():
    ui = 'kpi = MetricIndicatorInline("$287,128.43")\nx = BarChart(["Hybrid","SaaS"], [Series("Avg ($k)", [287.1, 211.8])])'
    assert grounding_issues(ui, RESULT) == []


def test_grounding_accepts_shares_of_total():
    share = round(287128.43 / (287128.43 + 211753.9) * 100, 1)
    assert grounding_issues(f'TextContent("Hybrid is {share}% of the total")', RESULT) == []


def test_grounding_flags_invented_numbers():
    issues = grounding_issues('TextContent("Hybrid averages $412,000 across 1,234 companies")', RESULT)
    assert 412000.0 in issues and 1234.0 in issues


@pytest.mark.parametrize(
    "rows",
    [
        RESULT,
        [{"count": 38}],
        [],
        [{"_id": {"country": "India", "type": "SaaS"}, "total": 10.5, "n": 2}, {"_id": {"country": "US", "type": "Hybrid"}, "total": 7, "n": 1}],
        [{"company_name": 'Quote "Co"', "nested": {"a": 1}, "tags": ["x", "y"], "flag": True, "missing": None}],
        [{"label": f"Company with a very long descriptive name {i}", "value": i * 1.5} for i in range(12)],
    ],
)
def test_fallback_data_ui_is_valid_openui(rows):
    program = fallback_data_ui(
        "Average spend?", {"collection": "span_companies", "operation": "aggregate"}, rows,
        note="Verified result", follow_ups=["Show by country"],
    )
    verdict = official(program)
    assert verdict["ok"], verdict


def test_fallback_root_replaces_invalid_generated_root():
    broken = 'root = Card([k])\nk = OverviewCardItem(Text("Hybrid"))\n'
    combined = broken + "\n" + fallback_data_ui("q", None, RESULT)
    assert official(combined)["ok"]


def test_message_ui_is_valid_openui():
    assert official(fallback_message_ui("Title", 'A "quoted" message', "warning", body="More"))["ok"]


def test_positional_slips_are_fixed_without_an_llm_round_trip():
    from backend.openui_engine import LineSanitizer, fix_positional_args
    from backend.openui_validator import validate

    # Shapes taken from real validation failures in logs/requests.jsonl.
    assert fix_positional_args('t1 = Text("Retail")') == ('t1 = Text("text", "Retail")', 1)
    assert fix_positional_args('t1 = Text("number", "12")') == ('t1 = Text("number", "12")', 0)
    assert fix_positional_args("i1 = OverviewCardItem(Text(\"Retail\"))") == (
        'i1 = OverviewCardItem(null, Text("text", "Retail"))', 2)
    assert fix_positional_args('i1 = SnippetCardItem(null, a)')[1] == 0
    assert fix_positional_args('i1 = SnippetCardItem("id-1", a)')[1] == 0
    # Text inside a string literal is content, not a call.
    assert fix_positional_args('c = TextContent("Use Text(\\"x\\") here")')[1] == 0
    # BoldText / TextContent are different components.
    assert fix_positional_args('b = BoldText("x")')[1] == 0

    program = (
        "root = Card([ov])\n"
        "ov = OverviewCardBlock([i1, i2])\n"
        'i1 = OverviewCardItem(Text("Retail"))\n'
        'i2 = OverviewCardItem(Text("Logistics"))\n'
    )
    sanitizer = LineSanitizer()
    sanitizer.feed(program)
    sanitizer.finish()
    assert sanitizer.autofixed == 4
    verdict = validate(sanitizer.text)
    if verdict is not None:  # Node sidecar available
        assert verdict["ok"], verdict["errors"]


def test_follow_up_questions_are_not_grounding_checked():
    from backend.openui_engine import grounding_issues

    rows = [{"_id": "India", "count": 42}]
    ui = (
        'root = Card([t, fu])\nt = TextContent("India has 42 companies.")\n'
        'fu = FollowUpBlock([fu1])\nfu1 = FollowUpItem("What are the top 10 countries by company count?")\n'
    )
    assert grounding_issues(ui, rows) == []
    # A made-up figure in the answer itself is still caught.
    assert grounding_issues(ui.replace("42 companies", "57 companies"), rows) == [57.0]
