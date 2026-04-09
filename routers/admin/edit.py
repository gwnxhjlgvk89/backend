# 创建管理员账号接口
# 1. xlsx文件上传（两种模式：初始数据上传(清空)、增量数据上传）
import io
import re
import pandas as pd
import numpy as np
import bcrypt
from typing import Optional, List, Dict, Set, Tuple
import models

from fastapi import APIRouter, UploadFile, Body, File, Depends, HTTPException, Query
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


@router.post("/update/club", response_model=ResponseSchema, summary="更新社团")
def update_club(
    club_data: dict,
    db: Session = Depends(get_db),
):
    club = (
        db.query(models.Clubs).filter_by(club_name=club_data.get("club_name")).first()
    )
    if not club:
        raise HTTPException(status_code=400, detail="社团不存在")

    for field, value in club_data.items():
        if field == "club_name":
            continue
        setattr(club, field, value)
    db.commit()
    db.refresh(club)

    return ResponseSchema(code=200, message="社团更新成功", data=None)


@router.post("/delete/club", response_model=ResponseSchema, summary="删除社团")
def delete_club(
    club_name: str = Body(..., embed=True),
    db: Session = Depends(get_db),
):
    print(f"Attempting to delete club: {club_name}")
    club = db.query(models.Clubs).filter_by(club_name=club_name).first()
    if not club:
        raise HTTPException(status_code=400, detail="社团不存在")

    students_in_club = (
        db.query(models.Students)
        .filter(models.Students.selected_club_name == club_name)
        .all()
    )

    for student in students_in_club:
        if student.has_selected == 1:
            student.selected_club_name = None
            student.has_selected = 0
        elif student.is_reserved == 1:
            student.reserved_club_name = None
            student.is_reserved = 0

    db.delete(club)
    db.commit()

    return ResponseSchema(code=200, message="社团删除成功", data=None)


@router.post("/update/student", response_model=ResponseSchema, summary="更新学生信息")
def update_student(
    student_data: dict,
    db: Session = Depends(get_db),
):
    student = (
        db.query(models.Students)
        .filter_by(student_id=student_data.get("student_id"))
        .first()
    )
    if not student:
        raise HTTPException(status_code=400, detail="学生不存在")

    if student.is_reserved:
        club = (
            db.query(models.Clubs)
            .filter_by(club_name=student.reserved_club_name)
            .first()
        )
        if club:
            if club.club_status == 2:
                club.club_status = 1;
            club.remaining_quota += 1
            club.reserved_quota -= 1
            student.reserved_club_name = None
            student.is_reserved = 0
    if student.has_selected:
        club = (
            db.query(models.Clubs)
            .filter_by(club_name=student.selected_club_name)
            .first()
        )
        if club:
            if club.club_status == 2:
                club.club_status = 1;
            club.remaining_quota += 1
            student.selected_club_name = None
            student.has_selected = 0
    db.commit()
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
            if club.remaining_quota == 0:
                club.club_status = 2
            student.selected_club_name = student_data.get("selected_club_name")
            student.has_selected = 1
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
            club.reserved_quota += 1
            if club.remaining_quota == 0:
                club.club_status = 2
            student.reserved_club_name = student_data.get("reserved_club_name")
            student.is_reserved = 1

    for field, value in student_data.items():
        if field == "student_id":
            continue
        setattr(student, field, value)
    db.commit()
    db.refresh(student)

    return ResponseSchema(code=200, message="学生信息更新成功", data=None)


@router.post("/delete/student", response_model=ResponseSchema, summary="删除学生")
def delete_student(
    student_id: str = Body(..., embed=True),
    db: Session = Depends(get_db),
):
    print(f"Attempting to delete student: {student_id}")
    student = db.query(models.Students).filter_by(student_id=student_id).first()
    if not student:
        raise HTTPException(status_code=400, detail="学生不存在")

    if student.is_reserved:
        club = (
            db.query(models.Clubs)
            .filter_by(club_name=student.reserved_club_name)
            .first()
        )
        if club:
            club.remaining_quota += 1
            if club.club_status == 2:
                club.club_status = 1;
            club.reserved_quota -= 1
    if student.has_selected:
        club = (
            db.query(models.Clubs)
            .filter_by(club_name=student.selected_club_name)
            .first()
        )
        if club:
            club.remaining_quota += 1
            if club.club_status == 2:
                club.club_status = 1;

    db.delete(student)
    db.commit()

    return ResponseSchema(code=200, message="学生删除成功", data=None)
