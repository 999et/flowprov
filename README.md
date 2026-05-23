# flowprov

> Provenance and drift detection for the agentic workflows you've already shipped.

`flowprov` watches every node execution in your n8n / BuildShip / LangGraph flows and tells you, in near real time, when an LLM-backed node's behaviour drifts from its historical norm — *before* the downstream weirdness shows up in your support queue.

It does three things:

1. **Records** every node execution as a (flow, version, input-hash, output, embedding) tuple in Postgres + pgvector.
2. **Detects drift** by comparing each new output's embedding against historical executions of the same logical request, using a tunable two-tier policy (hard-fail + soft-warn-on-z-score).
3. **Explains drift** by letting you replay any historical execution against any prompt/model version and diffing the outputs.

The system itself runs as either (a) a sidecar HTTP service that your n8n nodes POST to, or (b) an n8n flow that processes your other n8n flows (delightfully meta).

## Table of contents

1. [Why this exists](#why-this-exists)
2. [Quick start](#quick-start)
3. [Expected output](#expected-output)
4. [How it works](#how-it-works)
5. [Wiring your own n8n flows](#wiring-your-own-n8n-flows)
6. [Tuning drift detection](#tuning-drift-detection)
7. [Project layout](#project-layout)
8. [Migrating from local Postgres to Supabase](#migrating-from-local-postgres-to-supabase)
9. [Troubleshooting](#troubleshooting)

---

## Why this exists

When you move business logic out of code and into low-code orchestration with embedded LLM nodes, you trade one class of risk (refactor regressions caught by unit tests) for a worse one: **silent stochastic drift**. Someone "improves" a prompt; a model auto-upgrades on the provider side; an upstream input distribution shifts. Three weeks later, ops notices something is off, and you spend a day reconstructing what changed.

`flowprov` is the unit-test substitute for the stochastic layer.

The two core insights:

1. **Canonical input hash** groups executions of the "same logical request" so we can build a per-class baseline. This is what lets us say "the same input produced a different output today."
2. **Versioned (prompt, model, temperature) tuples** make every prompt change a first-class object you can point a finger at. When drift fires on `v3`, you can replay the same input against `v2` and see exactly what changed.

---

## Quick start 

### Prerequisites

```bash
# Python 3.11+ (Debian 13 ships 3.12+ by default)
sudo apt update
sudo apt install -y python3 python3-venv python3-dev build-essential

# Docker + Compose v2 (used for Postgres)
sudo apt install -y docker.io docker-compose-v2
sudo usermod -aG docker $USER
# Log out & back in (or run `newgrp docker`) so your shell picks up the group.
```

Quick sanity check:

```bash
python3 --version       # 3.11.x or 3.12.x
docker --version
docker compose version
```

### One-shot bootstrap

```bash
cd flowprov
./scripts/bootstrap.sh
```

The bootstrap script:
1. Verifies Python ≥ 3.11 and Docker
2. Creates `.venv` and installs all dependencies in editable mode
3. Copies `.env.example` → `.env` (if not already present)
4. Starts the Postgres + pgvector container on host port `5433`
5. Runs Alembic migrations to create the schema and the IVFFlat index

If you'd rather drive it yourself instead of using the script:

```bash
make install     # create .venv and pip install everything
cp .env.example .env
make db-up       # start Postgres + pgvector
make migrate     # apply migrations
```

### Run the API

In Terminal A:

```bash
make api
```

You should see:

```
INFO  flowprov starting up
INFO  Uvicorn running on http://0.0.0.0:8000 (Press CTRL+C to quit)
INFO  Application startup complete.
```

Open <http://localhost:8000/> — the dashboard will be empty.

### Run the demo simulator

In Terminal B (with the API still running):

```bash
make demo
```

This generates ~90 realistic executions across five flows (HackerOne triage, reconciliation classifier, support ticket router, payment decision agent, KYC summariser) using the fake offline LLM. The run takes a few seconds with the default hash embedder; the first run takes ~30 seconds extra if you've enabled the optional MiniLM backend.

Refresh the dashboard. You'll see five flows with a healthy execution count and no drift yet.

### Inject drift

```bash
make demo-drift
```

This re-runs three of the HackerOne triage inputs against a *deliberately broken* version of the prompt (one that suppresses severity/component/owner). Drift events fire. Open <http://localhost:8000/> and you'll see them at the top of the page.

### Confirm root cause via replay

On any drift event, click **replay**. The page re-runs the original input against the *good* (v1) prompt and shows a side-by-side diff with cosine distance. That diff is the root cause, visible in 4 seconds, with no archaeology.

---

## Expected output

### Terminal A — API server (`make api`)

```
2026-05-23 09:42:11,328 INFO    flowprov — flowprov starting up
INFO:     Started server process [13892]
INFO:     Waiting for application startup.
INFO:     Application startup complete.
INFO:     Uvicorn running on http://0.0.0.0:8000 (Press CTRL+C to quit)
INFO:     127.0.0.1:55432 - "POST /api/ingest HTTP/1.1" 200 OK
INFO:     127.0.0.1:55432 - "POST /api/ingest HTTP/1.1" 200 OK
...
2026-05-23 09:43:17,884 INFO    flowprov.service — New flow version: security.hackerone.triage v2
2026-05-23 09:43:17,901 WARNING flowprov.service — DRIFT FAIL on flow=security.hackerone.triage node=llm.triage exec=88: Nearest in-class neighbor is 0.612 away (>0.40 hard threshold). Output is unlike anything we've seen for this input.
```

### Terminal B — `make demo`

```
flowprov · demo simulator
  api: http://localhost:8000
  llm: fake (deterministic, offline)
  flows: 5, runs/class: 6

⠹ seeding executions...

✔ 90 executions ingested
  drift signals during baseline: 0

→ open http://localhost:8000/ to inspect the dashboard
→ next: make demo-drift to inject a prompt regression and trigger drift
```

### Terminal B — `make demo-drift`

```
flowprov · drift injection
  flow: security.hackerone.triage
  regression: prompt rewritten to suppress severity/component/owner
  will replay 3 input classes against the new prompt

  → ingested execution    88  v2  FAIL (dist=0.612)
  → ingested execution    89  v2  FAIL (dist=0.587)
  → ingested execution    90  v2  FAIL (dist=0.643)

drift signals fired: 3 fail · 0 warn

→ open http://localhost:8000/flows/security.hackerone.triage
  inspect the new version and the drift events.
→ then click 'replay' on a drifted execution to see it re-run against
  the original (good) version and confirm root cause.
```

### Browser — `http://localhost:8000/`

After `make demo`:

| flow id                          | name                                | versions | executions | drift |
|----------------------------------|-------------------------------------|---------:|-----------:|------:|
| `security.hackerone.triage`      | HackerOne Report Triage             |       1  |        18  |  —   |
| `finance.recon.classify`         | Reconciliation Exception Classifier |       1  |        24  |  —   |
| `support.ticket.route`           | Support Ticket Router               |       1  |        18  |  —   |
| `finance.payment.decide`         | Payment Decision Agent              |       1  |        18  |  —   |
| `kyc.update.summarize`           | KYC Update Summariser               |       1  |        12  |  —   |

After `make demo-drift` you'll see `versions = 2` and `drift = 3` on the HackerOne row.

### Browser — replay view

A side-by-side panel with the original output (under `v1`) on the left, the regressed output (under `v2`) on the right, the cosine distance prominent at the top, and a unified diff at the bottom highlighting exactly which words and structures changed.

---

## How it works

### The data model

Four tables, all defined in `migrations/versions/001_initial_schema.py`:

| table          | role                                                                                                                                                                                                                                  |
|----------------|---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `flows`        | A logical flow (one row per `flow_id`). Created on first sight.                                                                                                                                                                       |
| `flow_versions`| A specific `(flow_id, prompt_template, model_name, temperature)` tuple. A new row whenever any of those four change — this is what makes "what changed?" answerable.                                                                  |
| `executions`   | One row per node execution. Includes the canonicalised input hash, the full output text, and the `pgvector` embedding. Indexed by IVFFlat on the embedding column for sub-millisecond k-NN.                                           |
| `drift_events` | One row per detected drift signal. Severity is either `warn` or `fail`, distance is the cosine distance to the nearest in-class neighbour, and the explanation captures the baseline statistics.                                       |

### The detection algorithm

For every new execution, we:

1. **Embed** the output text with `all-MiniLM-L6-v2` (384-dim vector, normalised).
2. **Compute the canonical input hash**: drop volatile keys (`_ts`, `_request_id`, etc.), sort remaining keys, JSON-serialise, BLAKE2b-256. This is what groups executions of the "same logical request."
3. **k-NN against in-class history** using pgvector's `<=>` operator and the IVFFlat index.
4. **Two-tier policy**:
   - **Hard fail**: if the *nearest* historical neighbour is more than `DRIFT_HARD_THRESHOLD` away (default 0.40), fire `fail`. Even unrelated outputs from the same model usually sit ≤ 0.25 apart in cosine distance, so 0.40 catches anything genuinely off.
   - **Soft warn**: if there are at least `DRIFT_MIN_HISTORY` historical samples (default 5), compute the mean and std of the in-class distances. If the new output's nearest-neighbour distance exceeds `mean + DRIFT_SOFT_STD_MULTIPLIER * std` (default 2.5σ), fire `warn`.

The thresholds are explicitly tunable per environment via `.env`. In production you'd want to learn them per `(flow, node)` from your false-positive feedback loop; the schema is ready for that — see `drift_events.acknowledged`.

### Why a hash backend by default?

The default `EMBEDDING_PROVIDER=hash` is a deterministic, dependency-free embedder built on character 3-gram + word unigram hashing into 384 buckets, log-damped and L2-normalised. It's *not* as semantically rich as a real transformer, but for our specific question — "did this LLM output drift from previous outputs of the same logical request?" — it is empirically sufficient and has three big wins:

1. **Zero ML deps**: the demo runs anywhere, no torch download, no GPU concerns, no `~/.cache/huggingface` to manage.
2. **Deterministic**: identical input → identical vector forever. Great for CI and reproducible drift thresholds.
3. **Fast**: ~50µs per string on a single core. The dashboard stays snappy under load.

For production, switch to `EMBEDDING_PROVIDER=minilm`:

```bash
pip install -e ".[ml]"
# then in .env:
EMBEDDING_PROVIDER=minilm
```

This pulls in `sentence-transformers/all-MiniLM-L6-v2` (a real 384-dim transformer, ~80 MB download on first run) which gives stronger semantic discrimination at the cost of ~1.5 GB of disk for the torch + transformers stack. Both backends produce 384-dim vectors so you can switch without changing the schema. Higher-fidelity options like `bge-base-en-v1.5` or hosted Voyage/OpenAI embeddings would slot in as a third backend with no schema change beyond a `Vector(N)` dimension bump.

---

## Wiring your own n8n flows

See [`examples/n8n_workflows/README.md`](examples/n8n_workflows/README.md) for the importable workflow and the manual wiring guide. The contract is a single HTTP POST per LLM-node execution; sample payload:

```json
{
  "flow_id": "security.hackerone.triage",
  "flow_name": "HackerOne Report Triage",
  "node_id": "llm.triage",
  "prompt_template": "You are a senior security analyst...",
  "model_name": "gpt-4o-mini",
  "model_provider": "openai",
  "temperature": 0.0,
  "input_json": { "title": "...", "body": "...", "asset": "..." },
  "output_text": "Severity: P1. Likely component: api. Recommended owner: @team-platform.",
  "latency_ms": 842,
  "token_usage_json": {"prompt_tokens": 128, "completion_tokens": 32}
}
```

---

## Tuning drift detection

Edit `.env`:

```bash
# Hard-fail threshold — distance above which we flag regardless of class history
DRIFT_HARD_THRESHOLD=0.40

# Soft-warn z-score multiplier — distance > mean + N*std fires warn
DRIFT_SOFT_STD_MULTIPLIER=2.5

# Min historical samples before soft-warn becomes active
DRIFT_MIN_HISTORY=5

# k-NN candidates pulled per query
DRIFT_KNN=10
```

Tuning playbook:

| symptom                            | adjust                                            |
|------------------------------------|---------------------------------------------------|
| too many false positives           | raise `DRIFT_SOFT_STD_MULTIPLIER` (e.g. 3.0)      |
| missing real drift                 | lower `DRIFT_HARD_THRESHOLD` (e.g. 0.30)          |
| warns firing on fresh classes      | raise `DRIFT_MIN_HISTORY` (e.g. 10)               |
| latency on huge tables             | rebuild IVFFlat with more lists (200 → 1000)      |

---

## Project layout

```
flowprov/
├── alembic.ini                          Alembic configuration
├── docker-compose.yml                   Postgres + pgvector (+ optional n8n)
├── Makefile                             one-liner ops
├── pyproject.toml                       package + deps
├── README.md                            you are here
├── .env.example                         template; copy to .env
│
├── flowprov/                            the application
│   ├── __init__.py
│   ├── config.py                        pydantic-settings (reads .env)
│   ├── db.py                            async SQLAlchemy engine + session
│   ├── models.py                        ORM models (matches migration 001)
│   ├── schemas.py                       pydantic v2 request/response schemas
│   ├── embeddings.py                    sentence-transformers + canonical hash
│   ├── llm.py                           fake + openai LLM clients
│   ├── drift.py                         two-tier drift detection engine
│   ├── service.py                       provenance ingest service
│   ├── replay.py                        execution replay service
│   ├── notify.py                        optional Slack webhook
│   ├── cli.py                           typer CLI (`flowprov health`, `flowprov flows`)
│   └── api/
│       ├── __init__.py
│       ├── app.py                       FastAPI factory + lifespan
│       ├── routes_ingest.py             /api/ingest, /api/replay, /api/drift
│       ├── routes_dashboard.py          /, /flows/{id}, /executions/{id}/replay
│       ├── static/                      (served at /static)
│       └── templates/
│           ├── base.html
│           ├── index.html
│           ├── flow_detail.html
│           └── replay.html
│
├── migrations/
│   ├── env.py
│   ├── script.py.mako
│   └── versions/
│       └── 001_initial_schema.py
│
├── examples/
│   ├── __init__.py
│   ├── flow_simulator/                  the demo runner
│   │   ├── __init__.py
│   │   ├── flows.py                     5 realistic flow definitions
│   │   ├── run.py                       `make demo`
│   │   └── inject_drift.py              `make demo-drift`
│   └── n8n_workflows/
│       ├── README.md                    wiring guide
│       └── 01_triage.json               importable n8n workflow
│
├── tests/
│   ├── __init__.py
│   ├── conftest.py
│   ├── test_embeddings.py               unit tests, no DB
│   ├── test_llm.py                      unit tests, no DB
│   └── test_service.py                  integration tests, needs DB
│
└── scripts/
    └── bootstrap.sh                     one-shot bootstrap
```

---

## Migrating from local Postgres to Supabase

The schema is portable — it uses standard Postgres + `pgvector`, both of which Supabase supports natively. To switch:

1. Create a new Supabase project; enable the `vector` extension under **Database → Extensions**.
2. Get the connection string from **Project Settings → Database**. Convert it to asyncpg form:
   ```
   postgresql+asyncpg://postgres:<pw>@db.<ref>.supabase.co:5432/postgres
   ```
3. In `.env`, set `DATABASE_URL` and `DATABASE_URL_SYNC` accordingly.
4. `make migrate` — Alembic creates the same tables in your Supabase project.

The dashboard and API don't care where Postgres lives.

---

## Troubleshooting

### `port 5433 already in use`

Another Postgres is bound to 5433. Either stop it, or edit `docker-compose.yml` to use a different host port (and update `DATABASE_URL` to match).

### `pg_isready` not ready / migrations fail with `could not connect`

```bash
docker compose ps                       # confirm postgres status is "healthy"
docker compose logs postgres --tail=50  # look for actual error
make db-reset                           # nuclear option — drops volume and re-migrates
```

### `sentence-transformers` download fails

This only applies if you opted into the heavy backend (`EMBEDDING_PROVIDER=minilm`). The default `hash` backend has no ML deps. If you need MiniLM and you're firewalled:
```bash
HF_HUB_OFFLINE=1 make demo   # will fail until you pre-download the model
```
To preload manually:
```bash
.venv/bin/python -c "from sentence_transformers import SentenceTransformer as M; M('sentence-transformers/all-MiniLM-L6-v2')"
```

### `ValueError: vector dimension X does not match column dimension 384`

You changed `EMBEDDING_MODEL` to one with a different dim. Update the `Vector(384)` in `migrations/versions/001_initial_schema.py` AND `models.py`, then `make db-reset`.

### Tests skipped or fail with `connection refused`

The integration tests (`tests/test_service.py`) need the DB. Bring it up first:
```bash
make db-up && make migrate && make test
```

### "Drift detected during baseline run"

The fake LLM is deterministic at temperature 0 but its templates introduce some variance across same-intent prompts. If you see drift during `make demo`, raise `DRIFT_SOFT_STD_MULTIPLIER` to 3.5 in `.env`, run `make db-reset` and try again.

---

## License

MIT.
