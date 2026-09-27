from sqlalchemy import event
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from club.config import settings
from club.metrics import before_cursor, after_cursor


def make_engine(*, pool_size=None, max_overflow=None):
    s = settings()
    engine = create_async_engine(
        s.database_url,
        pool_size=s.pool_size if pool_size is None else pool_size,
        max_overflow=s.pool_overflow if max_overflow is None else max_overflow,
        pool_timeout=3,
        pool_recycle=300,
        pool_pre_ping=True,
        hide_parameters=True,
        isolation_level="READ COMMITTED",
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
