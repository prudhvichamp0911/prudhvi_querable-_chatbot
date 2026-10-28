"""Account settings: plan and usage limits, personal API keys, profile.

Modelled on the settings pages of ChatGPT / Claude and the OpenAI / Anthropic
API consoles:

* Plans (Free, Pro, Team) set a daily message limit and how many API keys a
  user may hold. Billing is simulated: no payment processor is connected,
  so switching plan only changes the limits. Admins are never limited.
* API keys are shown once at creation. Only the SHA-256 of a key is stored,
  plus a short prefix so the user can tell keys apart.
* Usage is counted per user per UTC day in ``app_usage``.

    GET    /api/account/overview         -> plan, plans, usage, profile
    POST   /api/account/plan             -> switch plan
    GET    /api/account/keys             -> key list (no secrets)
    POST   /api/account/keys             -> new key (secret returned once)
    DELETE /api/account/keys/{id}        -> revoke
    PATCH  /api/account/profile          -> display name
    POST   /api/account/password         -> change password
    POST   /api/account/sessions/revoke  -> sign out other devices
"""

import secrets
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from backend.auth import (
    API_KEY_PREFIX,
    _token_hash,
    api_keys,
    hash_password,
    require_session_user,
    sessions,
    users,
    verify_password,
)
from backend.config import settings
from backend.db import db

usage = db["app_usage"]

router = APIRouter(prefix="/api/account", tags=["account"])

PLANS = {
    "free": {
        "id": "free",
        "name": "Free",
        "price_usd": 0,
        "period": "forever",
        "tagline": "For trying things out",
        "messages_per_day": 50,
        "api_keys": 2,
        "features": [
            "50 questions per day",
            "All models in the model switcher",
            "Charts, maps and the 3D globe",
            "2 personal API keys",
        ],
    },
    "pro": {
        "id": "pro",
        "name": "Pro",
        "price_usd": 20,
        "period": "per month",
        "tagline": "For analysts who live in their data",
        "messages_per_day": 500,
        "api_keys": 10,
        "features": [
            "500 questions per day",
            "Everything in Free",
            "10 personal API keys",
            "Priority answers during busy hours",
        ],
    },
    "team": {
        "id": "team",
        "name": "Team",
        "price_usd": 30,
        "period": "per seat / month",
        "tagline": "For teams sharing one source of truth",
        "messages_per_day": None,
        "api_keys": 25,
        "features": [
            "Unlimited questions",
            "Everything in Pro",
            "25 personal API keys",
            "Admin-managed accounts",
        ],
    },
}

USAGE_DAYS = 14


def ensure_indexes():
    usage.create_index([("username", 1), ("day", 1)], unique=True)


def _today():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def plan_for(user):
    plan = (user or {}).get("plan") or settings.default_plan
    return PLANS.get(plan, PLANS["free"])


def _user_record(username):
    return users.find_one({"username": username}) or {}


def daily_limit(user):
    """Messages per day for this user, or None for unlimited."""

    if user.get("role") == "admin" or not settings.plan_limits_enforced:
        return None
    return plan_for(_user_record(user["username"]))["messages_per_day"]


class QuotaExceeded(Exception):
    def __init__(self, message):
        super().__init__(message)
        self.message = message


def count_message(user):
    """Count one question against today's limit; raise QuotaExceeded when over."""

    limit = daily_limit(user)
    day = _today()
    if limit is not None:
        current = usage.find_one({"username": user["username"], "day": day}) or {}
        if current.get("messages", 0) >= limit:
            plan = plan_for(_user_record(user["username"]))
            raise QuotaExceeded(
                f"You've used all {limit} questions included in the {plan['name']} plan today. "
                "The limit resets at midnight UTC, or you can upgrade in Settings → Plan & billing."
            )
    usage.update_one(
        {"username": user["username"], "day": day},
        {"$inc": {"messages": 1}, "$setOnInsert": {"tokens": 0, "cost_usd": 0.0}},
        upsert=True,
    )


def record_usage(username, tokens=0, cost_usd=0.0):
    """Add tokens and cost of a finished request to today's usage."""

    usage.update_one(
        {"username": username, "day": _today()},
        {"$inc": {"tokens": int(tokens or 0), "cost_usd": float(cost_usd or 0.0)},
         "$setOnInsert": {"messages": 0}},
        upsert=True,
    )


def _usage_summary(user):
    today = datetime.now(timezone.utc).date()
    days = [(today - timedelta(days=offset)).isoformat() for offset in range(USAGE_DAYS - 1, -1, -1)]
    rows = {doc["day"]: doc for doc in usage.find({"username": user["username"], "day": {"$in": days}})}
    series = [
        {
            "day": day,
            "messages": rows.get(day, {}).get("messages", 0),
            "tokens": rows.get(day, {}).get("tokens", 0),
            "cost_usd": round(rows.get(day, {}).get("cost_usd", 0.0), 6),
        }
        for day in days
    ]
    return {
        "today": series[-1]["messages"],
        "limit": daily_limit(user),
        "days": series,
        "total_messages": sum(row["messages"] for row in series),
        "total_tokens": sum(row["tokens"] for row in series),
        "total_cost_usd": round(sum(row["cost_usd"] for row in series), 6),
    }


def _public_key(doc):
    return {
        "id": doc["_id"],
        "name": doc.get("name") or "Secret key",
        "preview": f"{doc['prefix']}…{doc.get('suffix', '')}",
        "created_at": doc["created_at"].isoformat() if doc.get("created_at") else None,
        "last_used_at": doc["last_used_at"].isoformat() if doc.get("last_used_at") else None,
    }


# --------------------------------------------------
# Routes
# --------------------------------------------------

@router.get("/overview")
def overview(user=Depends(require_session_user)):
    record = _user_record(user["username"])
    plan = plan_for(record)
    return {
        "profile": {
            "username": user["username"],
            "display_name": user["display_name"],
            "role": user["role"],
            "created_at": record["created_at"].isoformat() if record.get("created_at") else None,
        },
        "plan": plan["id"],
        "plans": list(PLANS.values()),
        "billing_simulated": True,
        "limits_enforced": settings.plan_limits_enforced and user["role"] != "admin",
        "usage": _usage_summary(user),
        "api_keys": {
            "count": api_keys.count_documents({"username": user["username"], "revoked_at": None}),
            "limit": plan["api_keys"],
        },
    }


class PlanChange(BaseModel):
    plan: str


@router.post("/plan")
def change_plan(payload: PlanChange, user=Depends(require_session_user)):
    if payload.plan not in PLANS:
        raise HTTPException(status_code=400, detail={"code": "unknown_plan", "message": "Unknown plan."})
    users.update_one({"username": user["username"]}, {"$set": {"plan": payload.plan}})
    return {"plan": payload.plan}


@router.get("/keys")
def list_keys(user=Depends(require_session_user)):
    docs = api_keys.find({"username": user["username"], "revoked_at": None}).sort("created_at", -1)
    return {"keys": [_public_key(doc) for doc in docs]}


class NewKey(BaseModel):
    name: str = Field(default="", max_length=60)


@router.post("/keys", status_code=201)
def create_key(payload: NewKey, user=Depends(require_session_user)):
    plan = plan_for(_user_record(user["username"]))
    active = api_keys.count_documents({"username": user["username"], "revoked_at": None})
    if user["role"] != "admin" and active >= plan["api_keys"]:
        raise HTTPException(
            status_code=403,
            detail={
                "code": "key_limit",
                "message": f"The {plan['name']} plan allows {plan['api_keys']} API keys. "
                           "Revoke one or upgrade your plan.",
            },
        )

    secret = API_KEY_PREFIX + secrets.token_urlsafe(32)
    doc = {
        "_id": str(uuid.uuid4()),
        "username": user["username"],
        "name": " ".join(payload.name.split()) or "Secret key",
        "key_hash": _token_hash(secret),
        "prefix": secret[:7],
        "suffix": secret[-4:],
        "created_at": datetime.now(timezone.utc),
        "last_used_at": None,
        "revoked_at": None,
    }
    api_keys.insert_one(doc)
    # The only time the full key is ever returned.
    return {"key": secret, **_public_key(doc)}


@router.delete("/keys/{key_id}")
def revoke_key(key_id: str, user=Depends(require_session_user)):
    result = api_keys.update_one(
        {"_id": key_id, "username": user["username"], "revoked_at": None},
        {"$set": {"revoked_at": datetime.now(timezone.utc)}},
    )
    if not result.matched_count:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "API key not found."})
    return {"ok": True}


class ProfileUpdate(BaseModel):
    display_name: str = Field(min_length=1, max_length=80)


@router.patch("/profile")
def update_profile(payload: ProfileUpdate, user=Depends(require_session_user)):
    name = " ".join(payload.display_name.split())
    if not name:
        raise HTTPException(status_code=422, detail={"code": "invalid_name", "message": "Enter a name."})
    users.update_one({"username": user["username"]}, {"$set": {"display_name": name}})
    return {"display_name": name}


class PasswordChange(BaseModel):
    current_password: str = Field(min_length=1, max_length=200)
    new_password: str = Field(min_length=8, max_length=200)


def _current_token_hash(request):
    token = request.cookies.get(settings.session_cookie_name)
    return _token_hash(token) if token else None


@router.post("/password")
def change_password(payload: PasswordChange, request: Request, user=Depends(require_session_user)):
    record = _user_record(user["username"])
    if not verify_password(payload.current_password, record.get("password_hash", "")):
        raise HTTPException(
            status_code=400,
            detail={"code": "wrong_password", "message": "Your current password is incorrect."},
        )
    users.update_one(
        {"username": user["username"]},
        {"$set": {"password_hash": hash_password(payload.new_password)}},
    )
    # Every other device has to sign in again with the new password.
    sessions.delete_many({"username": user["username"], "token_hash": {"$ne": _current_token_hash(request)}})
    return {"ok": True}


@router.post("/sessions/revoke")
def revoke_other_sessions(request: Request, user=Depends(require_session_user)):
    result = sessions.delete_many(
        {"username": user["username"], "token_hash": {"$ne": _current_token_hash(request)}}
    )
    return {"revoked": result.deleted_count}
