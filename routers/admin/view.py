from fastapi import APIRouter, Body, HTTPException, Depends, Request
from fastapi.responses import JSONResponse
import hashlib
from sqlalchemy.orm import Session
from database import get_db
import models
from datetime import datetime

from schemas import ResponseSchema
from crud import (
    get_clubs_with_major_restrictions,
    get_clubs_with_major_restrictions_with_students,
    get_club_with_major_restrictions_with_students,
    get_students,
)

router = APIRouter(prefix="/admin", tags=["管理员浏览模块"])


@router.get("/clubs", summary="获取单一社团信息")
def get_club_with_student(
    club_id: int,
    db: Session = Depends(get_db),
):
    return ResponseSchema(
        code=200,
        message="获取成功",
        data=get_club_with_major_restrictions_with_students(club_id),
    )


@router.get("/clubs", summary="获取社团列表+学生信息")
def get_club_list_with_student(
    db: Session = Depends(get_db),
):
    return ResponseSchema(
        code=200,
        message="获取成功",
        data=get_clubs_with_major_restrictions_with_students(),
    )


@router.get("/students", summary="获取单一学生信息")
def get_student(
    student_id: int,
    db: Session = Depends(get_db),
):
    student = (
        db.query(models.Students)
        .filter(models.Students.student_id == student_id)
        .first()
    )
    return ResponseSchema(
        code=200,
        message="获取成功",
        data={**{k: v for k, v in student.__dict__.items() if not k.startswith("_")}},
    )


@router.get("/students", summary="获取学生列表")
def get_student_list(
    db: Session = Depends(get_db),
):
    return ResponseSchema(
        code=200,
        message="获取成功",
        data=get_students(),
    )
