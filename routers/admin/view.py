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
    get_majors,
)

router = APIRouter(prefix="/admin", tags=["管理员浏览模块"])


@router.get("/clubs", summary="获取社团信息")
def get_clubs(
    db: Session = Depends(get_db),
):
    return ResponseSchema(
        code=200,
        message="获取成功",
        data=get_clubs_with_major_restrictions(db=db),
    )


@router.get("/students", summary="获取学生信息")
def get_student(
    db: Session = Depends(get_db),
):
    return ResponseSchema(
        code=200,
        message="获取成功",
        data=get_students(db=db),
    )


@router.get("/majors", summary="获取专业信息")
def get_major(
    db: Session = Depends(get_db),
):
    return ResponseSchema(
        code=200,
        message="获取成功",
        data=get_majors(db=db),
    )
