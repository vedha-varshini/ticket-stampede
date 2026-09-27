# Ticket Stampede decisions

## Architecture and rejected alternatives

The seller is a FastAPI process backed by PostgreSQL. PostgreSQL is the correctness
boundary: multiple FastAPI processes may use the same database, so the solution does
not depend on an in-memory counter or an application-level mutex. SQLAlchemy uses the
`psycopg` async driver, and each `POST /buy` is one database transaction.

I rejected a simple `sold_count` read, followed by an insert/update. Under PostgreSQL's
normal `READ COMMITTED` isolation, concurrent requests can all read the same count and
all decide stock remains. That was intentionally demonstrated in the naive version:
500 requests at concurrency 250 produced 238 issued rows for a 100-ticket sale. The
counter happened to finish at 100 because lost updates overwrote one another; it was
not evidence that only 100 tickets had been issued.

I also did not use a single locked sale-counter row. It can be correct when an atomic
conditional update is used, but serializes every purchase behind one hot row and does
not itself identify a ticket number. Instead, `/reset` materializes inventory rows
`1..capacity`. Each buyer locks one available row with `FOR UPDATE SKIP LOCKED`, marks
it issued, and records the request outcome in the same transaction. This gives each
successful buyer a distinct durable resource while allowing buyers of different rows
to proceed.

## Correctness boundary

`purchase_requests` has primary key `(sale_id, request_id)`. The request record is
inserted first. Its owner allocates a ticket; a duplicate waits for the unique-key
winner to commit and then reads that stored result. Reusing a request ID with another
user is rejected with HTTP 409. `UNIQUE(sale_id, ticket_number)` adds a database-level
backstop, and the foreign key points every issued request at real inventory.

`GET /status` is derived from committed `issued` request records, rather than a
separate counter. Its count and holder list therefore have one source of truth.

The key trade-off is the short locking transaction and a relational schema for only
one sale at a time. It is intentionally simple for the assignment. The design uses
`SKIP LOCKED`, so a buyer can receive `sold_out` if every currently available row is
locked even if another transaction later rolls back. With this short transaction,
that window is small; a production design could retry a bounded number of times.

## Evidence and tests

`tests/test_purchase_invariants.py` checks concurrent idempotency, exact capacity,
over-capacity concurrency, sequential replay, and cross-user request-ID reuse against
PostgreSQL. `scripts/run_load.py` reports requests/sec, median and p99 client latency,
and duplicate/oversell checks. `scripts/run_edge_cases.py` exercises the same cases
over HTTP.

The corrected 500-request / 250-concurrency run finished with 100 tickets sold,
zero duplicate ticket numbers, zero duplicate stored request IDs, and no oversell.
The three-process experiment (ports 8000–8002, shared PostgreSQL) also finished with
100 sold and no invariant failure. Details and measured performance are in
[`REPORT.md`](REPORT.md).

## What breaks and the next two weeks

`/reset` deletes and recreates all sale state. It is a test/admin endpoint and must
not run while purchases are in flight; a production service would create a new sale
record and retire the old one instead. There is no authentication, rate limiting,
observability pipeline, migration history, retry policy, or load balancer in this
take-home implementation.

Next, I would add Alembic migrations and an explicit sale lifecycle; run the three
instances behind a real reverse proxy; add database and request telemetry; and run a
longer benchmark that deliberately injects PostgreSQL latency. I would then decide
whether connection-pool sizing or the inventory-row selection is the first measured
bottleneck, rather than claiming a bottleneck from a short local run.
