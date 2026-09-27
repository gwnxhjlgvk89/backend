from datetime import datetime, timezone
from typing import Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    @field_validator("password", "new_password", "old_password", check_fields=False)
    @classmethod
    def bounded_password(cls, v):
        if v is not None and len(v.encode()) > 72:
            raise ValueError("密码编码后不能超过72字节")
        return v


class Login(Input):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=72)


class PasswordChange(Input):
    old_password: str = Field(min_length=1, max_length=72)
    new_password: str = Field(min_length=10, max_length=72)

    @field_validator("new_password")
    @classmethod
    def password_bytes(cls, v):
        if len(v.encode()) > 72:
            raise ValueError("密码编码后不能超过72字节")
        return v


class EnrollmentInput(Input):
    club_id: int = Field(gt=0)


class Contact(Input):
    phone: str = Field(default="", max_length=32, pattern=r"^[0-9+ ()-]*$")
    email: str = Field(default="", max_length=254)

    @field_validator("email")
    @classmethod
    def email_valid(cls, v):
        if v and ("@" not in v or any(c.isspace() for c in v)):
            raise ValueError("邮箱格式不正确")
        return v


class ClubInput(Input):
    name: str = Field(min_length=1, max_length=64)
    category: str = Field(default="", max_length=64)
    description: str = Field(default="", max_length=10000)
    location: str = Field(default="", max_length=128)
    schedule: str = Field(default="", max_length=128)
    cover: str = Field(default="", max_length=512)
    capacity: int = Field(ge=0, le=10000)
    active: bool = True
    allowed_majors: list[str] = Field(default_factory=list, max_length=200)


class StudentInput(Input):
    username: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=64)
    major: str = Field(default="", max_length=64)
    class_name: str = Field(default="", max_length=64)
    active: bool = True
    password: str | None = Field(default=None, min_length=10, max_length=72)
    reserved_club_id: int | None = Field(default=None, gt=0)


class AdminInput(Input):
    username: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=10, max_length=72)
    role: Literal["admin", "super_admin"] = "admin"


class AdminRoleInput(Input):
    role: Literal["admin", "super_admin"]
    active: bool = True


class ActivityInput(Input):
    name: str = Field(min_length=1, max_length=128)
    starts_at: datetime
    ends_at: datetime
    allow_cancel: bool = False
    cancel_until: datetime | None = None

    @field_validator("starts_at", "ends_at", "cancel_until")
    @classmethod
    def utc(cls, v):
        if v is not None:
            if not v.tzinfo:
                raise ValueError("时间必须包含时区")
            return v.astimezone(timezone.utc).replace(tzinfo=None)
        return v

    @model_validator(mode="after")
    def window(self):
        if self.ends_at <= self.starts_at:
            raise ValueError("结束时间必须晚于开始时间")
        if self.allow_cancel and (not self.cancel_until or self.cancel_until < self.starts_at):
            raise ValueError("允许退选时须设置有效截止时间")
        return self


class ActivityState(Input):
    state: Literal["published", "paused", "draft"]


# Explicit public output contracts. ORM columns never define the API surface.

T = TypeVar("T")


class Envelope(BaseModel, Generic[T]):
    data: T


class UserOutput(BaseModel):
    id: int
    username: str
    name: str
    role: Literal["student", "admin", "super_admin"]
    major: str
    class_name: str
    active: bool
    must_change_password: bool
    phone: str
    email: str


class LoginOutput(BaseModel):
    token: str
    user: UserOutput


class ActivityOutput(BaseModel):
    name: str
    state: Literal["draft", "paused", "upcoming", "open", "ended"]
    configured_state: Literal["draft", "paused", "published"]
    starts_at: str | None
    ends_at: str | None
    allow_cancel: bool
    cancel_until: str | None
    version: int


class ClubOutput(BaseModel):
    id: int
    name: str
    category: str
    location: str
    schedule: str
    cover: str
    capacity: int
    active: bool
    allowed_majors: list[str]


class QuotaOutput(BaseModel):
    club_id: int
    remaining: int
    version: int


class ClubDetailOutput(ClubOutput):
    remaining: int
    version: int
    description: str


class EnrollmentOutput(BaseModel):
    club_id: int
    club_name: str
    source: Literal["normal", "reserved"]
    created_at: str


class EnrollmentResult(BaseModel):
    status: Literal["enrolled", "cancelled"]
    enrollment: EnrollmentOutput | None


class BootstrapOutput(BaseModel):
    user: UserOutput
    activity: ActivityOutput
    server_time: str
    enrollment: EnrollmentOutput | None
    favorites: list[int]
    clubs: list[ClubOutput]
    quotas: list[QuotaOutput]
