"""Distribute a concurrent buy test across three seller instances sharing PostgreSQL."""

import asyncio
import json
from collections import Counter
from time import perf_counter
from uuid import uuid4

import httpx

BASE_URLS = [
    "http://127.0.0.1:8000",
    "http://127.0.0.1:8001",
    "http://127.0.0.1:8002",
]
CAPACITY = 100
REQUESTS = 500
CONCURRENCY = 250
DUPLICATE_REQUEST_EVERY = 10


async def main() -> None:
    async with httpx.AsyncClient(timeout=60) as client:
        reset = await client.post(f"{BASE_URLS[0]}/reset", json={"ticket_count": CAPACITY})
        reset.raise_for_status()

        semaphore = asyncio.Semaphore(CONCURRENCY)
        instance_calls: Counter[str] = Counter()

        payloads: list[tuple[str, str]] = []
        for index in range(REQUESTS):
            if index and index % DUPLICATE_REQUEST_EVERY == 0:
                payloads.append(payloads[index - 1])
            else:
                payloads.append((f"multi-user-{index}", str(uuid4())))

        async def buy(index: int, user_id: str, request_id: str) -> tuple[int, str]:
            base_url = BASE_URLS[index % len(BASE_URLS)]
            async with semaphore:
                response = await client.post(
                    f"{base_url}/buy",
                    json={"user_id": user_id, "request_id": request_id},
                )
            instance_calls[base_url] += 1
            return response.status_code, str(response.json().get("outcome"))

        started = perf_counter()
        buy_tasks = (
            buy(index, user_id, request_id)
            for index, (user_id, request_id) in enumerate(payloads)
        )
        responses = await asyncio.gather(*buy_tasks)
        elapsed = perf_counter() - started
        status_response = await client.get(f"{BASE_URLS[1]}/status")
        status_response.raise_for_status()
        final_status = status_response.json()

    ticket_numbers = [ticket["ticket_number"] for ticket in final_status["tickets"]]
    request_ids = [ticket["request_id"] for ticket in final_status["tickets"]]
    report = {
        "instances": instance_calls,
        "requests_sent": REQUESTS,
        "unique_request_ids": len(set(payloads)),
        "concurrency": CONCURRENCY,
        "issued_responses": sum(outcome == "issued" for _, outcome in responses),
        "sold_out_responses": sum(outcome == "sold_out" for _, outcome in responses),
        "failed_responses": sum(status != 200 for status, _ in responses),
        "requests_per_second": round(REQUESTS / elapsed, 2),
        "status_number_sold": final_status["number_sold"],
        "capacity": final_status["capacity"],
        "duplicate_ticket_numbers": _duplicates(ticket_numbers),
        "duplicate_request_ids": _duplicates(request_ids),
        "oversold": final_status["number_sold"] > final_status["capacity"],
    }
    print(json.dumps(report, indent=2))
    print("FINAL_STATUS")
    print(json.dumps(final_status, indent=2))


def _duplicates(values: list[int] | list[str]) -> dict[int, int] | dict[str, int]:
    counts = Counter(values)
    return {value: count for value, count in counts.items() if count > 1}


if __name__ == "__main__":
    asyncio.run(main())
