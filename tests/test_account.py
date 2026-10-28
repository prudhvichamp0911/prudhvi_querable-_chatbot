from backend.velodb import VeloDBError

from tests.conftest import sse_events


def test_login_reports_database_down_as_503(app_client, monkeypatch):
    from backend import auth

    def down(*args, **kwargs):
        raise VeloDBError("127.0.0.1:9030: connection refused")

    monkeypatch.setattr(auth.users, "find_one", down)
    response = app_client.post("/api/auth/login", json={"username": "a", "password": "b"})
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "database_unavailable"
    assert "VeloDB" in response.json()["error"]["message"]


def test_overview_lists_plans_and_usage(logged_in):
    body = logged_in.get("/api/account/overview").json()
    assert body["plan"] == "free"
    assert {plan["id"] for plan in body["plans"]} == {"free", "pro", "team"}
    assert len(body["usage"]["days"]) == 14
    assert body["profile"]["username"] == "tester"


def test_plan_switch(logged_in):
    assert logged_in.post("/api/account/plan", json={"plan": "pro"}).json() == {"plan": "pro"}
    assert logged_in.get("/api/account/overview").json()["plan"] == "pro"
    assert logged_in.get("/api/auth/me").json()["user"]["plan"] == "pro"
    assert logged_in.post("/api/account/plan", json={"plan": "platinum"}).status_code == 400


def test_api_key_lifecycle(logged_in):
    from backend.auth import api_keys

    created = logged_in.post("/api/account/keys", json={"name": "Reporting script"})
    assert created.status_code == 201
    secret = created.json()["key"]
    assert secret.startswith("qc-")
    # Only the hash is stored.
    assert api_keys.find_one({"key_hash": secret}) is None

    listed = logged_in.get("/api/account/keys").json()["keys"]
    assert [key["name"] for key in listed] == ["Reporting script"]
    assert "key" not in listed[0]

    # A key authenticates API calls without a cookie...
    logged_in.cookies.clear()
    headers = {"Authorization": f"Bearer {secret}"}
    assert logged_in.get("/api/models", headers=headers).status_code == 200
    # ...but cannot manage the account.
    assert logged_in.get("/api/account/keys", headers=headers).status_code == 401
    assert logged_in.post("/api/account/keys", json={}, headers=headers).status_code == 401


def test_revoked_key_stops_working(logged_in):
    created = logged_in.post("/api/account/keys", json={}).json()
    assert logged_in.delete(f"/api/account/keys/{created['id']}").status_code == 200
    assert logged_in.delete(f"/api/account/keys/{created['id']}").status_code == 404
    logged_in.cookies.clear()
    response = logged_in.get("/api/models", headers={"Authorization": f"Bearer {created['key']}"})
    assert response.status_code == 401


def test_key_limit_follows_plan(logged_in):
    from backend.auth import api_keys

    api_keys.delete_many({"username": "tester"})
    for _ in range(2):
        assert logged_in.post("/api/account/keys", json={}).status_code == 201
    third = logged_in.post("/api/account/keys", json={})
    assert third.status_code == 403
    assert third.json()["error"]["code"] == "key_limit"
    logged_in.post("/api/account/plan", json={"plan": "pro"})
    assert logged_in.post("/api/account/keys", json={}).status_code == 201
    api_keys.delete_many({"username": "tester"})


def test_daily_limit_blocks_chat_with_friendly_message(logged_in, monkeypatch):
    from backend import account

    account.usage.delete_many({"username": "tester"})
    monkeypatch.setitem(account.PLANS["free"], "messages_per_day", 0)
    response = logged_in.post(
        "/api/chat",
        json={"threadId": None, "messages": [{"id": "1", "role": "user", "content": "How many companies?"}]},
    )
    events = sse_events(response)
    text = "".join(event.get("delta", "") for event in events if event["type"] == "TEXT_MESSAGE_CONTENT")
    assert "Daily limit reached" in text
    assert events[-1]["type"] == "RUN_FINISHED"


def test_profile_and_password_change(logged_in, user):
    assert logged_in.patch("/api/account/profile", json={"display_name": "  Ada   L "}).json() == {
        "display_name": "Ada L"
    }
    wrong = logged_in.post("/api/account/password", json={"current_password": "nope", "new_password": "another-pass-1"})
    assert wrong.status_code == 400
    ok = logged_in.post(
        "/api/account/password",
        json={"current_password": user["password"], "new_password": "another-pass-1"},
    )
    assert ok.status_code == 200
    # The current session keeps working; the new password signs in.
    assert logged_in.get("/api/auth/me").status_code == 200
    assert logged_in.post("/api/auth/login", json={"username": "tester", "password": "another-pass-1"}).status_code == 200
