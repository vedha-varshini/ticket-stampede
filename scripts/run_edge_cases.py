"""Exercise the required purchase edge cases against a running local API."""

import asyncio
import json
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass
from typing import Any
from uuid import uuid4

import httpx

BASE_URL = "http://127.0.0.1:8000"


@dataclass
class CaseResult:
    name: str
    passed: bool
    details: dict[str, Any]


async def reset(client: httpx.AsyncClient, capacity: int) -> None:
    response = await client.post("/reset", json={"ticket_count": capacity})
    response.raise_for_status()


async def buy(client: httpx.AsyncClient, user_id: str, request_id: str) -> httpx.Response:
    return await client.post("/buy", json={"user_id": user_id, "request_id": request_id})


async def status(client: httpx.AsyncClient) -> dict[str, Any]:
    response = await client.get("/status")
    response.raise_for_status()
    return response.json()


async def concurrent_duplicate(client: httpx.AsyncClient) -> CaseResult:
    await reset(client, 1)
    request_id = str(uuid4())
    responses = await asyncio.gather(
        buy(client, "alice", request_id), buy(client, "alice", request_id)
    )
    payloads = [response.json() for response in responses]
    final_status = await status(client)
    passed = (
        all(response.status_code == 200 for response in responses)
        and {payload["ticket_number"] for payload in payloads} == {1}
        and final_status["number_sold"] == 1
    )
    return CaseResult(
        "duplicate request_id concurrently",
        passed,
        {"responses": payloads, "status_number_sold": final_status["number_sold"]},
    )


async def exact_capacity(client: httpx.AsyncClient) -> CaseResult:
    await reset(client, 100)
    responses = await asyncio.gather(
        *(buy(client, f"user-{index}", str(uuid4())) for index in range(100))
    )
    final_status = await status(client)
    numbers = [ticket["ticket_number"] for ticket in final_status["tickets"]]
    all_issued = all(
        response.status_code == 200 and response.json()["outcome"] == "issued"
        for response in responses
    )
    passed = (
        all_issued
        and final_status["number_sold"] == 100
        and len(set(numbers)) == 100
    )
    return CaseResult(
        "exactly 100 successful purchases",
        passed,
        {"issued": 100, "status_number_sold": final_status["number_sold"]},
    )


async def above_capacity(client: httpx.AsyncClient) -> CaseResult:
    await reset(client, 100)
    responses = await asyncio.gather(
        *(buy(client, f"user-{index}", str(uuid4())) for index in range(150))
    )
    outcomes = [
        response.json().get("outcome") for response in responses if response.status_code == 200
    ]
    final_status = await status(client)
    numbers = [ticket["ticket_number"] for ticket in final_status["tickets"]]
    passed = (
        outcomes.count("issued") == 100
        and outcomes.count("sold_out") == 50
        and final_status["number_sold"] == 100
        and len(numbers) == len(set(numbers))
    )
    return CaseResult(
        "more than 100 concurrent purchases",
        passed,
        {
            "issued": outcomes.count("issued"),
            "sold_out": outcomes.count("sold_out"),
            "status_number_sold": final_status["number_sold"],
        },
    )


async def sequential_duplicate(client: httpx.AsyncClient) -> CaseResult:
    await reset(client, 1)
    request_id = str(uuid4())
    first = await buy(client, "alice", request_id)
    second = await buy(client, "alice", request_id)
    final_status = await status(client)
    passed = (
        first.status_code == second.status_code == 200
        and first.json() == second.json()
        and final_status["number_sold"] == 1
    )
    return CaseResult(
        "duplicate request_id after completion",
        passed,
        {
            "first_response": first.json(),
            "second_response": second.json(),
            "status_number_sold": final_status["number_sold"],
        },
    )


async def cross_user_duplicate(client: httpx.AsyncClient) -> CaseResult:
    await reset(client, 2)
    request_id = str(uuid4())
    first = await buy(client, "alice", request_id)
    second = await buy(client, "bob", request_id)
    final_status = await status(client)
    passed = (
        first.status_code == 200
        and second.status_code == 409
        and final_status["number_sold"] == 1
        and final_status["tickets"][0]["user_id"] == "alice"
    )
    return CaseResult(
        "same request_id from different users",
        passed,
        {
            "first_status": first.status_code,
            "second_status": second.status_code,
            "second_response": second.json(),
            "status_number_sold": final_status["number_sold"],
        },
    )


async def main() -> None:
    cases: list[CallableCase] = [
        concurrent_duplicate,
        exact_capacity,
        above_capacity,
        sequential_duplicate,
        cross_user_duplicate,
    ]
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30) as client:
        results = [await case(client) for case in cases]
    print(json.dumps([asdict(result) for result in results], indent=2))
    if not all(result.passed for result in results):
        raise SystemExit(1)


CallableCase = Callable[[httpx.AsyncClient], Awaitable[CaseResult]]


if __name__ == "__main__":
    asyncio.run(main())
