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


async def test_preserialized_reads_match_documented_schemas(env):
    from club.schemas import BootstrapOutput, ClubDetailOutput, Envelope, QuotaOutput

    app, client, tokens = env
    auth = {"Authorization": "Bearer " + tokens[1]}
    boot = await client.get("/api/v1/bootstrap", headers=auth)
    data = Envelope[BootstrapOutput].model_validate(boot.json()).data
    assert [c.id for c in data.clubs] == [1, 2] and data.user.id == 1
    quotas = await client.get("/api/v1/clubs/quotas", headers=auth)
    assert len(Envelope[list[QuotaOutput]].model_validate(quotas.json()).data) == 2
    detail = await client.get("/api/v1/clubs/2", headers=auth)
    assert Envelope[ClubDetailOutput].model_validate(detail.json()).data.remaining == 20
    assert (await client.get("/api/v1/clubs/99", headers=auth)).status_code == 404
