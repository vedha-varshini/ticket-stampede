"""Correct PostgreSQL-backed Ticket Stampede API."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncEngine

from .config import Settings
from .db import build_engine
from .runtime import configure_event_loop
from .service import buy_ticket, create_schema, reset_sale, sale_status

configure_event_loop()


class ResetRequest(BaseModel):
    ticket_count: int = Field(gt=0, le=10_000)


class ResetResponse(BaseModel):
    sale_id: str
    capacity: int


class BuyRequest(BaseModel):
    user_id: str = Field(min_length=1, max_length=128)
    request_id: str = Field(min_length=1, max_length=128)


class BuyResponse(BaseModel):
    outcome: str
    ticket_number: int | None = None


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = Settings()
    engine = build_engine(str(settings.database_url))
    app.state.engine = engine
    app.state.settings = settings
    await create_schema(engine)
    try:
        yield
    finally:
        await engine.dispose()


app = FastAPI(title="Ticket Stampede", version="0.1.0", lifespan=lifespan)


def _engine(request: Request) -> AsyncEngine:
    return request.app.state.engine  # type: ignore[no-any-return]


@app.post("/reset", response_model=ResetResponse, status_code=status.HTTP_201_CREATED)
async def reset(payload: ResetRequest, request: Request) -> ResetResponse:
    sale_id = await reset_sale(_engine(request), payload.ticket_count)
    return ResetResponse(sale_id=str(sale_id), capacity=payload.ticket_count)


@app.post("/buy", response_model=BuyResponse)
async def buy(payload: BuyRequest, request: Request) -> BuyResponse:
    try:
        issued, ticket_number = await buy_ticket(
            _engine(request), payload.user_id, payload.request_id
        )
    except LookupError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error

    if not issued:
        return BuyResponse(outcome="sold_out")
    return BuyResponse(outcome="issued", ticket_number=ticket_number)


@app.get("/status")
async def get_status(request: Request) -> dict[str, object]:
    try:
        return await sale_status(_engine(request))
    except LookupError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
