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
from fastapi.responses import StreamingResponse
from urllib.parse import quote

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


@router.get("/export/all", summary="导出所有数据", response_model=None)
def export_all_data(
    db: Session = Depends(get_db),
):
    data = get_clubs_with_major_restrictions_with_students(db)
    excel_buffer = export_clubs_data_to_excel(data)
    excel_buffer.seek(0)

    filename = "社团报名详情.xlsx"
    filename_quoted = quote(filename)  # URL 编码

    headers = {"Content-Disposition": f"attachment; filename*=UTF-8''{filename_quoted}"}

    return StreamingResponse(
        excel_buffer,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers=headers,
    )
