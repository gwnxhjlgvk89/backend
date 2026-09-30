from sqlalchemy import event
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from club.config import settings
from club.metrics import before_cursor, after_cursor


def make_engine(*, pool_size=None, max_overflow=None, read_only=False):
    s = settings()
    engine = create_async_engine(
        s.database_url,
        pool_size=s.pool_size if pool_size is None else pool_size,
        max_overflow=s.pool_overflow if max_overflow is None else max_overflow,
        pool_timeout=3,
        # Recycling bounds idle staleness; a per-checkout ping would add a
        # round-trip to every request during the opening burst.
        pool_recycle=300,
        hide_parameters=True,
        # Reads run in autocommit: each SELECT sees committed data (as READ
        # COMMITTED would) and returning the connection needs no ROLLBACK.
        isolation_level="AUTOCOMMIT" if read_only else "READ COMMITTED",
        pool_reset_on_return=None if read_only else "rollback",
        connect_args={"connect_timeout": 5},
    )

    @event.listens_for(engine.sync_engine, "connect")
    def limits(connection, _):
        cursor = connection.cursor()
        cursor.execute("SET SESSION innodb_lock_wait_timeout=2")
        cursor.execute("SET SESSION time_zone='+00:00'")
        cursor.close()

    event.listen(engine.sync_engine, "before_cursor_execute", before_cursor)
    event.listen(engine.sync_engine, "after_cursor_execute", after_cursor)
    return engine


def sessions(engine):
    return async_sessionmaker(engine, expire_on_commit=False)
