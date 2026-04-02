# 管理员上传数据接口
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

from crud import (
    get_clubs_with_major_restrictions_with_students,
)

from excel import export_clubs_data_to_excel

from database import get_db

router = APIRouter(prefix="/admin", tags=["管理员接口"])


@router.post("/export/all", response_model=ResponseSchema, summary="导出所有数据")
def export_all_data(
    db: Session = Depends(get_db),
):
    data = get_clubs_with_major_restrictions_with_students(db)

    excel_buffer = export_clubs_data_to_excel(data)
    with open("社团报名详情.xlsx", "wb") as f:
        f.write(excel_buffer.getbuffer())
    print("Excel文件 '社团报名详情.xlsx' 已生成！")

    return ResponseSchema(
        code=200,
        message="数据导出成功",
        data=data,
    )
