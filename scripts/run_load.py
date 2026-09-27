"""Load-test the correct Ticket Stampede seller and verify final invariants."""

import argparse
import asyncio
from collections import Counter
from dataclasses import asdict, dataclass
from statistics import median
from time import perf_counter
from uuid import uuid4

import httpx


@dataclass
class LoadReport:
    requests_sent: int
    unique_request_ids: int
    issued_responses: int
    sold_out_responses: int
    failed_responses: int
    elapsed_seconds: float
    requests_per_second: float
    median_latency_ms: float
    p99_latency_ms: float
    status_number_sold: int
    capacity: int
    duplicate_ticket_numbers: dict[int, int]
    duplicate_request_ids: dict[str, int]
    oversold: bool


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--capacity", type=int, default=100)
    parser.add_argument("--requests", type=int, default=500)
    parser.add_argument("--concurrency", type=int, default=250)
    parser.add_argument("--duplicate-request-every", type=int, default=0)
    args = parser.parse_args()

    limits = httpx.Limits(
        max_connections=args.concurrency,
        max_keepalive_connections=args.concurrency,
    )
    async with httpx.AsyncClient(base_url=args.base_url, limits=limits, timeout=60) as client:
        reset = await client.post("/reset", json={"ticket_count": args.capacity})
        reset.raise_for_status()
        requests = _requests(args.requests, args.duplicate_request_every)
        started = perf_counter()
        responses = await _send_requests(client, requests, args.concurrency)
        elapsed = perf_counter() - started
        status_response = await client.get("/status")
        status_response.raise_for_status()
        sale_status = status_response.json()

    outcomes = [outcome for outcome, _ in responses]
    latencies = sorted(latency for _, latency in responses)
    ticket_numbers = [ticket["ticket_number"] for ticket in sale_status["tickets"]]
    stored_request_ids = [ticket["request_id"] for ticket in sale_status["tickets"]]
    report = LoadReport(
        requests_sent=args.requests,
        unique_request_ids=len({request_id for _, request_id in requests}),
        issued_responses=outcomes.count("issued"),
        sold_out_responses=outcomes.count("sold_out"),
        failed_responses=outcomes.count("failed"),
        elapsed_seconds=round(elapsed, 3),
        requests_per_second=round(args.requests / elapsed, 2),
        median_latency_ms=round(median(latencies), 2),
        p99_latency_ms=round(_percentile(latencies, 0.99), 2),
        status_number_sold=sale_status["number_sold"],
        capacity=sale_status["capacity"],
        duplicate_ticket_numbers=_duplicates(ticket_numbers),
        duplicate_request_ids=_duplicates(stored_request_ids),
        oversold=sale_status["number_sold"] > sale_status["capacity"],
    )
    print(asdict(report))
    print("FINAL_STATUS")
    print(sale_status)


def _requests(total: int, duplicate_every: int) -> list[tuple[str, str]]:
    generated: list[tuple[str, str]] = []
    for index in range(total):
        if duplicate_every and index and index % duplicate_every == 0:
            generated.append(generated[index - 1])
        else:
            generated.append((f"user-{index}", str(uuid4())))
    return generated


async def _send_requests(
    client: httpx.AsyncClient, requests_to_send: list[tuple[str, str]], concurrency: int
) -> list[tuple[str, float]]:
    semaphore = asyncio.Semaphore(concurrency)

    async def send(user_id: str, request_id: str) -> tuple[str, float]:
        async with semaphore:
            started = perf_counter()
            try:
                response = await client.post(
                    "/buy", json={"user_id": user_id, "request_id": request_id}
                )
            except httpx.HTTPError:
                return "failed", (perf_counter() - started) * 1_000
            latency_ms = (perf_counter() - started) * 1_000
            if response.status_code != 200:
                return "failed", latency_ms
            return str(response.json().get("outcome")), latency_ms

    coroutines = (send(user_id, request_id) for user_id, request_id in requests_to_send)
    return await asyncio.gather(*coroutines)


def _percentile(values: list[float], percentile: float) -> float:
    index = max(0, min(len(values) - 1, int(len(values) * percentile + 0.999_999) - 1))
    return values[index]


def _duplicates(values: list[int] | list[str]) -> dict[int, int] | dict[str, int]:
    counts = Counter(values)
    return {value: count for value, count in counts.items() if count > 1}


if __name__ == "__main__":
    asyncio.run(main())
