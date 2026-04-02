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
    )
    db.add(new_admin)
    db.commit()

    return ResponseSchema(
        code=200, message="管理员账号创建成功", data={"username": username}
    )
