from sqlalchemy import Integer, String, DateTime, ForeignKey, Text, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from typing import Optional
from datetime import datetime


class Base(DeclarativeBase):
    # 只需要再能被模型文件访问到的地方创建一次就行
    pass


class Majors(Base):
    __tablename__ = "majors"

    major_name: Mapped[str] = mapped_column(
        String(64), nullable=False, primary_key=True
    )
    department: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Classes(Base):
    __tablename__ = "classes"

    class_name: Mapped[str] = mapped_column(
        String(64), nullable=False, primary_key=True
    )
    major_name: Mapped[str] = mapped_column(
        String(64), ForeignKey("majors.major_name"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Students(Base):
    __tablename__ = "students"

    # club_id和major_name可以添加外键关联，因为后续高峰值抢课操作不会频繁更新这两个字段，性能影响不大
    # 但select_club_id会频繁查询和更新，所以不加外键，改成冗余存储，定期通过后台任务校验数据一致性

    student_id: Mapped[str] = mapped_column(
        String(20), primary_key=True, comment="学号"
    )
    name: Mapped[str] = mapped_column(String(32), nullable=False, comment="姓名")
    avatar: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True, comment="头像URL"
    )
    email: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True, comment="邮箱地址"
    )
    phone: Mapped[Optional[str]] = mapped_column(
        String(20), nullable=True, comment="联系电话"
    )
    password_hash: Mapped[str] = mapped_column(
        String(255), nullable=False, comment="密码哈希"
    )
    class_name: Mapped[str] = mapped_column(
        String(64), ForeignKey("classes.class_name"), nullable=False
    )
    major_name: Mapped[str] = mapped_column(
        String(64), ForeignKey("majors.major_name"), nullable=False
    )
    department: Mapped[str] = mapped_column(
        String(64), nullable=False, comment="学院/系部"
    )
    is_pwd_changed: Mapped[int] = mapped_column(
        Integer, default=0, comment="是否修改过初始密码"
    )
    account_status: Mapped[int] = mapped_column(Integer, default=1, comment="账号状态")
    is_reserved: Mapped[int] = mapped_column(
        Integer, default=0, comment="是否在预留名单中"
    )
    reserved_club_name: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True, comment="预留社团名称"
    )
    has_selected: Mapped[int] = mapped_column(Integer, default=0, comment="是否已抢课")
    selected_club_name: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True, comment="已抢到的社团名称"
    )
    selected_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    token_ver: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class AdminUser(Base):
    __tablename__ = "admin_users"

    admin_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    real_name: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    role: Mapped[int] = mapped_column(
        Integer, default=1, comment="1-普通管理员 2-超级管理员"
    )
    is_active: Mapped[int] = mapped_column(Integer, default=1)
    last_login_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Clubs(Base):
    __tablename__ = "clubs"

    club_name: Mapped[str] = mapped_column(
        String(64), primary_key=True, comment="社团名称"
    )
    teacher_advisor: Mapped[Optional[str]] = mapped_column(
        String(32), nullable=True, comment="指导老师"
    )
    club_president: Mapped[Optional[str]] = mapped_column(
        String(32), nullable=True, comment="社长"
    )
    super_club: Mapped[Optional[str]] = mapped_column(
        String(32), nullable=False, comment="一级社团"
    )
    description: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True, comment="社团简介"
    )
    description_detail: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True, comment="社团详细介绍"
    )
    activity_position: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True, comment="社团活动位置"
    )
    activity_time: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True, comment="社团活动时间"
    )
    foundation_year: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True, comment="社团成立年份"
    )
    cover_image: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True, comment="封面图片URL"
    )
    total_quota: Mapped[int] = mapped_column(
        Integer, nullable=False, default=30, comment="招募名额"
    )
    reserved_quota: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, comment="预留名额（管理员预留给特定学生）"
    )
    remaining_quota: Mapped[int] = mapped_column(
        Integer, nullable=False, default=30, comment="剩余名额"
    )
    club_status: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, comment="状态 0-停止招募 1-正在招募"
    )
    has_major_limit: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, comment="是否有专业限制"
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class Club_Activities(Base):
    __tablename__ = "club_activities"

    activity_id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True, comment="活动ID"
    )
    club_name: Mapped[str] = mapped_column(
        String(64), ForeignKey("clubs.club_name", ondelete="CASCADE"), nullable=False
    )
    activity_name: Mapped[str] = mapped_column(
        String(64), nullable=False, comment="活动名称"
    )
    activity_location: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True, comment="活动地点"
    )


class Student_Favorites(Base):
    __tablename__ = "student_favorites"

    student_id: Mapped[str] = mapped_column(
        String(20),
        ForeignKey("students.student_id", ondelete="CASCADE"),
        primary_key=True,
    )
    club_name: Mapped[str] = mapped_column(
        String(64), ForeignKey("clubs.club_name", ondelete="CASCADE"), primary_key=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Club_Major_Restrictions(Base):
    __tablename__ = "club_major_restrictions"

    club_name: Mapped[str] = mapped_column(
        String(64), ForeignKey("clubs.club_name", ondelete="CASCADE"), primary_key=True
    )
    major_name: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("majors.major_name", ondelete="CASCADE"),
        primary_key=True,
    )


class Selections(Base):
    __tablename__ = "selections"

    selection_id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True
    )
    student_id: Mapped[str] = mapped_column(
        String(20),
        ForeignKey("students.student_id", ondelete="CASCADE"),
        nullable=False,
    )
    club_name: Mapped[str] = mapped_column(
        String(64), ForeignKey("clubs.club_name", ondelete="CASCADE"), nullable=False
    )
    selected_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Reserved_List(Base):
    __tablename__ = "reserved_list"

    student_id: Mapped[str] = mapped_column(
        String(20),
        ForeignKey("students.student_id", ondelete="CASCADE"),
        primary_key=True,
    )
    club_name: Mapped[str] = mapped_column(
        String(64), ForeignKey("clubs.club_name", ondelete="CASCADE"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    created_by: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("admin_users.admin_id"), nullable=True
    )


class System_Config(Base):
    __tablename__ = "system_config"

    config_id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True
    )
    activity_name: Mapped[str] = mapped_column(
        String(64), nullable=False, unique=True, comment="活动名称"
    )
    preview_start: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, comment="预览开始时间"
    )
    preview_end: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, comment="预览结束时间"
    )
    selection_start: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, comment="抢课开始时间"
    )
    selection_end: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, comment="抢课结束时间"
    )
    allow_cancel: Mapped[int] = mapped_column(
        Integer, default=0, comment="是否允许学生取消已选社团"
    )
    cancel_deadline: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True, comment="取消截止时间，允许取消时必填"
    )
    system_status: Mapped[int] = mapped_column(
        Integer, default=1, comment="系统状态 0-未发布 1-预览中 2-抢课中 3-已结束"
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class Operation_Logs(Base):
    __tablename__ = "operation_logs"

    log_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    operator_id: Mapped[str] = mapped_column(
        String(32), nullable=False, comment="操作者ID"
    )
    operator_type: Mapped[int] = mapped_column(
        Integer, nullable=False, comment="1-学生 2-管理员"
    )
    action: Mapped[str] = mapped_column(String(64), nullable=False, comment="操作类型")
    target_table: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    target_id: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    details: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True, comment="操作详情，JSON格式"
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    ip_address: Mapped[Optional[str]] = mapped_column(
        String(45), nullable=True, comment="操作者IP地址"
    )
