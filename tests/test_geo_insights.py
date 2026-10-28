"""Geographic analysis and deterministic insights (no LLM, no network)."""

from backend.geo import build_geo_payload, places_in_text, query_hints, regions_in_text
from backend.insights import result_insights


def names(payload):
    return [place["name"] for place in payload["places"]]


def test_grouped_rows_map_every_country_with_its_value():
    rows = [{"_id": "United States", "count": 176}, {"_id": "UK", "count": 63}, {"_id": "Singapore", "count": 24}]
    geo = build_geo_payload("companies per country", rows)
    assert geo["source"] == "database"
    assert names(geo) == ["United States", "United Kingdom", "Singapore"]
    assert [p["id"] for p in geo["places"]] == ["840", "826", "702"]
    assert geo["places"][0]["value"] == 176
    assert geo["total"] == 263
    assert geo["insights"][0]["title"] == "United States leads"


def test_which_country_does_a_record_belong_to():
    rows = [{"company_name": "Professional Services Company 001", "country": "United States"}]
    geo = build_geo_payload("Which country does Professional Services Company 001 belong to?", rows)
    assert names(geo) == ["United States"]
    assert geo["places"][0]["continent"] == "North America"


def test_raw_documents_are_counted_per_place():
    rows = [{"name": "a", "country": "India", "employee_count": 5},
            {"name": "b", "country": "India", "employee_count": 7},
            {"name": "c", "country": "Germany", "employee_count": 9}]
    geo = build_geo_payload("list companies", rows)
    assert geo["metric"] == "Records"
    assert {p["name"]: p["value"] for p in geo["places"]} == {"India": 2, "Germany": 1}


def test_count_answer_is_attached_to_the_country_in_the_question():
    geo = build_geo_payload("How many companies are in India?", [{"count": 38}])
    assert names(geo) == ["India"]
    assert geo["places"][0]["value"] == 38


def test_general_answer_marks_places_it_mentions():
    answer = 'root = Card([t])\nt = TextContent("The Eiffel Tower is in Paris, France.")'
    geo = build_geo_payload("Where is the Eiffel Tower?", None, answer)
    assert geo["source"] == "answer"
    assert names(geo) == ["Paris", "France"]
    assert geo["places"][0]["kind"] == "city"


def test_no_geography_means_no_map():
    assert build_geo_payload("What is SaaS?", None, 'root = Card([t])\nt = TextContent("Hosted software.")') is None
    assert build_geo_payload("Average spend by deployment", [{"_id": "SaaS", "avg": 10}]) is None


def test_ambiguous_words_need_capitals():
    assert places_in_text("tell us about chad and turkey") == []
    assert places_in_text("Chad, the US and Turkey") == [("country", "148"), ("country", "840"), ("country", "792")]


def test_category_insights():
    rows = [{"_id": "Hybrid", "total": 60}, {"_id": "SaaS", "total": 30}, {"_id": "On-Prem", "total": 10}]
    result = result_insights(rows)
    assert result["shape"] == "category"
    leader = result["insights"][0]
    assert leader["title"] == "Hybrid leads" and leader["value"] == "60%"
    assert result["insights"][1]["value"] == "6.0×"


def test_averages_are_not_reported_as_shares():
    rows = [{"_id": "Hybrid", "avg_spend": 300.0}, {"_id": "SaaS", "avg_spend": 100.0}]
    assert result_insights(rows)["insights"][0]["title"] == "Hybrid is highest"


def test_time_series_insights():
    rows = [{"_id": {"year": 2024, "month": m}, "revenue": v} for m, v in [(1, 100), (2, 150), (3, 90), (4, 200)]]
    result = result_insights(rows)
    assert result["shape"] == "time"
    kinds = {card["kind"]: card for card in result["insights"]}
    assert kinds["trend"]["value"] == "+100%"
    assert kinds["peak"]["value"] == "2024-04"


def test_raw_documents_get_no_insights():
    rows = [{"company_id": "S1", "company_name": "A", "country": "India", "employee_count": 5, "spend": 1.0}]
    assert result_insights(rows) is None


def test_demonyms_point_to_their_country():
    assert places_in_text("How many German companies use Deel?") == [("country", "276")]
    assert places_in_text("Compare Singaporean and Dutch firms") == [("country", "702"), ("country", "528")]
    assert places_in_text("please polish the report") == []


def test_region_in_question_gives_a_globe_even_for_a_single_number():
    geo = build_geo_payload("How many companies are in Europe?", [{"count": 189}])
    assert geo["places"] == []
    assert [r["name"] for r in geo["regions"]] == ["Europe"]
    europe = geo["regions"][0]
    assert {"276", "250", "826"} <= set(europe["ids"])
    assert 35 < europe["lat"] < 65 and -10 < europe["lon"] < 40
    assert geo["insights"][0]["detail"] == "Count: 189"


def test_region_and_country_rows_are_combined():
    rows = [{"_id": "Germany", "count": 50}, {"_id": "France", "count": 32}]
    geo = build_geo_payload("companies per country in EMEA", rows)
    assert names(geo) == ["Germany", "France"]
    assert [r["name"] for r in geo["regions"]] == ["EMEA"]


def test_region_beats_the_demonym_inside_it():
    assert places_in_text("North American companies") == []
    assert regions_in_text("North American and APAC companies") == ["North America", "APAC"]
    assert regions_in_text("the eu is not a region here, but the EU is") == ["European Union"]


def test_query_hints_spell_out_regions_and_demonyms():
    hints = query_hints("Total HR spend of Indian and European companies")
    assert '"Indian" means the country value "India"' in hints
    assert "Germany" in hints and "France" in hints
    assert query_hints("Average spend by deployment type") == ""
    assert "no continent or region field" in query_hints("companies by continent")


def test_new_cities_are_located():
    geo = build_geo_payload("Where is Lisbon?", None, None)
    assert names(geo) == ["Lisbon"]
    assert geo["places"][0]["country"] == "Portugal"
