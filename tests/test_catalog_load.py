import asyncio
from sqlalchemy import event


async def test_cold_catalog_does_not_query_once_per_student(env):
    app, client, tokens = env
    catalog_reads = []

    def observed(conn, cursor, statement, parameters, context, many):
        if "v2_clubs.active IS true" in statement:
            catalog_reads.append(statement)

    event.listen(app.state.read_engine.sync_engine, "before_cursor_execute", observed)
    try:
        responses = await asyncio.gather(
            *(
                client.get(
                    "/api/v1/bootstrap",
                    headers={
                        "Authorization": "Bearer " + tokens[i],
                    },
                )
                for i in range(1, 31)
            )
        )
        assert all(r.status_code == 200 for r in responses)
        assert len(catalog_reads) == 1
    finally:
        event.remove(app.state.read_engine.sync_engine, "before_cursor_execute", observed)
