# Architecture

One application, one conversation flow, one backend.

```text
Browser
  │  http://localhost:3100   (Next.js 16, openui_test/)
  │
  ├── /login ─────────────── cinematic login page (POST /api/auth/login)
  │
  └── / ─────────────────── OpenUI AgentInterface inside the cinematic shell
        │                    • componentLibrary = openuiChatLibrary (official)
        │                    • llm     = fetchLLM(/api/chat, agUIAdapter)
        │                    • storage = restStorage(/api/threads)
        │                    • artifactRenderers = query inspector, routing card
        │                    • VoiceDock (Web Speech API) → useThread().processMessage
        │
        │   /api/*  (Next.js rewrite — the browser only talks to one origin)
        ▼
FastAPI  http://127.0.0.1:8000   (backend/)
  ├── /api/auth/*        login · logout · me      (backend/auth.py)
  ├── /api/threads/*     per-user conversations   (backend/threads.py)
  ├── /api/chat          AG-UI SSE stream         (backend/chat_service.py)
  ├── /api/models        model allowlist
  ├── /api/metrics       p50/p95 latency, tokens, cost
  ├── /api/insights/overview  KPI tiles, chart panels, maps, headline insights
  ├── /api/geo/datasets · /api/geo/explore   Geo explorer (read-only $group)
  ├── /api/catalog       collections, fields, PII-masked samples
  ├── /api/health        public status (no secrets)
  └── /ask               legacy plain-text answer (login required)

/api/chat request flow
  1. Guardrails ─────────── size, control chars, prompt-injection, write intent   (guardrails.py)
  2. Jev routing ────────── OpenRouter decisions API with the collection summary  (jev_router.py)
       └─ confidence < JEV_MIN_CONFIDENCE or error → LangChain classifier          (langchain_agent.is_database_question)
  3a. database_query
       ├─ LangChain query generation from the discovered schema                   (langchain_agent.generate_database_query)
       ├─ query_velodb tool → allowlist validator → compiler → read-only VeloDB   (langchain_tools.py, validator.py, query_compiler.py, database_tool.py)
       │     maxTimeMS, row cap, PII masking, internal collections hidden
       ├─ one repair attempt with the real validator/DB error
       └─ count / empty results → deterministic OpenUI (no extra LLM call)
  3b. general_chat / browser_task
       └─ optional Graphiti/Neo4j context (GRAPHITI_ENABLED)                       (graphiti_context.py)
  4. OpenUI generation ──── OpenRouter (default) or Thesys OpenUI Gateway          (openui_engine.stream_openui)
       system prompt = openuiChatLibrary.prompt(...) generated from the frontend library
  5. Validation
       ├─ line sanitizer while streaming (unknown components, non-https URLs, HTML)
       ├─ official parser (@openuidev/lang-core createParser) in a Node sidecar  (openui_validator.py)
       ├─ grounding check: numbers must come from the VeloDB result
       ├─ one repair pass with the parser errors (Autofix-style)
       └─ still invalid → deterministic OpenUI view of the verified rows
  5b. Analysis ─────────── geo_map + data_insights tool calls, no LLM call         (geo.py, insights.py)
       ├─ countries/cities in the VeloDB rows (or named in the question/answer)
       │     → ISO ids + values → world map card in the chat (analysis-renderers.tsx)
       └─ grouped rows → leader share, concentration, spread, skew, trend, peak
  6. Streaming ─────────── AG-UI events: RUN_STARTED, TOOL_CALL_*, TEXT_MESSAGE_*, RUN_FINISHED
  7. Persistence ───────── thread messages saved per user in SQLite (chat_threads)
  8. Observability ─────── trace per request → logs/requests.jsonl, /api/metrics, Langfuse (optional)
```

## Where each existing component lives

| Component | File(s) | Role in the flow |
|---|---|---|
| FastAPI | `backend/main.py` | Single backend; auth, chat, threads, metrics |
| Jev | `backend/jev_router.py` | Primary router (now schema-aware, with timeout) |
| LangChain | `backend/langchain_agent.py`, `langchain_tools.py` | Fallback router, query generation, `query_velodb` tool |
| Query validation | `backend/validator.py` | Allowlist of operations, stages, operators, collections, fields |
| VeloDB (Apache Doris) | `backend/velodb.py`, `backend/query_compiler.py`, `backend/database_tool.py`, `backend/schema_discovery.py` | MySQL-protocol client, contract-to-SQL compiler, read-only execution, schema cache |
| SQLite document store | `backend/docstore.py`, `backend/db.py` | Users, sessions, API keys, usage, chat threads |
| OpenRouter | `backend/openui_engine.py`, `langchain_agent.py` | All LLM calls |
| OpenUI | `openui_test/src/components/cloud-chat.tsx`, `backend/openui_engine.py`, `backend/openui_validator.py` | Rendering, generation, validation |
| Graphiti/Neo4j | `backend/graphiti_service.py`, `backend/graphiti_context.py` | Optional context (disabled by default) |
| Geo & insights | `backend/geo.py`, `backend/insights.py`, `openui_test/src/components/world-map.tsx`, `analysis-renderers.tsx`, `tools/*` | Map + insight cards in chat; Insights studio, Geo explorer, Data catalog, Prompt library, Search pages (sidebar routes in `app-sidebar.tsx`) |
| Tests | `tests/` | pytest suite (`python -m pytest`) |

## Removed duplication

* The Next.js API routes that called Thesys directly with `THESYS_API_KEY`
  (`/api/chat`, `/api/frontend-token`, `/api/queryable`) were removed.
  FastAPI is the only backend.
* OpenUI Cloud thread storage (shared `DEMO_USER_ID`) was replaced by per-user
  storage in SQLite through OpenUI's `restStorage` adapter.
* FastAPI `/` now redirects to the Next.js app. `backend/static/` (the old
  HTML chat) is still served at `/static` but is no longer an entry point.
