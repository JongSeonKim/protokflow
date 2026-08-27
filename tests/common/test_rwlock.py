"""Tests for the writer-preferring asyncio read-write lock."""

from __future__ import annotations

import asyncio

from backend.common.rwlock import AsyncReadWriteLock


async def test_readers_run_concurrently() -> None:
    """Two readers overlap instead of serializing against each other."""
    lock = AsyncReadWriteLock()
    both_inside = asyncio.Event()
    observed: list[int] = []

    async def reader() -> None:
        async with lock.read():
            observed.append(lock.readers)
            if lock.readers == 2:
                both_inside.set()
            else:
                await asyncio.wait_for(both_inside.wait(), timeout=1)

    await asyncio.gather(reader(), reader())

    assert both_inside.is_set()
    assert max(observed) == 2


async def test_a_writer_excludes_readers() -> None:
    """A reader cannot enter while a writer holds the lock."""
    lock = AsyncReadWriteLock()
    order: list[str] = []
    writer_entered = asyncio.Event()
    release_writer = asyncio.Event()

    async def writer() -> None:
        async with lock.write():
            order.append("writer-enter")
            writer_entered.set()
            await release_writer.wait()
            order.append("writer-exit")

    async def reader() -> None:
        await writer_entered.wait()
        async with lock.read():
            order.append("reader")

    writer_task = asyncio.ensure_future(writer())
    reader_task = asyncio.ensure_future(reader())
    await writer_entered.wait()
    await asyncio.sleep(0)
    assert order == ["writer-enter"]

    release_writer.set()
    await asyncio.gather(writer_task, reader_task)

    assert order == ["writer-enter", "writer-exit", "reader"]


async def test_writers_exclude_each_other() -> None:
    """Two writers never overlap."""
    lock = AsyncReadWriteLock()
    concurrent = 0
    peak = 0

    async def writer() -> None:
        nonlocal concurrent, peak
        async with lock.write():
            concurrent += 1
            peak = max(peak, concurrent)
            await asyncio.sleep(0)
            concurrent -= 1

    await asyncio.gather(*(writer() for _ in range(4)))

    assert peak == 1


async def test_a_waiting_writer_blocks_new_readers() -> None:
    """A steady stream of readers cannot starve a queued writer."""
    lock = AsyncReadWriteLock()
    order: list[str] = []
    first_reader_inside = asyncio.Event()
    release_first_reader = asyncio.Event()

    async def first_reader() -> None:
        async with lock.read():
            first_reader_inside.set()
            await release_first_reader.wait()
            order.append("first-reader")

    async def writer() -> None:
        await first_reader_inside.wait()
        async with lock.write():
            order.append("writer")

    async def late_reader() -> None:
        await first_reader_inside.wait()
        await asyncio.sleep(0)
        async with lock.read():
            order.append("late-reader")

    first = asyncio.ensure_future(first_reader())
    second = asyncio.ensure_future(writer())
    third = asyncio.ensure_future(late_reader())
    await first_reader_inside.wait()
    for _ in range(5):
        await asyncio.sleep(0)

    release_first_reader.set()
    await asyncio.gather(first, second, third)

    assert order == ["first-reader", "writer", "late-reader"]


async def test_an_error_inside_the_block_releases_the_lock() -> None:
    """A failing holder must not leave the lock permanently taken."""
    lock = AsyncReadWriteLock()

    for acquire in (lock.read, lock.write):
        try:
            async with acquire():
                raise RuntimeError("boom")
        except RuntimeError:
            pass

    assert lock.readers == 0
    assert lock.writing is False
    async with lock.write():
        assert lock.writing is True
