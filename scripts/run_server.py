"""Start one Ticket Stampede API instance with Windows-compatible PostgreSQL support."""

import argparse
import asyncio

import uvicorn

from ticket_stampede.runtime import configure_event_loop

configure_event_loop()
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--port", type=int, default=8000)
args = parser.parse_args()
uvicorn.run(
    "ticket_stampede.main:app",
    host="127.0.0.1",
    port=args.port,
    loop=asyncio.SelectorEventLoop,
)
