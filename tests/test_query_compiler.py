"""Tests for the MongoDB-contract -> VeloDB SQL compiler.

Two halves:
  * pure compilation tests, which need no database
  * execution tests against the seeded VeloDB test database
"""

import pytest

from backend.query_compiler import CompileError, Compiler, rebuild_rows

COLUMNS = ["company_id", "company_name", "country", "deployment_type",
           "employee_count", "annual_hr_tech_spend_usd", "contact_email"]


@pytest.fixture()
def compiler():
    return Compiler("span_companies", COLUMNS, max_rows=200)


# --- compilation: structure ------------------------------------------

def test_count_with_equality_filter(compiler):
    compiled = compiler.count({"country": "India"})
    assert compiled.sql == (
        "SELECT COUNT(*) AS `count` FROM `span_companies` WHERE `country` = %s")
    assert compiled.params == ["India"]


def test_find_projects_only_requested_columns(compiler):
    compiled = compiler.find({}, ["company_name", "employee_count"])
    assert compiled.sql.startswith("SELECT `company_name`, `employee_count`")
    assert "LIMIT 200" in compiled.sql


def test_find_always_carries_a_limit(compiler):
    assert "LIMIT 200" in compiler.find({}, []).sql


def test_comparison_operators(compiler):
    compiled = compiler.count({"employee_count": {"$gte": 100, "$lt": 1000}})
    assert "`employee_count` >= %s" in compiled.sql
    assert "`employee_count` < %s" in compiled.sql
    assert compiled.params == [100, 1000]


def test_in_operator_expands_placeholders(compiler):
    compiled = compiler.count({"country": {"$in": ["India", "Germany", "France"]}})
    assert "`country` IN (%s, %s, %s)" in compiled.sql
    assert compiled.params == ["India", "Germany", "France"]


def test_empty_in_list_matches_nothing(compiler):
    assert "1 = 0" in compiler.count({"country": {"$in": []}}).sql


def test_ne_also_matches_null_like_mongo(compiler):
    """Mongo's $ne matches missing fields; SQL's <> does not match NULL."""
    compiled = compiler.count({"country": {"$ne": "India"}})
    assert "`country` IS NULL OR `country` <> %s" in compiled.sql


def test_or_combines_conditions(compiler):
    compiled = compiler.count({"$or": [{"country": "India"}, {"country": "France"}]})
    assert " OR " in compiled.sql
    assert compiled.params == ["India", "France"]


def test_regex_case_insensitive_lowers_both_sides(compiler):
    compiled = compiler.count({"company_name": {"$regex": "ALPHA", "$options": "i"}})
    assert "LOWER(`company_name`) REGEXP %s" in compiled.sql
    assert compiled.params == ["alpha"]


def test_exists_becomes_a_null_check(compiler):
    assert "IS NOT NULL" in compiler.count({"contact_email": {"$exists": True}}).sql
    assert "IS NULL" in compiler.count({"contact_email": {"$exists": False}}).sql


# --- compilation: aggregation ----------------------------------------

def test_group_by_single_field_keeps_the_id_alias(compiler):
    compiled = compiler.aggregate([
        {"$group": {"_id": "$country", "total": {"$sum": "$annual_hr_tech_spend_usd"}}},
        {"$sort": {"total": -1}}, {"$limit": 5}])
    assert "`country` AS `_id`" in compiled.sql
    assert "SUM(`annual_hr_tech_spend_usd`) AS `total`" in compiled.sql
    assert "GROUP BY `country`" in compiled.sql
    assert "ORDER BY `total` DESC" in compiled.sql
    assert "LIMIT 5" in compiled.sql


def test_group_count_uses_sum_one(compiler):
    compiled = compiler.aggregate([{"$group": {"_id": "$country", "n": {"$sum": 1}}}])
    assert "COUNT(*) AS `n`" in compiled.sql


def test_match_before_group_becomes_where(compiler):
    compiled = compiler.aggregate([
        {"$match": {"country": "India"}},
        {"$group": {"_id": "$deployment_type", "n": {"$sum": 1}}}])
    assert "WHERE" in compiled.sql and compiled.params == ["India"]
    assert compiled.sql.index("WHERE") < compiled.sql.index("GROUP BY")


def test_composite_group_key_is_flagged_for_rebuild(compiler):
    compiled = compiler.aggregate([
        {"$group": {"_id": {"a": "$country", "b": "$deployment_type"},
                    "n": {"$sum": 1}}}])
    assert compiled.composite_id == ["a", "b"]
    assert "GROUP BY `country`, `deployment_type`" in compiled.sql


def test_dotted_sort_key_resolves_to_the_group_alias(compiler):
    compiled = compiler.aggregate([
        {"$group": {"_id": {"year": "$employee_count"}, "n": {"$sum": 1}}},
        {"$sort": {"_id.year": 1}}])
    assert "ORDER BY `year` ASC" in compiled.sql


def test_limit_is_capped_at_max_rows():
    small = Compiler("span_companies", COLUMNS, max_rows=10)
    compiled = small.aggregate([{"$group": {"_id": "$country", "n": {"$sum": 1}}},
                                {"$limit": 5000}])
    assert "LIMIT 10" in compiled.sql


# --- compilation: rejection ------------------------------------------

def test_unknown_column_is_rejected(compiler):
    with pytest.raises(CompileError, match="unknown column"):
        compiler.count({"salary": 1})


def test_unknown_column_in_group_is_rejected(compiler):
    with pytest.raises(CompileError):
        compiler.aggregate([{"$group": {"_id": "$nope", "n": {"$sum": 1}}}])


@pytest.mark.parametrize("stage", ["$unwind", "$facet", "$lookup", "$out", "$merge"])
def test_unsupported_stages_are_rejected(compiler, stage):
    with pytest.raises(CompileError, match="not supported"):
        compiler.aggregate([{stage: {}}])


def test_injection_in_a_column_name_cannot_escape(compiler):
    """A column name is never interpolated unless the catalog contains it."""
    with pytest.raises(CompileError):
        compiler.count({"country`; DROP TABLE span_companies; --": "x"})


def test_injection_in_a_value_stays_a_bound_parameter(compiler):
    compiled = compiler.count({"country": "'; DROP TABLE span_companies; --"})
    assert "DROP" not in compiled.sql
    assert compiled.params == ["'; DROP TABLE span_companies; --"]


def test_unsupported_accumulator_is_rejected(compiler):
    with pytest.raises(CompileError, match="not supported"):
        compiler.aggregate([{"$group": {"_id": "$country", "x": {"$push": "$country"}}}])


def test_empty_pipeline_is_rejected(compiler):
    with pytest.raises(CompileError):
        compiler.aggregate([])


# --- rebuild ----------------------------------------------------------

def test_rebuild_nests_composite_keys_back_under_id(compiler):
    compiled = compiler.aggregate([
        {"$group": {"_id": {"year": "$employee_count"}, "value": {"$sum": 1}}}])
    rows = rebuild_rows([{"year": 2024, "value": 7}], compiled)
    assert rows == [{"_id": {"year": 2024}, "value": 7}]


def test_rebuild_leaves_scalar_group_rows_untouched(compiler):
    compiled = compiler.aggregate([{"$group": {"_id": "$country", "n": {"$sum": 1}}}])
    rows = [{"_id": "India", "n": 2}]
    assert rebuild_rows(rows, compiled) == rows


# --- execution against the seeded test warehouse ----------------------

def test_count_runs_against_velodb(mongo):
    from backend.database_tool import run_database_query

    result = run_database_query(
        {"collection": "span_companies", "operation": "count",
         "filters": {"country": "India"}})
    assert result == [{"count": 2}]


def test_aggregate_runs_against_velodb(mongo):
    from backend.database_tool import run_database_query

    rows = run_database_query({
        "collection": "span_companies", "operation": "aggregate",
        "pipeline": [{"$group": {"_id": "$deployment_type",
                                 "total": {"$sum": "$annual_hr_tech_spend_usd"}}},
                     {"$sort": {"total": -1}}]})
    assert {row["_id"] for row in rows} == {"Hybrid", "SaaS"}
    totals = {row["_id"]: row["total"] for row in rows}
    assert totals["Hybrid"] == 8000.0      # Beta 3000 + Gamma 5000
    assert totals["SaaS"] == 1000.0        # Alpha
    assert all(isinstance(row["total"], float) for row in rows)


def test_distinct_runs_against_velodb(mongo):
    from backend.database_tool import run_database_query

    rows = run_database_query(
        {"collection": "span_companies", "operation": "distinct", "field": "country"})
    assert {row["value"] for row in rows} == {"India", "United States"}


def test_write_attempt_is_refused_by_the_client(mongo):
    from backend import velodb

    with pytest.raises(velodb.ReadOnlyViolation):
        velodb.query("DELETE FROM span_companies")
    with pytest.raises(velodb.ReadOnlyViolation):
        velodb.query("SELECT 1; DROP TABLE span_companies")


def test_non_queryable_table_is_refused(mongo):
    from backend.database_tool import run_database_query

    with pytest.raises(CompileError):
        run_database_query({"collection": "app_users", "operation": "count"})
