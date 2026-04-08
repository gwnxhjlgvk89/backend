# 创建管理员账号接口
# 1. xlsx文件上传（两种模式：初始数据上传(清空)、增量数据上传）
import io
import re
import pandas as pd
import numpy as np
import bcrypt
from typing import Optional, List, Dict, Set, Tuple
import models

from fastapi import APIRouter, UploadFile, File, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import text, select

from schemas import ResponseSchema

from auth import (
    get_current_student,
    get_current_admin,
    oauth2_scheme,
    admin_oauth2_scheme,
    hash_password,
    create_access_token,
    verify_password,
    decode_access_token,
)

from database import get_db

router = APIRouter(prefix="/admin", tags=["管理员创建模块"])


@router.post("/create", response_model=ResponseSchema, summary="创建管理员账号")
def create_admin_account(
    username: str = Query(..., description="管理员用户名"),
    password: str = Query(..., description="管理员密码"),
    role: str = Query(..., description="管理员角色: 1普通管理员，2超级管理员"),
    db: Session = Depends(get_db),
):
    # 检查用户名是否已存在
    existing_admin = (
        db.query(models.AdminUser).filter(models.AdminUser.username == username).first()
    )
    if existing_admin:
        raise HTTPException(status_code=400, detail="用户名已存在")

    # 创建新管理员账号
    new_admin = models.AdminUser(
        username=username,
        password_hash=hash_password(password),
        is_active=1,
        last_login_at=None,
        role=role,
    )
    db.add(new_admin)
    db.commit()

    return ResponseSchema(
        code=200, message="管理员账号创建成功", data={"username": username}
    )


@router.post("/create_test", response_model=ResponseSchema, summary="创建临时测试账号")
def create_user_account(
    db: Session = Depends(get_db),
):
    for i in range(10):
        student_id = "test" + str(i)
        name = "test"
        if i < 5:
            class_name = "跨境2502"
            major_name = "跨境电子商务"
            department = "商务管理学院"
        else:
            class_name = "会计2526"
            major_name = "大数据与会计（2）"
            department = "商务管理学院"
        is_reserved = 0
        is_pwd_changed = 1

        student = db.get(models.Students, student_id)
        if not student:
            # 新增学生，生成初始密码哈希
            db.add(
                models.Students(
                    student_id=student_id,
                    name=name,
                    major_name=major_name,
                    class_name=class_name,
                    department=department,
                    is_reserved=is_reserved,
                    is_pwd_changed=is_pwd_changed,
                    password_hash=hash_password(name),
                )
            )
            db.commit()
        else:
            # 学生已存在，更新信息和密码哈希
            student.name = name
            student.major_name = major_name
            student.class_name = class_name
            student.department = department
            student.is_reserved = is_reserved
            student.is_pwd_changed = is_pwd_changed
            student.password_hash = hash_password(name)
            db.commit()

    return ResponseSchema(code=200, message="测试账号创建成功", data=None)


@router.post("/create/club", response_model=ResponseSchema, summary="创建社团")
def create_club(
    club_data: dict,
    db: Session = Depends(get_db),
):
    if not club_data.get("club_name"):
        raise HTTPException(status_code=400, detail="社团名称不能为空")
    if db.query(models.Clubs).filter_by(club_name=club_data["club_name"]).first():
        raise HTTPException(status_code=400, detail="社团名称已存在")
    # 这里 club_data 是一个字典，包含社团的各个字段
    # 你需要根据你的 models.Clubs 模型来提取这些字段
    new_club = models.Clubs(
        club_name=club_data.get("club_name"),
        super_club=club_data.get("super_club"),
        teacher_advisor=club_data.get("teacher_advisor"),
        club_president=club_data.get("club_president"),
        description=club_data.get("description"),
        description_detail=club_data.get("description_detail"),
        cover_image=club_data.get("cover_image"),
        activity_position=club_data.get("activity_position"),
        activity_time=club_data.get("activity_time"),
        foundation_year=club_data.get("foundation_year"),
        total_quota=club_data.get("total_quota"),
        reserved_quota=club_data.get("reserved_quota"),
        remaining_quota=club_data.get("remaining_quota"),  # 初始剩余名额等于总名额
        club_status=club_data.get("club_status"),
        has_major_limit=club_data.get("has_major_limit"),
    )
    db.add(new_club)
    db.commit()

    return ResponseSchema(code=200, message="社团创建成功", data=None)


@router.post("/create/student", response_model=ResponseSchema, summary="创建学生账号")
def create_student(
    student_data: dict,
    db: Session = Depends(get_db),
):
    required_fields = ["student_id", "name", "major_name", "class_name", "department"]
    for field in required_fields:
        if not student_data.get(field):
            raise HTTPException(status_code=400, detail=f"{field} 不能为空")

    if (
        db.query(models.Students)
        .filter_by(student_id=student_data["student_id"])
        .first()
    ):
        raise HTTPException(status_code=400, detail="学生ID已存在")

    # 如果是新增major
    new_major = (
        db.query(models.Majors)
        .filter_by(major_name=student_data.get("major_name"))
        .first()
    )
    if not new_major:
        new_major = models.Majors(
            major_name=student_data.get("major_name"),
            department=student_data.get("department"),
        )
        db.add(new_major)
        # Ensure majors row exists before inserting classes row referencing it.
        db.flush()

    # 如果是新增class
    new_class = (
        db.query(models.Classes)
        .filter_by(
            class_name=student_data.get("class_name"),
        )
        .first()
    )
    if not new_class:
        new_class = models.Classes(
            class_name=student_data.get("class_name"),
            major_name=student_data.get("major_name"),
        )
        db.add(new_class)

    if student_data.get("has_selected"):
        club = (
            db.query(models.Clubs)
            .filter_by(club_name=student_data.get("selected_club_name"))
            .first()
        )
        if club:
            if club.remaining_quota <= 0:
                raise HTTPException(status_code=400, detail="社团名额已满")
            club.remaining_quota -= 1
    if student_data.get("is_reserved"):
        club = (
            db.query(models.Clubs)
            .filter_by(club_name=student_data.get("reserved_club_name"))
            .first()
        )
        if club:
            if club.remaining_quota <= 0:
                raise HTTPException(status_code=400, detail="社团名额已满")
            club.remaining_quota -= 1

    new_student = models.Students(
        student_id=student_data.get("student_id"),
        name=student_data.get("name"),
        major_name=student_data.get("major_name"),
        class_name=student_data.get("class_name"),
        department=student_data.get("department"),
        is_reserved=student_data.get("is_reserved", 0),
        reserved_club_name=student_data.get("reserved_club_name"),
        has_selected=student_data.get("has_selected", 0),
        selected_club_name=student_data.get("selected_club_name"),
        is_pwd_changed=0,
        password_hash=hash_password(student_data.get("name")),  # 初始密码为姓名
        email=student_data.get("email"),
        phone=student_data.get("phone"),
    )

    db.add(new_student)
    db.commit()

    return ResponseSchema(code=200, message="学生账号创建成功", data=None)
