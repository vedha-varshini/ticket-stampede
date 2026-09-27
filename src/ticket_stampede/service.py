"""Transactional PostgreSQL ticket allocation and idempotent purchase operations."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import delete, insert, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine

from .schema import metadata, purchase_requests, sales, tickets


async def create_schema(engine: AsyncEngine) -> None:
    """Create missing tables without modifying state shared by other API instances."""
    async with engine.begin() as connection:
        await connection.run_sync(metadata.create_all)


async def reset_sale(engine: AsyncEngine, capacity: int) -> UUID:
    """Start a fresh sale with exactly one available row per ticket."""
    sale_id = uuid4()
    async with engine.begin() as connection:
        await connection.execute(delete(purchase_requests))
        await connection.execute(delete(tickets))
        await connection.execute(delete(sales))
        await connection.execute(
            insert(sales).values(sale_id=sale_id, capacity=capacity, is_active=True)
        )
        await connection.execute(
            insert(tickets),
            [
                {"sale_id": sale_id, "ticket_number": ticket_number, "state": "available"}
                for ticket_number in range(1, capacity + 1)
            ],
        )
    return sale_id


async def buy_ticket(
    engine: AsyncEngine, user_id: str, request_id: str
) -> tuple[bool, int | None]:
    """Return the same durable outcome for repeat requests and issue one ticket at most once."""
    async with engine.begin() as connection:
        sale = (
            await connection.execute(select(sales).where(sales.c.is_active).limit(1))
        ).mappings().one_or_none()
        if sale is None:
            raise LookupError("No active sale. Call /reset first.")
        sale_id = sale["sale_id"]

        owns_request = False
        # A savepoint lets us handle a duplicate-key error while keeping the
        # surrounding transaction usable. The conflicting INSERT waits until a
        # concurrent winner commits its complete ticket allocation.
        try:
            async with connection.begin_nested():
                await connection.execute(
                    insert(purchase_requests).values(
                        sale_id=sale_id,
                        request_id=request_id,
                        user_id=user_id,
                        outcome="processing",
                    )
                )
            owns_request = True
        except IntegrityError:
            pass

        if not owns_request:
            existing = (
                await connection.execute(
                    select(purchase_requests)
                    .where(
                        purchase_requests.c.sale_id == sale_id,
                        purchase_requests.c.request_id == request_id,
                    )
                    .limit(1)
                )
            ).mappings().one()
            if existing["user_id"] != user_id:
                raise ValueError("request_id cannot be reused by a different user_id")
            return existing["outcome"] == "issued", existing["ticket_number"]

        # The owner locks one available inventory row. SKIP LOCKED allows other
        # buyers to claim different tickets concurrently.
        ticket = (
            await connection.execute(
                select(tickets)
                .where(tickets.c.sale_id == sale_id, tickets.c.state == "available")
                .order_by(tickets.c.ticket_number)
                .limit(1)
                .with_for_update(skip_locked=True)
            )
        ).mappings().one_or_none()

        if ticket is None:
            await connection.execute(
                update(purchase_requests)
                .where(
                    purchase_requests.c.sale_id == sale_id,
                    purchase_requests.c.request_id == request_id,
                )
                .values(outcome="sold_out")
            )
            return False, None

        ticket_number = ticket["ticket_number"]
        await connection.execute(
            update(tickets)
            .where(tickets.c.sale_id == sale_id, tickets.c.ticket_number == ticket_number)
            .values(state="issued")
        )
        await connection.execute(
            update(purchase_requests)
            .where(
                purchase_requests.c.sale_id == sale_id,
                purchase_requests.c.request_id == request_id,
            )
            .values(outcome="issued", ticket_number=ticket_number)
        )
        return True, ticket_number


async def sale_status(engine: AsyncEngine) -> dict[str, object]:
    """Return the count and holders derived from committed issued purchase records."""
    async with engine.connect() as connection:
        sale = (
            await connection.execute(select(sales).where(sales.c.is_active).limit(1))
        ).mappings().one_or_none()
        if sale is None:
            raise LookupError("No active sale. Call /reset first.")

        rows = (
            await connection.execute(
                select(purchase_requests)
                .where(
                    purchase_requests.c.sale_id == sale["sale_id"],
                    purchase_requests.c.outcome == "issued",
                )
                .order_by(purchase_requests.c.ticket_number)
            )
        ).mappings().all()

    ticket_holders = [
        {
            "ticket_number": row["ticket_number"],
            "user_id": row["user_id"],
            "request_id": row["request_id"],
            "issued_at": _timestamp(row["created_at"]),
        }
        for row in rows
    ]
    return {
        "sale_id": str(sale["sale_id"]),
        "capacity": sale["capacity"],
        "number_sold": len(ticket_holders),
        "tickets": ticket_holders,
    }


def _timestamp(value: datetime | None) -> str | None:
    return value.isoformat() if value else None
