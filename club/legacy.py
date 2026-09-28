"""Strict legacy conversion. No production access or writes at import time."""

from collections import Counter, defaultdict
from datetime import datetime
import hashlib
import json
from zoneinfo import ZoneInfo

from sqlalchemy import func, select, text

from club.initial_passwords import initial_password
from club.models import Activity, Club, Enrollment, Favorite, User

TABLES = (
    "students",
    "admin_users",
    "clubs",
    "reserved_list",
    "selections",
    "student_favorites",
    "club_major_restrictions",
    "majors",
    "classes",
)


def fingerprint(snapshot):
    stable = {
        k: sorted(v, key=lambda x: json.dumps(x, sort_keys=True, default=str)) for k, v in snapshot.items()
    }
    return hashlib.sha256(json.dumps(stable, sort_keys=True, default=str).encode()).hexdigest()


def plan_legacy(data):
    issues = []
    clubs = {c["club_name"]: c for c in data["clubs"]}
    students = {s["student_id"]: s for s in data["students"]}
    if len(clubs) != len(data["clubs"]) or len(students) != len(data["students"]):
        issues.append({"code": "DUPLICATE_PRIMARY_KEYS"})
    usernames = [str(s["student_id"]) for s in data["students"]] + [
        a["username"] for a in data["admin_users"]
    ]
    if len(set(u.casefold() for u in usernames)) != len(usernames):
        issues.append({"code": "USERNAME_COLLISION"})
    reserved, selected = defaultdict(list), defaultdict(list)
    for r in data["reserved_list"]:
        reserved[r["student_id"]].append(r["club_name"])
    for r in data["selections"]:
        selected[r["student_id"]].append(r["club_name"])
    enrolled = []
    limits = defaultdict(list)
    for r in data["club_major_restrictions"]:
        limits[r["club_name"]].append(r["major_name"])
    for sid in set(reserved) | set(selected):
        if sid not in students:
            issues.append({"code": "ORPHAN_ENROLLMENT", "student_id": sid})
    for sid, s in students.items():
        r, n = reserved[sid], selected[sid]
        rflag = bool(s.get("is_reserved"))
        nflag = bool(s.get("has_selected"))
        if len(r) > 1 or len(n) > 1:
            issues.append({"code": "DUPLICATE_ENROLLMENT", "student_id": sid})
        # Flags were the old write path. A selection table may be empty, but if
        # populated it must agree exactly; reservation sources must agree too.
        rn = s.get("reserved_club_name") if rflag else None
        nn = s.get("selected_club_name") if nflag else None
        if (r and (not rflag or r != [rn])) or (n and (not nflag or n != [nn])):
            issues.append({"code": "FLAG_RECORD_CONFLICT", "student_id": sid})
        if (rflag and not rn) or (nflag and not nn) or (rflag and nflag):
            issues.append({"code": "RESERVED_NORMAL_CONFLICT", "student_id": sid})
        name = rn or nn
        if name:
            if name not in clubs:
                issues.append({"code": "MISSING_CLUB", "student_id": sid})
                continue
            if clubs[name].get("has_major_limit") and s.get("major_name") not in limits[name]:
                issues.append({"code": "INELIGIBLE_ENROLLMENT", "student_id": sid})
            enrolled.append(
                {
                    "student_id": sid,
                    "club_name": name,
                    "source": "reserved" if rn else "normal",
                    "created_at": s.get("selected_at"),
                }
            )
    count = Counter(e["club_name"] for e in enrolled)
    reserved_count = Counter(e["club_name"] for e in enrolled if e["source"] == "reserved")
    for name, c in clubs.items():
        if c["total_quota"] - count[name] != c["remaining_quota"] or reserved_count[name] != c.get(
            "reserved_quota", 0
        ):
            issues.append(
                {
                    "code": "QUOTA_MISMATCH",
                    "club_name": name,
                    "capacity": c["total_quota"],
                    "remaining": c["remaining_quota"],
                    "enrolled": count[name],
                    "reserved": reserved_count[name],
                }
            )
        if c.get("has_major_limit") and not limits[name]:
            issues.append({"code": "EMPTY_MAJOR_RESTRICTION", "club_name": name})
    for a in data["admin_users"]:
        if a.get("role") not in (1, 2):
            issues.append({"code": "INVALID_ADMIN", "admin_id": a.get("admin_id")})
    if not any(a.get("role") == 2 and a.get("is_active") for a in data["admin_users"]):
        issues.append({"code": "NO_ACTIVE_SUPER_ADMIN"})
    return {
        "fingerprint": fingerprint(data),
        "counts": {k: len(v) for k, v in data.items()},
        "issues": issues,
        "enrollments": enrolled,
    }


async def read_legacy(db, lock=False):
    # Names are an internal constant, never client input.
    return {
        name: [
            dict(r)
            for r in (
                await db.execute(text(f"SELECT * FROM `{name}`" + (" FOR UPDATE" if lock else "")))
            ).mappings()
        ]
        for name in TABLES
    }


async def apply_legacy(db, data, reviewed_fingerprint, timezone="Asia/Shanghai"):
    plan = plan_legacy(data)
    if plan["issues"] or plan["fingerprint"] != reviewed_fingerprint:
        raise ValueError("Legacy conflicts or source changed; regenerate and review the report")
    if await db.scalar(select(func.count()).select_from(User)) or await db.scalar(
        select(func.count()).select_from(Club)
    ):
        raise ValueError("Migration requires empty v2 users and clubs")
    passwords = {str(s["student_id"]): initial_password(s["name"]) for s in data["students"]}
    passwords.update(
        {a["username"]: initial_password(a.get("real_name") or a["username"]) for a in data["admin_users"]}
    )
    cids, uids = {}, {}
    restrictions = defaultdict(list)
    for r in data["club_major_restrictions"]:
        restrictions[r["club_name"]].append(r["major_name"])
    for c in sorted(data["clubs"], key=lambda c: c["club_name"]):
        new = Club(
            name=c["club_name"],
            category=c.get("super_club") or "",
            description=c.get("description_detail") or c.get("description") or "",
            location=c.get("activity_position") or "",
            schedule=c.get("activity_time") or "",
            cover=c.get("cover_image") or "",
            capacity=c["total_quota"],
            remaining=c["remaining_quota"],
            active=c.get("club_status", 1) != 0,
            allowed_majors=restrictions[c["club_name"]] if c.get("has_major_limit") else [],
        )
        db.add(new)
        await db.flush()
        cids[c["club_name"]] = new.id
    for s in data["students"]:
        new = User(
            username=str(s["student_id"]),
            name=s["name"],
            password_plaintext=passwords[str(s["student_id"])],
            role="student",
            major=s["major_name"],
            class_name=s["class_name"],
            active=bool(s["account_status"]),
            must_change_password=True,
            avatar=s.get("avatar") or "",
            phone=s.get("phone") or "",
            email=s.get("email") or "",
            token_version=s.get("token_ver", 1) + 1,
        )
        db.add(new)
        await db.flush()
        uids[s["student_id"]] = new.id
    for a in data["admin_users"]:
        db.add(
            User(
                username=a["username"],
                name=a.get("real_name") or a["username"],
                password_plaintext=passwords[a["username"]],
                role="super_admin" if a["role"] == 2 else "admin",
                active=bool(a["is_active"]),
                must_change_password=True,
            )
        )
    for e in plan["enrollments"]:
        created = e["created_at"]
        if created:
            if isinstance(created, str):
                created = datetime.fromisoformat(created)
            created = (
                created.replace(tzinfo=ZoneInfo(timezone)).astimezone(ZoneInfo("UTC")).replace(tzinfo=None)
            )
        kwargs = {"created_at": created} if created else {}
        db.add(
            Enrollment(
                student_id=uids[e["student_id"]], club_id=cids[e["club_name"]], source=e["source"], **kwargs
            )
        )
    for f in data["student_favorites"]:
        if f["student_id"] in uids and f["club_name"] in cids:
            db.add(Favorite(student_id=uids[f["student_id"]], club_id=cids[f["club_name"]]))
    a = await db.get(Activity, 1)
    if a:
        a.state = "draft"
    else:
        db.add(Activity(id=1, state="draft"))
    await db.flush()
    return plan["counts"]
