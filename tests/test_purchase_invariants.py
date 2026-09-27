"""Integration checks for the PostgreSQL allocation and idempotency invariants."""

import asyncio
from uuid import uuid4

import pytest

from ticket_stampede.config import Settings
from ticket_stampede.db import build_engine
from ticket_stampede.service import buy_ticket, create_schema, reset_sale, sale_status


@pytest.fixture
async def engine():  # type: ignore[no-untyped-def]
    settings = Settings()
    database_url = str(settings.test_database_url or settings.database_url)
    test_engine = build_engine(database_url)
    await create_schema(test_engine)
    try:
        yield test_engine
    finally:
        await test_engine.dispose()


@pytest.mark.integration
async def test_same_request_id_concurrently_returns_one_ticket(engine) -> None:  # type: ignore[no-untyped-def]
    await reset_sale(engine, 1)
    request_id = str(uuid4())

    results = await asyncio.gather(
        buy_ticket(engine, "alice", request_id),
        buy_ticket(engine, "alice", request_id),
    )

    assert results == [(True, 1), (True, 1)]
    assert (await sale_status(engine))["number_sold"] == 1


@pytest.mark.integration
async def test_exact_capacity_has_unique_ticket_numbers(engine) -> None:  # type: ignore[no-untyped-def]
    capacity = 100
    await reset_sale(engine, capacity)

    results = await asyncio.gather(
        *(buy_ticket(engine, f"user-{index}", str(uuid4())) for index in range(capacity))
    )
    status = await sale_status(engine)
    ticket_numbers = [ticket["ticket_number"] for ticket in status["tickets"]]

    assert all(issued for issued, _ in results)
    assert status["number_sold"] == capacity
    assert sorted(ticket_numbers) == list(range(1, capacity + 1))


@pytest.mark.integration
async def test_excess_concurrent_purchases_do_not_oversell(engine) -> None:  # type: ignore[no-untyped-def]
    capacity = 100
    await reset_sale(engine, capacity)

    results = await asyncio.gather(
        *(buy_ticket(engine, f"user-{index}", str(uuid4())) for index in range(150))
    )
    status = await sale_status(engine)

    assert sum(issued for issued, _ in results) == capacity
    assert sum(not issued for issued, _ in results) == 50
    assert status["number_sold"] == capacity


@pytest.mark.integration
async def test_completed_request_is_replayed_and_cross_user_reuse_is_rejected(engine) -> None:  # type: ignore[no-untyped-def]
    await reset_sale(engine, 2)
    request_id = str(uuid4())

    first = await buy_ticket(engine, "alice", request_id)
    replay = await buy_ticket(engine, "alice", request_id)

    assert first == replay
    with pytest.raises(ValueError, match="cannot be reused by a different user_id"):
        await buy_ticket(engine, "bob", request_id)
    assert (await sale_status(engine))["number_sold"] == 1
