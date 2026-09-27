"""Application bootstrap verification without any business routes."""

from ticket_stampede.main import app


def test_fastapi_application_metadata() -> None:
    assert app.title == "Ticket Stampede"
    assert app.version == "0.1.0"
