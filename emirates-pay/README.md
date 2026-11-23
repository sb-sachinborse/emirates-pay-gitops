# Emirates Pay (demo wallet app)

A small AED wallet API with a bilingual (English / Arabic RTL) web UI. It is the **application** for the
UAE-focused GitOps project: the code is deliberately simple, and the platform around it is the portfolio piece.

Features: mock UAE Pass style sign-in, wallet top-up, wallet-to-wallet transfers with a **0.5% fee (min AED 1.00) plus
5% VAT on the fee**, double-entry ledger, idempotent transfers, transaction history, health/readiness probes,
Prometheus metrics, JSON logs, and built-in failure injection for demos.

> Demo only. There is no real UAE Pass integration and no real money. Do not expose it to the internet as-is.

## Run it

```bash
# 1. locally (needs Python 3.10+; Flask is the only dependency for dev)
pip install -r requirements.txt
make run                 # http://localhost:8080
make test                # 25 tests
make smoke               # end-to-end check against the running app

# 2. in Docker
docker compose up --build        # http://localhost:8080
```

## API

| Method and path | Auth | Purpose |
|---|---|---|
| `GET /health` | no | Liveness probe |
| `GET /ready` | no | Readiness probe (checks the database) |
| `GET /metrics` | no | Prometheus metrics |
| `GET /api/version` | no | Version, git SHA, env, whether fault injection is on |
| `POST /api/auth/uaepass-mock` | no | `{name, email}` returns a token and wallet (creates one if new) |
| `GET /api/me` | yes | Profile and balance |
| `GET /api/quote?amount=100` | no | Fee, VAT and total for a transfer |
| `POST /api/wallet/topup` | yes | `{amount}` (max AED 10,000) |
| `POST /api/transfer` | yes | `{to_wallet, amount, note}` plus optional `Idempotency-Key` header (max AED 20,000) |
| `GET /api/transactions` | yes | Last 50 transactions |

Errors always look like `{"error": {"code": "insufficient_funds", "message": "..."}}`.

## Configuration (environment variables)

| Variable | Default | Notes |
|---|---|---|
| `APP_ENV` | `development` (image: `production`) | In `production`, the app refuses to start without `SECRET_KEY` |
| `SECRET_KEY` | none | Signs auth tokens. Comes from Secret Manager in the GitOps setup |
| `DB_PATH` | `data/emirates_pay.db` | SQLite file (image: `/data/emirates_pay.db`) |
| `APP_VERSION`, `GIT_SHA` | `dev`, `local` | Set at image build time; shown in the UI footer and `/api/version` |
| `FAULT_RATE` | `0` | Share (0 to 1) of `/api` calls that return HTTP 500 |
| `FAULT_LATENCY_MS` | `0` | Artificial delay added to `/api` calls |
| `TOKEN_TTL_SECONDS` | `28800` | Token lifetime |
| `LOG_LEVEL` | `INFO` | Logs are one JSON object per line on stdout |

## Design decisions worth explaining in an interview

- **Money is integer fils**, never floats. Fee and VAT use integer half-up rounding.
- **Double-entry ledger**: every transaction writes balanced debit and credit rows (wallet, `revenue:fees`,
  `liability:vat`). A test asserts debits equal credits and that no money is created or lost.
- **Concurrency safety**: transfers run in `BEGIN IMMEDIATE` transactions. A test fires 12 parallel transfers at
  a balance that covers only 5 and proves exactly 5 succeed.
- **Idempotency**: retrying a transfer with the same `Idempotency-Key` returns the original result (HTTP 200)
  instead of charging twice. Reusing a key with a different payload is rejected (422). The UI reuses the key
  when a network error interrupts a send.
- **Security basics**: signed expiring tokens, strict CSP (no inline scripts), security headers, non-root container
  with a numeric UID, no secrets in the image, fail-closed `SECRET_KEY` in production.
- **Failure injection** (`FAULT_RATE`, `FAULT_LATENCY_MS`) exists so you can later demo canary auto-rollback,
  alerts firing and SLO burn without writing a "broken" version of the code.

## Known limits (each becomes a GitOps project step)

| Limit | Why | Planned fix |
|---|---|---|
| SQLite, single replica | One file cannot be shared by several pods | Swap to PostgreSQL (Cloud SQL / RDS) before scaling replicas |
| One gunicorn worker (threads only) | SQLite and in-process metrics need one process | Goes away with Postgres + `prometheus_client` multiprocess mode |
| Mock authentication | Demo only | Put a real identity provider in front |
| Token in `sessionStorage` | Fine for a demo | Use short-lived cookies (`HttpOnly`, `SameSite`) in real systems |
| No rate limiting, no TLS | Handled by the platform | Ingress rate limits and cert-manager TLS |

## What the platform (GitOps repo) needs from this app

- Image listens on **8080**, runs as **UID 10001** (`runAsNonRoot` works), writes only to `/data`.
- Probes: liveness `GET /health`, readiness `GET /ready`.
- Metrics: scrape `GET /metrics`. Useful for canary analysis:
  `http_requests_total{status=~"5.."}` and `http_request_duration_seconds_bucket`.
- Version visibility: the rollout is visible in the UI footer and `/api/version`
  (build with `--build-arg APP_VERSION=1.0.1 --build-arg GIT_SHA=$(git rev-parse --short HEAD)`).

## Layout

```
app/            main.py (routes), service.py (money logic), money.py, db.py, metrics.py, static/ (UI)
tests/          25 unit and integration tests (unittest, no extra dependencies)
scripts/        smoke.sh (end-to-end check, usable as a post-deploy gate)
Dockerfile, docker-compose.yml, Makefile
```
