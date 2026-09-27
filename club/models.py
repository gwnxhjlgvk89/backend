from datetime import datetime, timezone

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.dialects.mysql import DATETIME
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "v2_users"
    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    name: Mapped[str] = mapped_column(String(64))
    role: Mapped[str] = mapped_column(String(16), default="student", index=True)
    major: Mapped[str] = mapped_column(String(64), default="", index=True)
    class_name: Mapped[str] = mapped_column(String(64), default="", index=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=True)
    token_version: Mapped[int] = mapped_column(default=1)
    avatar: Mapped[str] = mapped_column(String(512), default="")
    phone: Mapped[str] = mapped_column(String(32), default="")
    email: Mapped[str] = mapped_column(String(254), default="")


class Club(Base):
    __tablename__ = "v2_clubs"
    __table_args__ = (CheckConstraint("remaining >= 0 AND remaining <= capacity", name="ck_quota"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True)
    category: Mapped[str] = mapped_column(String(64), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    location: Mapped[str] = mapped_column(String(128), default="")
    schedule: Mapped[str] = mapped_column(String(128), default="")
    cover: Mapped[str] = mapped_column(String(512), default="")
    capacity: Mapped[int] = mapped_column(Integer)
    remaining: Mapped[int] = mapped_column(Integer)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    allowed_majors: Mapped[list] = mapped_column(JSON, default=list)
    version: Mapped[int] = mapped_column(default=1)


class Activity(Base):
    __tablename__ = "v2_activity"
    id: Mapped[int] = mapped_column(primary_key=True, default=1)
    name: Mapped[str] = mapped_column(String(128), default="本届社团招新")
    starts_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=6))
    ends_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=6))
    cancel_until: Mapped[datetime | None] = mapped_column(DATETIME(fsp=6))
    allow_cancel: Mapped[bool] = mapped_column(Boolean, default=False)
    state: Mapped[str] = mapped_column(String(16), default="draft")
    version: Mapped[int] = mapped_column(default=1)


class Enrollment(Base):
    __tablename__ = "v2_enrollments"
    student_id: Mapped[int] = mapped_column(ForeignKey("v2_users.id"), primary_key=True)
    club_id: Mapped[int] = mapped_column(ForeignKey("v2_clubs.id"), index=True)
    source: Mapped[str] = mapped_column(String(16), default="normal")
    created_at: Mapped[datetime] = mapped_column(DATETIME(fsp=6), default=utcnow)


class Favorite(Base):
    __tablename__ = "v2_favorites"
    student_id: Mapped[int] = mapped_column(ForeignKey("v2_users.id"), primary_key=True)
    club_id: Mapped[int] = mapped_column(ForeignKey("v2_clubs.id"), primary_key=True)


class Idempotency(Base):
    __tablename__ = "v2_idempotency"
    __table_args__ = (UniqueConstraint("user_id", "key", name="uq_idempotency"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("v2_users.id"))
    key: Mapped[str] = mapped_column(String(64))
    fingerprint: Mapped[str] = mapped_column(String(128))
    response: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DATETIME(fsp=6), default=utcnow)


class Outbox(Base):
    __tablename__ = "v2_outbox"
    id: Mapped[int] = mapped_column(primary_key=True)
    payload: Mapped[dict] = mapped_column(JSON)
    delivered: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DATETIME(fsp=6), default=utcnow)


class Audit(Base):
    __tablename__ = "v2_audit"
    id: Mapped[int] = mapped_column(primary_key=True)
    actor_id: Mapped[int] = mapped_column(Integer)
    action: Mapped[str] = mapped_column(String(64))
    target: Mapped[str] = mapped_column(String(128))
    summary: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DATETIME(fsp=6), default=utcnow)


class Job(Base):
    __tablename__ = "v2_jobs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    actor_id: Mapped[int] = mapped_column(ForeignKey("v2_users.id"))
    kind: Mapped[str] = mapped_column(String(32))
    state: Mapped[str] = mapped_column(String(24), default="queued", index=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    result: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DATETIME(fsp=6), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DATETIME(fsp=6), default=utcnow, onupdate=utcnow)
