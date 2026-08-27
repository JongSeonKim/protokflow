"""A writer-preferring asyncio read-write lock."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager


class AsyncReadWriteLock:
    """Allow concurrent readers while a writer holds exclusive access.

    Readers exclude only writers, so unrelated readers never serialize
    against each other. A waiting writer blocks new readers, so a steady
    stream of readers cannot starve it.

    The lock is bound to the running event loop and is not thread-safe.
    """

    def __init__(self) -> None:
        self._condition = asyncio.Condition()
        self._readers = 0
        self._writing = False
        self._waiting_writers = 0

    @property
    def readers(self) -> int:
        """Number of readers currently holding the lock."""
        return self._readers

    @property
    def writing(self) -> bool:
        """Whether a writer currently holds the lock."""
        return self._writing

    @asynccontextmanager
    async def read(self) -> AsyncIterator[None]:
        """Hold shared access for the duration of the block."""
        async with self._condition:
            await self._condition.wait_for(
                lambda: not self._writing and self._waiting_writers == 0
            )
            self._readers += 1
        try:
            yield
        finally:
            async with self._condition:
                self._readers -= 1
                if self._readers == 0:
                    self._condition.notify_all()

    @asynccontextmanager
    async def write(self) -> AsyncIterator[None]:
        """Hold exclusive access for the duration of the block."""
        async with self._condition:
            self._waiting_writers += 1
            try:
                await self._condition.wait_for(
                    lambda: not self._writing and self._readers == 0
                )
            finally:
                self._waiting_writers -= 1
            self._writing = True
        try:
            yield
        finally:
            async with self._condition:
                self._writing = False
                self._condition.notify_all()
