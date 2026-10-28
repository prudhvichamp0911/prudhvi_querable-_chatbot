"""Login, sessions and route protection.

* Passwords: PBKDF2-HMAC-SHA256 with a per-user salt (standard library).
* Sessions: random 256-bit tokens. Only the SHA-256 of a token is stored in
  ``app_sessions``, so a database leak does not expose live sessions.
* Cookie: httpOnly, SameSite=Lax, Secure when COOKIE_SECURE=true.
* Expiry: absolute (SESSION_TTL_MINUTES) and idle (SESSION_IDLE_MINUTES).
* Logout deletes the server-side session, so the cookie stops working
  immediately.
* Brute force: failed logins per username+IP are locked out temporarily.
"""

import hashlib
import hmac
import re
import secrets
import threading
import time
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from backend.docstore import DuplicateKeyError

from backend.config import settings
from backend.db import db

PBKDF2_ITERATIONS = 310_000

users = db["app_users"]
sessions = db["app_sessions"]
api_keys = db["app_api_keys"]

router = APIRouter(prefix="/api/auth", tags=["auth"])


def ensure_indexes():
    users.create_index("username", unique=True)
    sessions.create_index("token_hash", unique=True)
    # The document store drops expired sessions on read (TTL index).
    sessions.create_index("expires_at", expireAfterSeconds=0)
    api_keys.create_index("key_hash", unique=True)
    api_keys.create_index([("username", 1), ("created_at", -1)])


# --------------------------------------------------
# Passwords
# --------------------------------------------------

def hash_password(password, salt=None):
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS)
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${salt.hex()}${digest.hex()}"


def verify_password(password, stored):
    try:
        algorithm, iterations, salt_hex, digest_hex = stored.split("$")
        if algorithm != "pbkdf2_sha256":
            return False
        digest = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            bytes.fromhex(salt_hex),
            int(iterations),
        )
        return hmac.compare_digest(digest.hex(), digest_hex)
    except (ValueError, AttributeError):
        return False


def create_user(username, password, display_name=None, role="analyst"):
    username = username.strip().lower()
    if len(password) < 8:
        raise ValueError("Password must be at least 8 characters.")
    users.insert_one(
        {
            "username": username,
            "display_name": display_name or username,
            "role": role,
            "password_hash": hash_password(password),
            "created_at": datetime.now(timezone.utc),
            "disabled": False,
        }
    )
    return username


# --------------------------------------------------
# Login rate limiting
# --------------------------------------------------

_failures = {}
_failures_lock = threading.Lock()


def _attempt_key(username, request):
    host = request.client.host if request.client else "unknown"
    return f"{username}|{host}"


def _locked_for(key):
    with _failures_lock:
        entry = _failures.get(key)
        if not entry:
            return 0
        count, first, locked_until = entry
        remaining = locked_until - time.monotonic()
        return max(0, int(remaining)) if remaining > 0 else 0


def _register_failure(key):
    now = time.monotonic()
    with _failures_lock:
        count, first, locked_until = _failures.get(key, (0, now, 0))
        if now - first > settings.login_lockout_seconds:
            count, first = 0, now
        count += 1
        if count >= settings.login_max_attempts:
            locked_until = now + settings.login_lockout_seconds
        _failures[key] = (count, first, locked_until)


def _clear_failures(key):
    with _failures_lock:
        _failures.pop(key, None)


# --------------------------------------------------
# Sessions
# --------------------------------------------------

def _token_hash(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_session(user):
    token = secrets.token_urlsafe(32)
    now = datetime.now(timezone.utc)
    sessions.insert_one(
        {
            "token_hash": _token_hash(token),
            "username": user["username"],
            "created_at": now,
            "last_seen": now,
            "expires_at": now + timedelta(minutes=settings.session_ttl_minutes),
        }
    )
    return token


def _as_utc(value):
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def resolve_session(token):
    """Return the user for a session token, or None if invalid/expired."""

    if not token:
        return None

    session = sessions.find_one({"token_hash": _token_hash(token)})
    if not session:
        return None

    now = datetime.now(timezone.utc)
    idle_limit = timedelta(minutes=settings.session_idle_minutes)

    if _as_utc(session["expires_at"]) <= now or now - _as_utc(session["last_seen"]) > idle_limit:
        sessions.delete_one({"_id": session["_id"]})
        return None

    user = users.find_one({"username": session["username"], "disabled": {"$ne": True}})
    if not user:
        return None

    sessions.update_one({"_id": session["_id"]}, {"$set": {"last_seen": now}})

    return {
        "username": user["username"],
        "display_name": user.get("display_name") or user["username"],
        "role": user.get("role", "analyst"),
        "plan": user.get("plan") or settings.default_plan,
        "session_expires_at": _as_utc(session["expires_at"]).isoformat(),
        "auth": "session",
    }


API_KEY_PREFIX = "qc-"


def resolve_api_key(key):
    """Return the user for a personal API key (Settings → API keys), or None."""

    if not key or not key.startswith(API_KEY_PREFIX):
        return None

    record = api_keys.find_one({"key_hash": _token_hash(key), "revoked_at": None})
    if not record:
        return None

    user = users.find_one({"username": record["username"], "disabled": {"$ne": True}})
    if not user:
        return None

    api_keys.update_one({"_id": record["_id"]}, {"$set": {"last_used_at": datetime.now(timezone.utc)}})

    return {
        "username": user["username"],
        "display_name": user.get("display_name") or user["username"],
        "role": user.get("role", "analyst"),
        "auth": "api_key",
    }


def _unauthenticated():
    return HTTPException(
        status_code=401,
        detail={"code": "unauthenticated", "message": "Your session has expired. Please sign in again."},
    )


def require_session_user(request: Request):
    """Browser session only: account changes cannot be made with an API key."""

    user = resolve_session(request.cookies.get(settings.session_cookie_name))
    if user is None:
        raise _unauthenticated()
    return user


def require_user(request: Request):
    """FastAPI dependency protecting every non-public endpoint.

    Accepts the session cookie, or ``Authorization: Bearer qc-...`` for
    scripts using a personal API key.
    """

    user = resolve_session(request.cookies.get(settings.session_cookie_name))
    if user is None:
        scheme, _, credentials = request.headers.get("authorization", "").partition(" ")
        if scheme.lower() == "bearer":
            user = resolve_api_key(credentials.strip())
    if user is None:
        raise _unauthenticated()
    return user


def _set_cookie(response, token):
    response.set_cookie(
        settings.session_cookie_name,
        token,
        max_age=settings.session_ttl_minutes * 60,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/",
    )


# --------------------------------------------------
# Routes
# --------------------------------------------------

class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=200)


@router.post("/login")
def login(payload: LoginRequest, request: Request, response: Response):
    username = payload.username.strip().lower()
    key = _attempt_key(username, request)

    locked = _locked_for(key)
    if locked:
        raise HTTPException(
            status_code=429,
            detail={
                "code": "locked",
                "message": f"Too many failed attempts. Try again in {locked} seconds.",
            },
        )

    user = users.find_one({"username": username, "disabled": {"$ne": True}})

    if not user or not verify_password(payload.password, user.get("password_hash", "")):
        _register_failure(key)
        raise HTTPException(
            status_code=401,
            detail={"code": "invalid_credentials", "message": "Incorrect username or password."},
        )

    _clear_failures(key)
    token = create_session(user)
    _set_cookie(response, token)

    return {
        "user": {
            "username": user["username"],
            "display_name": user.get("display_name") or user["username"],
            "role": user.get("role", "analyst"),
        }
    }


USERNAME_PATTERN = r"^[a-z0-9][a-z0-9._-]{2,31}$"

_signups = {}
_signups_lock = threading.Lock()


def _signup_allowed(request):
    """At most SIGNUP_MAX_PER_HOUR new accounts per client IP per hour."""

    host = request.client.host if request.client else "unknown"
    now = time.monotonic()
    with _signups_lock:
        recent = [stamp for stamp in _signups.get(host, []) if now - stamp < 3600]
        if len(recent) >= settings.signup_max_per_hour:
            _signups[host] = recent
            return False
        recent.append(now)
        _signups[host] = recent
        return True


class SignupRequest(BaseModel):
    username: str = Field(min_length=3, max_length=32)
    password: str = Field(min_length=8, max_length=200)
    display_name: str = Field(default="", max_length=80)


@router.get("/config")
def auth_config():
    """Public: tells the login page whether to offer "Create account"."""

    return {"signup_enabled": settings.allow_signup}


@router.post("/signup", status_code=201)
def signup(payload: SignupRequest, request: Request, response: Response):
    if not settings.allow_signup:
        raise HTTPException(
            status_code=403,
            detail={"code": "signup_disabled", "message": "Sign-up is turned off. Ask an administrator for an account."},
        )

    username = payload.username.strip().lower()
    if not re.fullmatch(USERNAME_PATTERN, username):
        raise HTTPException(
            status_code=422,
            detail={
                "code": "invalid_username",
                "message": "Usernames are 3–32 characters: letters, numbers, dots, dashes or underscores.",
            },
        )

    if not _signup_allowed(request):
        raise HTTPException(
            status_code=429,
            detail={"code": "signup_rate_limited", "message": "Too many new accounts from this network. Try again later."},
        )

    display_name = " ".join(payload.display_name.split()) or username
    try:
        create_user(username, payload.password, display_name=display_name)
    except DuplicateKeyError:
        raise HTTPException(
            status_code=409,
            detail={"code": "username_taken", "message": "That username is already taken."},
        ) from None

    user = users.find_one({"username": username})
    _set_cookie(response, create_session(user))

    return {
        "user": {
            "username": username,
            "display_name": display_name,
            "role": user.get("role", "analyst"),
        }
    }


@router.post("/logout")
def logout(request: Request, response: Response):
    token = request.cookies.get(settings.session_cookie_name)
    if token:
        sessions.delete_one({"token_hash": _token_hash(token)})
    response.delete_cookie(settings.session_cookie_name, path="/")
    return {"ok": True}


@router.get("/me")
def me(user=Depends(require_session_user)):
    return {"user": user}
