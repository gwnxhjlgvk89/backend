"""Batch concurrent identity reads, without caching accounts across requests."""

import asyncio
import time
from collections import deque

from sqlalchemy import select
from club.errors import DomainError, fail
from club.metrics import READ_POOL_WAIT
from club.models import User


class BatchReader:
    busy_message = "读取繁忙，请稍后再试"

    def __init__(self, factory, *, max_pending=4096, batch_size=128):
        self.factory = factory
        self.max_pending = max_pending
        self.batch_size = batch_size
        self.pending = deque()
        self.task = None
        self.closed = False

    async def fetch(self, keys):
        raise NotImplementedError

    async def get(self, key):
        if self.closed or len(self.pending) >= self.max_pending:
            fail(503, "TEMPORARILY_UNAVAILABLE", self.busy_message)
        future = asyncio.get_running_loop().create_future()
        self.pending.append((key, future))
        if self.task is None or self.task.done():
            self.task = asyncio.create_task(self.flush())
        try:
            return await asyncio.wait_for(future, timeout=3)
        except TimeoutError:
            fail(503, "TEMPORARILY_UNAVAILABLE", self.busy_message)

    async def flush(self):
        batch = []
        try:
            # A bounded 2ms window groups arrival bursts, not persisted identity data.
            await asyncio.sleep(0.002)
            while self.pending:
                batch = [self.pending.popleft() for _ in range(min(len(self.pending), self.batch_size))]
                live = [(key, f) for key, f in batch if not f.done()]
                if not live:
                    continue
                try:
                    accounts = await self.fetch({k for k, _ in live})
                    for key, future in live:
                        if not future.done():
                            future.set_result(accounts.get(key))
                except Exception as exc:
                    for _, future in live:
                        if not future.done():
                            future.set_exception(exc)
                batch = []
        finally:
            if self.closed:
                for _, future in batch + list(self.pending):
                    if not future.done():
                        future.set_exception(DomainError(503, "TEMPORARILY_UNAVAILABLE", "服务正在维护"))
                self.pending.clear()

    async def close(self):
        self.closed = True
        if self.task:
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
        # Cancellation before flush starts must also resolve its queued futures.
        for _, future in self.pending:
            if not future.done():
                future.set_exception(DomainError(503, "TEMPORARILY_UNAVAILABLE", "服务正在维护"))
        self.pending.clear()


class IdentityReader(BatchReader):
    busy_message = "身份核验繁忙，请稍后再试"

    def __init__(self, factory, column=User.id, **kwargs):
        super().__init__(factory, **kwargs)
        self.column = column

    async def fetch(self, keys):
        async with self.factory() as db:
            waiting = time.monotonic()
            try:
                await db.connection()
            finally:
                READ_POOL_WAIT.observe(time.monotonic() - waiting)
            rows = (await db.scalars(select(User).where(self.column.in_(keys)))).all()
            return {getattr(row, self.column.key): row for row in rows}
