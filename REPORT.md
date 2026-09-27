# Ticket Stampede experiment report

All figures below were produced locally against PostgreSQL 18 on `127.0.0.1:5432`.
They are evidence for this machine, not a capacity claim for production hardware.

## Naive baseline (intentionally unsafe)

The first implementation read a shared `sold_count`, chose `sold_count + 1`, then
inserted and updated separately. With capacity 100, 500 requests, concurrency 250,
and a repeated request every ten calls, it produced:

| Measure | Result |
| --- | ---: |
| Requests / unique request IDs | 500 / 451 |
| Issued / sold out / failed responses | 238 / 262 / 0 |
| Final actual issued rows / capacity | 238 / 100 |
| Duplicate ticket-number groups / extra duplicated rows | 67 / 138 |
| Duplicate request-ID groups / extra duplicated rows | 11 / 11 |
| Final counter | 100 |
| Oversold | yes |

This is the expected race: independent transactions read the same count before any
write commits. The counter's final value is only the last overwritten update, while
ticket rows are the actual issued records.

## Corrected result

The same workload using inventory row locks and durable idempotency produced 100 sold
for capacity 100, no duplicate ticket numbers, no duplicate stored request IDs, and
no oversell. It completed in 13.785 seconds (36.27 requests/sec). There were 115
`issued` responses because repeat calls replay an existing issued outcome; only 100
distinct tickets were stored.

The HTTP edge-case harness passed: concurrent duplicate replay returned ticket 1
twice but left one issued row; exactly 100 concurrent requests issued 100 tickets;
150 concurrent requests yielded 100 issued and 50 sold out; a completed request
replayed its original result; and another user reusing that ID received HTTP 409.

## Local performance sweep

Each level used a fresh 100-ticket sale and 100 unique purchases. No level reported a
failure or exceeded 100 tickets.

| Concurrency | Requests/sec | Median ms | p99 ms |
| ---: | ---: | ---: | ---: |
| 1 | 49.68 | 18.97 | 31.85 |
| 5 | 83.58 | 49.80 | 230.15 |
| 10 | 64.26 | 120.16 | 362.69 |
| 25 | 48.49 | 351.04 | 1574.28 |
| 50 | 105.99 | 352.60 | 834.40 |
| 75 | 99.19 | 523.22 | 897.65 |
| 100 | 109.12 | 620.33 | 793.25 |
| 150 | 71.11 | 880.14 | 1264.18 |
| 200 | 47.95 | 1231.52 | 1876.98 |
| 250 | 50.38 | 1138.71 | 1740.84 |

Tail latency becomes visibly worse around 25 concurrent clients on this local setup;
throughput is noisy because the API, client, and database share one Windows machine.

## Three seller processes

Three FastAPI processes on ports 8000–8002 shared the same PostgreSQL database. A
client distributed 500 requests (250 concurrent, 451 distinct request IDs) nearly
evenly: 167, 167, and 166 calls. It recorded 111 issued-response replays, 389 sold-out
responses, zero failures, and 100 final issued tickets with no duplicate ticket or
request IDs. This validates shared-database coordination across processes, though the
test client distributes requests directly; it is not a real load-balancer benchmark.
