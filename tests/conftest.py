"""Shared test setup.

Tests run against a separate VeloDB database (``queryable_chatbot_test``) and
a throwaway SQLite app-state file, so they never touch real users, threads or
business data. External services (OpenRouter, Jev, Thesys) are mocked unless a
test is marked ``live``.

If VeloDB is not running, the tests that need it skip rather than fail - start
it with ``docker compose up -d``.
"""

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

TEST_DB = "queryable_chatbot_test"

# Must be set before any backend module is imported.
os.environ["VELODB_DB"] = TEST_DB
os.environ["APP_STATE_DB"] = str(Path(tempfile.gettempdir()) / "qc_test_app_state.db")
os.environ["QUERYABLE_LOG_DIR"] = str(ROOT / "logs" / "test")
os.environ.setdefault("LOGIN_MAX_ATTEMPTS", "3")
os.environ.setdefault("LOGIN_LOCKOUT_SECONDS", "60")
# A placeholder key so the routing path under test is the Jev one (which the
# tests mock). Without it the router falls through to a real LLM call and the
# suite would need network access. Tests marked "live" set a real key.
os.environ.setdefault("OPENROUTER_API_KEY", "test-key-not-used")

import pytest  # noqa: E402

import pymysql  # noqa: E402

from backend.config import settings  # noqa: E402

# The same three companies the MongoDB suite used, so the assertions in
# test_security.py and test_chat_flow.py still mean what they meant.
SPAN_ROWS = [
    {"company_id": "S1", "company_name": "Alpha", "country": "India", "deployment_type": "SaaS",
     "annual_hr_tech_spend_usd": 1000.0, "employee_count": 50, "contact_email": "ceo@alpha.example"},
    {"company_id": "S2", "company_name": "Beta", "country": "India", "deployment_type": "Hybrid",
     "annual_hr_tech_spend_usd": 3000.0, "employee_count": 120, "contact_email": "hr@beta.example"},
    {"company_id": "S3", "company_name": "Gamma", "country": "United States", "deployment_type": "Hybrid",
     "annual_hr_tech_spend_usd": 5000.0, "employee_count": 900, "contact_email": "it@gamma.example"},
]

TEST_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS span_companies (
    company_id               VARCHAR(16)   NOT NULL,
    company_name             VARCHAR(128)  NOT NULL,
    country                  VARCHAR(64)   NOT NULL,
    deployment_type          VARCHAR(16)   NOT NULL,
    employee_count           INT           NOT NULL,
    annual_hr_tech_spend_usd DECIMAL(14,2) NOT NULL,
    contact_email            VARCHAR(128)  NULL
)
UNIQUE KEY (company_id)
DISTRIBUTED BY HASH (company_id) BUCKETS 1
PROPERTIES ("replication_num" = "1")
"""


def _admin_connection():
    return pymysql.connect(
        host=settings.velodb_host, port=settings.velodb_port,
        user=settings.velodb_user, password=settings.velodb_password,
        connect_timeout=settings.velodb_connect_timeout, autocommit=True)


def velodb_available():
    try:
        con = _admin_connection()
        con.close()
        return True
    except Exception:  # noqa: BLE001
        return False


def pytest_configure(config):
    config.addinivalue_line("markers", "live: calls real external services (OpenRouter/Jev)")
    config.addinivalue_line("markers", "velodb: needs a running VeloDB instance")


@pytest.fixture(scope="session")
def warehouse():
    """A clean VeloDB test database seeded with the three sample companies."""
    if not velodb_available():
        pytest.skip(f"VeloDB is not running at "
                    f"{settings.velodb_host}:{settings.velodb_port} "
                    f"(start it with: docker compose up -d)")

    con = _admin_connection()
    with con.cursor() as cursor:
        cursor.execute(f"DROP DATABASE IF EXISTS `{TEST_DB}`")
        cursor.execute(f"CREATE DATABASE `{TEST_DB}`")
        cursor.execute(f"USE `{TEST_DB}`")
        cursor.execute(TEST_TABLE_SQL)
        cursor.executemany(
            "INSERT INTO span_companies (company_id, company_name, country, "
            "deployment_type, employee_count, annual_hr_tech_spend_usd, contact_email) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s)",
            [(r["company_id"], r["company_name"], r["country"], r["deployment_type"],
              r["employee_count"], r["annual_hr_tech_spend_usd"], r["contact_email"])
             for r in SPAN_ROWS])
    con.close()

    from backend import auth, threads
    from backend.schema_discovery import clear_schema_cache

    auth.ensure_indexes()
    threads.ensure_indexes()
    clear_schema_cache()

    yield

    con = _admin_connection()
    with con.cursor() as cursor:
        cursor.execute(f"DROP DATABASE IF EXISTS `{TEST_DB}`")
    con.close()


@pytest.fixture()
def mongo(warehouse):
    """Backwards-compatible alias.

    The tests were written against MongoDB and ask for a fixture called
    ``mongo``. The store behind it is VeloDB now; keeping the name means the
    assertions did not have to be touched during the migration.
    """
    return warehouse


@pytest.fixture(autouse=True)
def _clean_app_state():
    """Each test starts with empty users/sessions/threads."""
    from backend.db import db

    for name in ("app_users", "app_sessions", "app_api_keys", "app_usage", "chat_threads"):
        db[name].delete_many({})
    yield


@pytest.fixture()
def app_client(warehouse):
    from fastapi.testclient import TestClient

    import backend.main as main

    with TestClient(main.app) as test_client:
        yield test_client


@pytest.fixture()
def user(warehouse):
    from backend.auth import create_user, users

    users.delete_many({"username": "tester"})
    create_user("tester", "correct-horse-battery", "Tester")
    yield {"username": "tester", "password": "correct-horse-battery"}
    users.delete_many({"username": "tester"})


@pytest.fixture()
def logged_in(app_client, user):
    response = app_client.post("/api/auth/login", json=user)
    assert response.status_code == 200
    return app_client


def sse_events(response):
    import json

    events = []
    for line in response.iter_lines():
        if line.startswith("data: "):
            events.append(json.loads(line[6:]))
    return events


@pytest.fixture(autouse=True)
def _clear_query_cache():
    from backend import chat_service

    chat_service._QUERY_CACHE.clear()
    yield
    chat_service._QUERY_CACHE.clear()
