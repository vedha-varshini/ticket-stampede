# Ticket Stampede

A FastAPI and PostgreSQL ticket seller built to demonstrate safe allocation during a
high-concurrency sale. A sale has fixed inventory, each successful ticket number is
unique, repeated requests return their original durable result, and `/status` derives
its count from the issued records.

See [DECISIONS.md](DECISIONS.md) for design choices and [REPORT.md](REPORT.md) for the
intentional naive failure and passing PostgreSQL experiments.

## Prerequisites

- Python 3.12
- PostgreSQL 18 running on `127.0.0.1:5432`
- A PostgreSQL database available to the connection string in `.env`

## Run locally

From PowerShell at the repository root:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e ".[dev,load]"
Copy-Item .env.example .env
```

Set `DATABASE_URL` in `.env` to your PostgreSQL database. Set
`TEST_DATABASE_URL` to a dedicated database if available; otherwise the integration
tests use `DATABASE_URL`. Do not commit `.env`.

Start the API:

```powershell
.\.venv\Scripts\python.exe scripts/run_server.py
```

In another terminal, create a 100-ticket sale and inspect it:

```powershell
Invoke-RestMethod -Method Post http://127.0.0.1:8000/reset -ContentType application/json -Body '{"ticket_count":100}'
Invoke-RestMethod http://127.0.0.1:8000/status
```

Endpoints:

- `POST /reset` with `{ "ticket_count": 100 }`
- `POST /buy` with `{ "user_id": "alice", "request_id": "a-client-generated-id" }`
- `GET /status`

## Verification

The test suite uses PostgreSQL and resets its selected test database during the
purchase-invariant tests. Do not point `TEST_DATABASE_URL` at data you need to keep.

```powershell
.\.venv\Scripts\python.exe -m pytest
```

Run the HTTP edge-case checks while the server is running:

```powershell
.\.venv\Scripts\python.exe scripts/run_edge_cases.py
```

Run the reusable workload (it resets the sale first):

```powershell
.\.venv\Scripts\python.exe scripts/run_load.py --capacity 100 --requests 500 --concurrency 250 --duplicate-request-every 10
```

Its report includes requests sent, unique request IDs, issued/sold-out/failed
responses, requests/sec, median and p99 client latency, final status count, duplicate
ticket/request IDs, and oversell detection.

## Three-process check

Start three terminals, one for each port:

```powershell
.\.venv\Scripts\python.exe scripts/run_server.py --port 8000
.\.venv\Scripts\python.exe scripts/run_server.py --port 8001
.\.venv\Scripts\python.exe scripts/run_server.py --port 8002
```

Then run:

```powershell
.\.venv\Scripts\python.exe scripts/run_three_instance_load.py
```

The script deliberately sends calls across all three processes sharing the one
PostgreSQL database. It is a coordination check, not a substitute for a real load
balancer.

## Submission note

Place the exported Codex/AI session transcript required by the assignment in
[`logs/`](logs/README.md) before submitting. Local `server*.log` files are excluded
because they are runtime output rather than the required session logs.

