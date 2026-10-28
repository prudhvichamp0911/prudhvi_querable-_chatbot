from datetime import datetime, timedelta, timezone

from backend.auth import _token_hash, hash_password, sessions, verify_password
from backend.config import settings


def test_password_hash_roundtrip():
    stored = hash_password("s3cret-password")
    assert stored.startswith("pbkdf2_sha256$")
    assert verify_password("s3cret-password", stored)
    assert not verify_password("wrong", stored)
    assert not verify_password("s3cret-password", "garbage")


def test_protected_endpoints_require_login(app_client):
    for method, path in [
        ("get", "/api/auth/me"),
        ("get", "/api/models"),
        ("get", "/api/metrics"),
        ("get", "/api/threads/get"),
        ("post", "/api/chat"),
        ("post", "/ask"),
    ]:
        response = app_client.post(path, json={}) if method == "post" else app_client.get(path)
        assert response.status_code == 401, path
        assert response.json()["error"]["code"] == "unauthenticated"


def test_health_is_public(app_client):
    body = app_client.get("/api/health").json()
    assert body["status"] == "ok"
    # Secrets are never echoed, only whether they are configured.
    assert all(not isinstance(value, str) or "sk-" not in value for value in body.values())


def test_login_sets_httponly_cookie_and_me_works(app_client, user):
    response = app_client.post("/api/auth/login", json=user)
    assert response.status_code == 200
    cookie = response.headers["set-cookie"]
    assert settings.session_cookie_name in cookie
    assert "HttpOnly" in cookie
    assert "SameSite=lax" in cookie
    me = app_client.get("/api/auth/me").json()["user"]
    assert me["username"] == "tester"
    assert "password_hash" not in me


def test_wrong_password_is_rejected_with_clear_error(app_client, user):
    response = app_client.post("/api/auth/login", json={"username": "tester", "password": "nope"})
    assert response.status_code == 401
    assert response.json()["error"]["message"] == "Incorrect username or password."


def test_lockout_after_repeated_failures(app_client, mongo):
    from backend.auth import create_user, users

    users.delete_many({"username": "locktest"})
    create_user("locktest", "right-password-1")
    for _ in range(settings.login_max_attempts):
        app_client.post("/api/auth/login", json={"username": "locktest", "password": "bad"})
    response = app_client.post("/api/auth/login", json={"username": "locktest", "password": "right-password-1"})
    assert response.status_code == 429
    users.delete_many({"username": "locktest"})


def test_logout_revokes_server_side_session(app_client, user):
    app_client.post("/api/auth/login", json=user)
    token = app_client.cookies.get(settings.session_cookie_name)
    assert sessions.find_one({"token_hash": _token_hash(token)})
    assert app_client.post("/api/auth/logout").status_code == 200
    assert sessions.find_one({"token_hash": _token_hash(token)}) is None
    # Replaying the old cookie no longer works.
    app_client.cookies.set(settings.session_cookie_name, token)
    assert app_client.get("/api/auth/me").status_code == 401


def test_expired_and_idle_sessions_are_rejected(app_client, user):
    app_client.post("/api/auth/login", json=user)
    token = app_client.cookies.get(settings.session_cookie_name)
    past = datetime.now(timezone.utc) - timedelta(minutes=settings.session_idle_minutes + 5)
    sessions.update_one({"token_hash": _token_hash(token)}, {"$set": {"last_seen": past}})
    assert app_client.get("/api/auth/me").status_code == 401

    app_client.post("/api/auth/login", json=user)
    token = app_client.cookies.get(settings.session_cookie_name)
    sessions.update_one(
        {"token_hash": _token_hash(token)},
        {"$set": {"expires_at": datetime.now(timezone.utc) - timedelta(seconds=1)}},
    )
    assert app_client.get("/api/auth/me").status_code == 401


def test_cross_site_writes_are_blocked(logged_in):
    response = logged_in.post(
        "/api/threads/create", json={"messages": []}, headers={"Origin": "https://evil.example"}
    )
    assert response.status_code == 403


def test_session_token_is_not_stored_in_plaintext(app_client, user):
    app_client.post("/api/auth/login", json=user)
    token = app_client.cookies.get(settings.session_cookie_name)
    assert sessions.find_one({"token_hash": token}) is None
    assert sessions.find_one({"token_hash": _token_hash(token)}) is not None


def test_auth_config_is_public(app_client):
    assert app_client.get("/api/auth/config").json() == {"signup_enabled": settings.allow_signup}


def test_signup_creates_account_and_signs_in(app_client, mongo):
    from backend.auth import _signups, users

    _signups.clear()
    users.delete_many({"username": "newbie"})
    response = app_client.post(
        "/api/auth/signup",
        json={"username": "Newbie", "password": "long-enough-pass", "display_name": "  New   Person "},
    )
    assert response.status_code == 201
    assert response.json()["user"] == {"username": "newbie", "display_name": "New Person", "role": "analyst"}
    assert settings.session_cookie_name in response.headers["set-cookie"]
    assert app_client.get("/api/auth/me").json()["user"]["username"] == "newbie"
    stored = users.find_one({"username": "newbie"})
    assert stored["password_hash"].startswith("pbkdf2_sha256$")
    users.delete_many({"username": "newbie"})


def test_signup_rejects_taken_and_invalid_usernames(app_client, user):
    from backend.auth import _signups

    _signups.clear()
    taken = app_client.post("/api/auth/signup", json={"username": "tester", "password": "long-enough-pass"})
    assert taken.status_code == 409
    assert taken.json()["error"]["code"] == "username_taken"

    invalid = app_client.post("/api/auth/signup", json={"username": "bad name!", "password": "long-enough-pass"})
    assert invalid.status_code == 422

    short = app_client.post("/api/auth/signup", json={"username": "shortpw", "password": "short"})
    assert short.status_code == 422


def test_signup_can_be_disabled(app_client, monkeypatch):
    from dataclasses import replace

    from backend import auth

    monkeypatch.setattr(auth, "settings", replace(auth.settings, allow_signup=False))
    response = app_client.post("/api/auth/signup", json={"username": "blocked", "password": "long-enough-pass"})
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "signup_disabled"
