"""Windows compatibility for psycopg's asynchronous driver."""

import asyncio
import sys


def configure_event_loop() -> None:
    """Use SelectorEventLoop on Windows, which psycopg async requires."""
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
