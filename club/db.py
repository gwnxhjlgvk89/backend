from sqlalchemy import event
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from club.config import settings


def make_engine():
    s = settings()
    engine = create_async_engine(s.database_url, pool_size=s.pool_size, max_overflow=s.pool_overflow,
                                 pool_timeout=2, pool_recycle=300, pool_pre_ping=True,
                                 isolation_level="READ COMMITTED", connect_args={"connect_timeout": 5})

    @event.listens_for(engine.sync_engine, "connect")
    def limits(connection, _):
        cursor = connection.cursor()
        cursor.execute("SET SESSION innodb_lock_wait_timeout=2")
        cursor.execute("SET SESSION time_zone='+00:00'")
        cursor.close()

    return engine


def sessions(engine):
    return async_sessionmaker(engine, expire_on_commit=False)
