import asyncio
from sqlalchemy import event
from club.models import Activity, Club, Enrollment, Favorite


async def test_bootstrap_batches_queries_and_isolates_personal_results(env):
    app, client, tokens = env
    async with app.state.sessions() as db, db.begin():
        db.add(Enrollment(student_id=1, club_id=2, source="normal"))
        db.add_all([Favorite(student_id=1, club_id=1), Favorite(student_id=2, club_id=2)])
        (await db.get(Club, 2)).remaining = 19
    queries = []

    def observed(conn, cursor, statement, parameters, context, many):
        if statement.startswith("SELECT"):
            queries.append(statement)

    event.listen(app.state.read_engine.sync_engine, "before_cursor_execute", observed)
    try:
        values = await asyncio.gather(*(app.state.bootstrap_reads.get(i) for i in range(1, 31)))
        assert len(queries) == 4  # one batch, not four round-trips per student
        assert values[0]["enrollment"]["club_id"] == 2
        assert values[0]["favorites"] == [1]
        assert values[1]["enrollment"] is None and values[1]["favorites"] == [2]
        assert all(v["enrollment"] is None and v["favorites"] == [] for v in values[2:])
    finally:
        event.remove(app.state.read_engine.sync_engine, "before_cursor_execute", observed)
    # No cache survives a batch: a newly paused activity and changed quota are read again.
    async with app.state.sessions() as db, db.begin():
        (await db.get(Activity, 1)).state = "paused"
        club = await db.get(Club, 2)
        club.remaining = 18
        club.version += 1
    response = await client.get("/api/v1/bootstrap", headers={"Authorization": "Bearer " + tokens[2]})
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["user"]["id"] == 2 and data["enrollment"] is None and data["favorites"] == [2]
    assert data["activity"]["state"] == "paused"
    assert next(q for q in data["quotas"] if q["club_id"] == 2)["remaining"] == 18
