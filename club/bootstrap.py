"""Coalesce concurrent bootstrap reads; never retain personal or quota snapshots."""

from sqlalchemy import select
from club.errors import fail
from club.identity import BatchReader
from club.models import Activity, Club, Enrollment, Favorite
from club.services import activity_data, iso


class BootstrapReader(BatchReader):
    async def fetch(self, keys):
        async with self.factory() as db:
            activity = await db.get(Activity, 1)
            if not activity:
                fail(503, "NOT_INITIALIZED", "活动尚未初始化")
            mine = {
                row.student_id: {
                    "club_id": row.club_id,
                    "club_name": name,
                    "source": row.source,
                    "created_at": iso(row.created_at),
                }
                for row, name in await db.execute(
                    select(Enrollment, Club.name).join(Club).where(Enrollment.student_id.in_(keys))
                )
            }
            favorites = {key: [] for key in keys}
            for uid, cid in await db.execute(
                select(Favorite.student_id, Favorite.club_id).where(Favorite.student_id.in_(keys))
            ):
                favorites[uid].append(cid)
            quotas = [
                {"club_id": cid, "remaining": remaining, "version": version}
                for cid, remaining, version in await db.execute(select(Club.id, Club.remaining, Club.version))
            ]
        status = activity_data(activity)
        return {
            uid: {
                "activity": status,
                "enrollment": mine.get(uid),
                "favorites": favorites[uid],
                "quotas": quotas,
            }
            for uid in keys
        }
