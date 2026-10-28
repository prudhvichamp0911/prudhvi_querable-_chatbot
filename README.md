# Queryable Chatbot (VeloDB edition)

Ask business questions in plain English and get answers from real data. The
chatbot turns a question into a validated query, runs it against **VeloDB**
(Apache Doris), and renders the answer as a live OpenUI component.

This is the MongoDB project migrated to VeloDB. Nothing about the user
experience changed; the storage layer underneath did.

---

## Quick start (5 steps)

You need **Docker Desktop**, **Python 3.10+** and **Node.js 18+** installed.

```powershell
# 1. get the project
git clone https://github.com/prudhvichamp0911/prudhvi_querable-_chatbot.git
cd prudhvi_querable-_chatbot

# 2. put your OpenRouter key in .env   (see "Where the key goes" below)
Copy-Item .env.example .env
notepad .env

# 3. python environment
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

# 4. start VeloDB and load the data (first run only)
docker compose up -d
python -m velodb.load

# 5. run everything
powershell -ExecutionPolicy Bypass -File start.ps1
```

`start.ps1` brings up VeloDB, the API and the web UI, then opens
<http://localhost:3100>. Sign in with the account you create:

```powershell
python -m scripts.create_user demo --display-name "Demo User"
```

---

## Where the OpenRouter key goes

**One place only: the `OPENROUTER_API_KEY` line in `.env` at the project root.**

```dotenv
OPENROUTER_API_KEY=sk-or-v1-your-key-here
```

That file is gitignored, and the frontend never receives it — the browser
calls FastAPI, and FastAPI calls OpenRouter. Do not put the key in
`openui_test/.env.local`; the frontend holds no keys at all.

Get a key at <https://openrouter.ai/keys>. After editing `.env`, restart the
backend so it is picked up. Check it landed:

```powershell
curl http://127.0.0.1:8000/api/health
# "openrouter_configured": true
```

Without a key the app still starts, the dashboard and catalog work, but chat
answers cannot be generated.

---

## What changed in the migration

| Area | Before (MongoDB) | After (VeloDB) |
|---|---|---|
| Business data | 6 collections | 6 SQL tables, `velodb/schema.sql` |
| Driver | `pymongo` | `PyMySQL` — VeloDB speaks the MySQL protocol |
| Query execution | `database_tool.py` → PyMongo | `database_tool.py` → `query_compiler.py` → SQL |
| Schema discovery | sampled 1000 documents, guessed types | reads `information_schema` — exact types |
| Users, sessions, API keys, usage, threads | MongoDB | SQLite (`backend/docstore.py`) |
| Data load | `scripts/import_span_companies.py` | `python -m velodb.load` |

### Why the app's own tables are not in VeloDB

VeloDB is a columnar MPP warehouse: very fast at scanning and grouping the
business tables, and a poor fit for what authentication does — a point read
plus a point write on *every* request, needing unique constraints and a TTL
on sessions, none of which Doris enforces. So operational state lives in a
small SQLite document store with the same API the PyMongo code used, which is
why `auth.py`, `account.py` and `threads.py` needed no rewrite.

### The query contract did not change

The LLM still emits the same JSON the MongoDB version used:

```json
{"collection": "span_companies", "operation": "aggregate",
 "pipeline": [{"$group": {"_id": "$country", "total": {"$sum": "$annual_hr_tech_spend_usd"}}},
              {"$sort": {"total": -1}}, {"$limit": 5}]}
```

`backend/query_compiler.py` compiles that to parameterised SQL:

```sql
SELECT `country` AS `_id`, SUM(`annual_hr_tech_spend_usd`) AS `total`
FROM `span_companies` GROUP BY `country` ORDER BY `total` DESC LIMIT 5
```

Keeping the envelope meant the chat service, the OpenUI renderer, the
validator and the frontend did not have to change. Stages that make no sense
on flat SQL tables (`$unwind`, `$facet`, `$lookup`) are rejected with a clear
message instead of failing deep in the stack.

---

## The data

Six datasets, 5,475 rows, loaded by `python -m velodb.load`:

| Table | Rows | Source |
|---|---|---|
| `span_companies` | 500 | `data/span_companies.csv` |
| `customers` | 300 | `data/kaggle_ecommerce/customers.csv` |
| `products` | 50 | `data/kaggle_ecommerce/products.csv` |
| `orders` | 1000 | `data/kaggle_ecommerce/orders.csv` |
| `order_items` | 2000 | `data/kaggle_ecommerce/order_items.csv` |
| `sales_cleaned` | 1625 | `data/kaggle_ecommerce/sales_cleaned.csv` |

`span_companies` columns: `company_id`, `company_name`, `industry`,
`country`, `employee_count`, `hr_technology`, `technology_category`,
`deployment_type`, `annual_hr_tech_spend_usd`.

The loader is idempotent — run it as often as you like. `--recreate` rebuilds
the tables, `--if-empty` skips tables that already hold rows, `--only <table>`
loads one.

### Questions to try

```
How many companies are in India?
Which HR technology has the highest total spend?
Average spend by deployment type
Top 5 industries by HR tech spend
How many orders were cancelled?
Revenue by month
```

---

## Running it piece by piece

```powershell
docker compose up -d                                  # VeloDB
python -m velodb.load                                 # data
python -m uvicorn backend.main:app --reload           # API  :8000
cd openui_test; npm install; npm run dev              # UI   :3100
```

Useful URLs: <http://127.0.0.1:8000/api/health>, <http://127.0.0.1:8000/docs>,
and the Doris web console at <http://127.0.0.1:8030> (user `root`, no password).

Query VeloDB directly with any MySQL client:

```powershell
mysql -h 127.0.0.1 -P 9030 -u root
```

## Tests

```powershell
python -m pytest            # 139 passed
```

The suite uses its own VeloDB database (`queryable_chatbot_test`) and a
temporary SQLite file, and drops both afterwards. It never touches your data.

---

## Pointing at a real VeloDB Cloud instance

Only `.env` changes — no code:

```dotenv
VELODB_HOST=your-cluster.velodb.cloud
VELODB_PORT=9030
VELODB_USER=admin
VELODB_PASSWORD=your-password
VELODB_DB=queryable_chatbot
```

Then `python -m velodb.load` against it, and skip `docker compose`. Make sure
your IP is allowed in the VeloDB console first.

---

## Troubleshooting

**"VeloDB is not reachable at 127.0.0.1:9030"**
The container is not up yet. `docker compose up -d`, then give it 1–2 minutes
on first boot. Watch it with `docker compose logs -f doris`.

**Tables cannot be created: "replication num is 1, available backend num is 0"**
Doris's storage backend needs a high memory-map limit, which Docker Desktop
does not set by default. Fix it, then restart the container:

```powershell
docker run --rm --privileged --pid=host alpine nsenter -t 1 -m -u -n -i sysctl -w vm.max_map_count=2000000
docker compose restart
```

`start.ps1` does this automatically. The setting resets when Docker Desktop
restarts.

**Chat says the language model is unavailable**
`OPENROUTER_API_KEY` is missing or wrong in `.env`. Check
`/api/health` → `openrouter_configured`.

**Frontend shows no components**
`cd openui_test && npm install` — the OpenUI validator needs those packages.
Restart the backend afterwards: it checks for them once at startup.

**Which port is the app on?**
This project runs on **3100**, fixed (`next dev -p 3100` in
`openui_test/package.json`). Port 3000 is deliberately avoided because other
software commonly occupies it. If you ever change the port, change
`FRONTEND_URL` in `.env` to match and restart the backend, otherwise the CSRF
origin check rejects every write from the browser.

**The backend keeps getting killed**
The machine is out of RAM. VeloDB wants ~2.4 GB; `docker-compose.yml` caps it
at 3 GB so it cannot grow further. Close other Docker stacks and browser
windows while running this, then restart with `start.ps1`.

**Reset everything**

```powershell
docker compose down -v        # deletes the warehouse data
Remove-Item data\app_state.db # deletes users, sessions, chat threads
docker compose up -d; python -m velodb.load
```

---

## Project layout

```
prudhvi_querable-_chatbot/
├── .env.example              <- copy to .env, put your OpenRouter key in it
├── docker-compose.yml        <- VeloDB (Apache Doris) container
├── requirements.txt
├── start.ps1                 <- starts warehouse + backend + frontend
├── run_backend.ps1           <- runs the backend and restarts it if it dies
├── velodb/
│   ├── schema.sql            <- the 6 tables
│   ├── load.py               <- CSV -> VeloDB loader
│   └── conf/                 <- memory-tuned Doris configs
├── backend/
│   ├── main.py               <- FastAPI routes
│   ├── velodb.py             <- VeloDB connection, read-only query execution
│   ├── query_compiler.py     <- query contract -> SQL   (new)
│   ├── docstore.py           <- SQLite store for app state  (new)
│   ├── database_tool.py      <- runs a validated contract
│   ├── schema_discovery.py   <- reads information_schema
│   ├── validator.py          <- rejects anything unsafe before execution
│   ├── chat_service.py       <- the chat pipeline (SSE)
│   ├── langchain_agent.py    <- routing, query generation, answers
│   ├── insights.py / geo.py  <- dashboard and maps
│   └── auth.py / account.py / threads.py
├── openui_test/              <- Next.js + OpenUI frontend
├── scripts/create_user.py
├── tests/                    <- pytest suite
├── docs/architecture.md
└── data/                     <- the CSV datasets
```
