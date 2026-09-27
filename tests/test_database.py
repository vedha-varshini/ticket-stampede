"""Read-only PostgreSQL environment verification."""

import pytest
from pydantic import ValidationError

from ticket_stampede.config import Settings
from ticket_stampede.db import check_database_connection


@pytest.mark.integration
async def test_postgresql_connection() -> None:
    try:
        settings = Settings()
    except ValidationError:
        pytest.skip("Set TEST_DATABASE_URL or DATABASE_URL in .env to run the PostgreSQL check.")

    database_url = str(settings.test_database_url or settings.database_url)
    probe_value, database_name = await check_database_connection(database_url)

    assert probe_value == 1
    assert database_name
