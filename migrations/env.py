import asyncio
from alembic import context
from club.db import make_engine
from club.models import Base


def run(connection):
    context.configure(connection=connection, target_metadata=Base.metadata)
    with context.begin_transaction():
        context.run_migrations()


async def online():
    engine = make_engine()
    async with engine.connect() as connection:
        await connection.run_sync(run)
    await engine.dispose()


if context.is_offline_mode():
    raise RuntimeError("Use an isolated database for migration previews")
asyncio.run(online())
