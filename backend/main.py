import asyncio
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from backend.velodb import VeloDBError

from backend import account, auth, threads
from backend.auth import require_user
from backend.chat_service import ChatRun, model_options, with_heartbeat
from backend.config import settings
from backend.db import ping
from backend.guardrails import redact_pii
from backend import insights
from backend.schema_discovery import get_schema
from backend.langchain_agent import run_langchain_agent
from backend.jev_router import route_question
from backend.observability import logger, metrics_snapshot
from backend.openui_engine import ASSET_DIR
from backend.openui_validator import status as validator_status
from backend.openui_validator import validate as validate_openui


app = FastAPI(title="Queryable Chatbot API")

# Legacy static UI files are kept on disk for reference, but the single user
# interface is the OpenUI frontend in openui_test/ (see "/" below).
app.mount(
    "/static",
    StaticFiles(directory="backend/static"),
    name="static"
)

app.include_router(auth.router)
app.include_router(threads.router)
app.include_router(account.router)

executor = ThreadPoolExecutor(max_workers=4)


# --------------------------------------------------
# Startup and request protection
# --------------------------------------------------

@app.on_event("startup")
def startup():
    try:
        auth.ensure_indexes()
        threads.ensure_indexes()
        account.ensure_indexes()
    except Exception as error:  # store unavailable: the API still starts
        logger.warning("index setup skipped: %s", error)

    # Start the official OpenUI validator now instead of on the first answer.
    threading.Thread(
        target=validate_openui, args=("root = Card([])",), daemon=True
    ).start()

    missing = [
        name for name, value in (
            ("OPENROUTER_API_KEY", settings.openrouter_api_key),
        ) if not value
    ]
    if missing:
        logger.warning("Missing configuration: %s", ", ".join(missing))


def _allowed_origins():
    origins = {settings.frontend_url.rstrip("/")}
    parsed = urlparse(settings.frontend_url)
    if parsed.hostname == "localhost":
        origins.add(settings.frontend_url.replace("localhost", "127.0.0.1").rstrip("/"))
    elif parsed.hostname == "127.0.0.1":
        origins.add(settings.frontend_url.replace("127.0.0.1", "localhost").rstrip("/"))
    return origins


@app.middleware("http")
async def reject_cross_site_writes(request: Request, call_next):
    """CSRF protection: state-changing API calls must come from the app."""

    if request.method in {"POST", "PUT", "PATCH", "DELETE"} and request.url.path.startswith("/api/"):
        origin = request.headers.get("origin")
        if origin and origin.rstrip("/") not in _allowed_origins():
            return JSONResponse(
                {"detail": {"code": "forbidden_origin", "message": "Cross-site request blocked."}},
                status_code=403,
            )
    return await call_next(request)


@app.exception_handler(HTTPException)
async def http_error(request: Request, exc: HTTPException):
    detail = exc.detail
    if not isinstance(detail, dict):
        detail = {"code": "error", "message": str(detail)}
    # OpenUI's error helpers read `error.message`.
    return JSONResponse({"detail": detail, "error": detail}, status_code=exc.status_code)


@app.exception_handler(VeloDBError)
async def database_error(request: Request, exc: VeloDBError):
    """VeloDB down or unreachable: a clear 503 instead of a 500 traceback."""

    logger.warning("VeloDB error on %s: %s", request.url.path, type(exc).__name__)
    detail = {
        "code": "database_unavailable",
        "message": f"VeloDB is not reachable at {settings.velodb_host}:{settings.velodb_port}. "
                   "Start it with: docker compose up -d",
    }
    return JSONResponse({"detail": detail, "error": detail}, status_code=503)


# --------------------------------------------------
# Public endpoints
# --------------------------------------------------

@app.get("/")
def home():
    return RedirectResponse(settings.frontend_url)


@app.get("/api/health")
def health():
    try:
        velodb_status = "ok" if ping() else "unavailable"
    except Exception:  # noqa: BLE001
        velodb_status = "unavailable"

    return {
        "status": "ok",
        "velodb": velodb_status,
        "openrouter_configured": bool(settings.openrouter_api_key),
        "openui_provider": settings.openui_provider,
        "thesys_configured": bool(settings.thesys_api_key),
        "openui_assets": (ASSET_DIR / "system_prompt.txt").exists(),
        "openui_validator": validator_status(),
        "jev_enabled": settings.jev_enabled,
        "graphiti_enabled": settings.graphiti_enabled,
        "langfuse_enabled": bool(settings.langfuse_public_key and settings.langfuse_secret_key),
    }


# --------------------------------------------------
# Authenticated endpoints
# --------------------------------------------------

@app.get("/api/models")
def models(user=Depends(require_user)):
    return {"default": settings.openui_model, "models": model_options()}


@app.get("/api/metrics")
def metrics(user=Depends(require_user)):
    return metrics_snapshot()


def _data_call(function, *args, **kwargs):
    try:
        return function(*args, **kwargs)
    except ValueError as error:
        raise HTTPException(status_code=400, detail={"code": "bad_request", "message": str(error)})
    except Exception as error:  # noqa: BLE001 - VeloDB unavailable
        logger.warning("data endpoint failed: %s", error)
        raise HTTPException(status_code=503, detail={"code": "database_unavailable",
                                                     "message": "The database is not reachable right now."})


@app.get("/api/insights/overview")
async def insights_overview(user=Depends(require_user)):
    """KPI tiles, chart panels, maps and headline insights for the dashboard."""

    return await asyncio.to_thread(_data_call, insights.overview)


@app.get("/api/geo/datasets")
async def geo_datasets(user=Depends(require_user)):
    return {"datasets": await asyncio.to_thread(_data_call, insights.geo_datasets)}


@app.get("/api/geo/explore")
async def geo_explore(collection: str, place_field: str, value_field: str | None = None,
                      op: str = "count", user=Depends(require_user)):
    payload = await asyncio.to_thread(_data_call, insights.geo_explore, collection, place_field, value_field, op)
    return payload or {"places": [], "insights": [], "continents": []}


def _catalog():
    schema = get_schema()
    collections = []
    for name, fields in sorted(schema.items()):
        collections.append({
            "name": name,
            "documents": insights._row_count(name),
            "fields": [{"name": field, "type": info.get("type"),
                        "samples": redact_pii([{field: value} for value in info.get("sample_values", [])])}
                       for field, info in fields.items()],
        })
    return {"collections": collections}


@app.get("/api/catalog")
async def catalog(user=Depends(require_user)):
    """Collections and fields the chatbot can read (PII-masked samples)."""

    return await asyncio.to_thread(_data_call, _catalog)


@app.post("/api/chat")
async def chat(request: Request, user=Depends(require_user)):
    """OpenUI chat endpoint (AG-UI RunAgentInput in, AG-UI SSE out)."""

    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        raise HTTPException(status_code=400, detail={"code": "bad_request", "message": "Invalid JSON body."})

    messages = body.get("messages")
    thread_id = body.get("threadId")

    if not isinstance(messages, list) or not messages or not isinstance(messages[-1], dict):
        raise HTTPException(status_code=400, detail={"code": "bad_request", "message": "messages must be a non-empty list."})
    if messages[-1].get("role") != "user":
        raise HTTPException(status_code=400, detail={"code": "bad_request", "message": "The last message must be from the user."})

    if thread_id:
        await asyncio.to_thread(threads.get_owned, thread_id, user["username"])

    run = ChatRun(user, thread_id, messages, body.get("model"))

    return StreamingResponse(
        with_heartbeat(run.events()),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"},
    )


class QuestionRequest(BaseModel):
    question: str


def log_jev_result(question, jev_future, started_at):
    """Log Jev's result when the background request finishes."""
    try:
        result = jev_future.result()
        elapsed = time.perf_counter() - started_at

        print()
        print("BACKGROUND JEV RESULT:")
        print("QUESTION:", question)
        print(result)
        print(f"JEV TOTAL TIME: {elapsed:.2f} seconds")

    except Exception as e:
        elapsed = time.perf_counter() - started_at
        print("[BACKGROUND JEV ERROR]", str(e))
        print(f"JEV TOTAL TIME: {elapsed:.2f} seconds")


@app.post("/ask")
async def ask_question(request: QuestionRequest, user=Depends(require_user)):
    """Plain-text answer endpoint kept for scripts and the evaluation runner."""

    start_time = time.perf_counter()
    question = request.question

    try:
        await asyncio.to_thread(account.count_message, user)
    except account.QuotaExceeded as limit:
        raise HTTPException(status_code=429, detail={"code": "quota_exceeded", "message": limit.message})

    print()
    print("=" * 70)
    print("FASTAPI /ASK DEBUG")
    print("=" * 70)
    print("QUESTION RECEIVED:", question)

    loop = asyncio.get_running_loop()

    # Start Jev in the background.
    jev_started = time.perf_counter()
    jev_future = executor.submit(route_question, question)

    # Log Jev when it finishes, without delaying the answer.
    jev_future.add_done_callback(
        lambda future: log_jev_result(
            question,
            future,
            jev_started
        )
    )

    # Generate the answer using the existing LangChain agent.
    print("CALLING LANGCHAIN AGENT...")

    try:
        answer = await loop.run_in_executor(
            executor,
            run_langchain_agent,
            question
        )
    except Exception as e:
        elapsed = time.perf_counter() - start_time
        print("[LANGCHAIN ERROR]", str(e))
        print(f"TOTAL RESPONSE TIME: {elapsed:.2f} seconds")
        raise

    elapsed = time.perf_counter() - start_time

    print()
    print("LANGCHAIN ANSWER:")
    print(answer)
    print(f"TOTAL RESPONSE TIME: {elapsed:.2f} seconds")
    print("=" * 70)

    return {"answer": answer}
