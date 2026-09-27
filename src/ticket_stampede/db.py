"""PostgreSQL engine construction and a minimal connectivity probe."""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


def build_engine(database_url: str) -> AsyncEngine:
    """Create the application's PostgreSQL engine without opening a connection yet."""
    return create_async_engine(database_url, pool_pre_ping=True)


def build_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Create the dependency-ready session factory; endpoint wiring comes later."""
    return async_sessionmaker(engine, expire_on_commit=False)


async def check_database_connection(database_url: str) -> tuple[int, str]:
    """Run a read-only probe used by the environment verification test."""
    engine = build_engine(database_url)
    try:
        async with engine.connect() as connection:
            result = await connection.execute(text("SELECT 1, current_database()"))
            row = result.one()
            return int(row[0]), str(row[1])
    finally:
        await engine.dispose()

