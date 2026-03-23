# 它定义的是所有数据流转过程中的数据格式，包括请求体、响应体、数据库模型等。
from pydantic import BaseModel, Field
from typing import Optional, Generic, TypeVar

# ── 通用响应格式 ──────────────────────────

T = TypeVar("T")


class ResponseSchema(BaseModel, Generic[T]):
    """统一响应结构，所有接口都返回这个格式"""

    code: int = Field(200, description="状态码，200成功")
    message: str = Field("ok", description="提示信息")
    data: Optional[T] = Field(None, description="返回数据")


# ── 登录响应数据结构 ──────────────────────────
class LoginRequestSchema(BaseModel):
    username: str = Field(..., description="用户名，因为学生管理员共用登录接口")
    password: str = Field(..., description="密码")


# 这里需要返回所有所需数据(可以大大加快访问效率)
class LoginResponseSchema(BaseModel):
    token: str = Field(..., description="JWT 访问令牌")
    token_type: str = Field("Bearer", description="令牌类型，默认为 Bearer")
    identity: str = Field(..., description="登录身份，student 或 admin")
    student: dict = Field({}, description="学生个人信息")
    admin: dict = Field({}, description="管理员个人信息")
    clubs: list[dict] = Field([], description="所有社团列表")


# 退出登录的话，只需要前端操作即可
# ────────────────────────────────────────


# ── 修改密码数据结构(管理员不用改密码) ──────────────────────────
class ChangePasswordRequestSchema(BaseModel):
    old_password: str = Field(..., description="旧密码")
    new_password: str = Field(..., description="新密码")


# 响应请求不需要，因为修改密码不需要返回额外数据，统一用 ResponseSchema 即可
# ────────────────────────────────────────


# ── 个人信息数据结构 ──────────────────────────
class PersonalInfoRequestSchema(BaseModel):
    username: int = Field(..., description="用户名，因为学生管理员共用接口")


class PersonalInfoResponseSchema(BaseModel):
    student: dict = Field({}, description="学生个人信息")
    admin: dict = Field({}, description="管理员个人信息")


# ────────────────────────────────────────


# ── 社团信息数据结构 ──────────────────────────
class ClubsResponseSchema(BaseModel):
    clubs: list[dict] = Field([], description="所有社团列表")
