from fastapi import APIRouter, Body, HTTPException, Depends, Request
from fastapi.responses import JSONResponse
import hashlib
from sqlalchemy.orm import Session
from database import get_db
import models
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


router = APIRouter(prefix="/admin", tags=["管理员接口"])


@router.post("/createteststudents", summary="批量创建测试学生数据")
def createteststudents(
    count: int = Body(1000, embed=True, description="要创建的测试学生数量，默认为1000"),
    db: Session = Depends(get_db),
):

    # 批量创建 1000 个测试学生
    for i in range(1, count + 1):
        student_id = f"test{i:04d}"
        name = f"测试用户{i}"
        student = db.get(models.Students, student_id)
        if not student:
            db.add(
                models.Students(
                    student_id=student_id,
                    name=name,
                    is_pwd_changed=1,
                    major_name="大数据与会计",
                    class_name="会计2404",
                    department="test_department",
                    password_hash=hash_password(name),
                )
            )
        else:
            student.name = name
            student.major_name = "大数据与会计"
            student.class_name = "会计2404"
            student.department = "test_department"
            student.is_pwd_changed = 1
            student.has_selected = 0
            student.reserved_club_name = None
            student.selected_club_name = None

    db.commit()
    return JSONResponse(
        content={"code": 0, "message": f"成功创建/重置 {count} 个测试学生数据"}
    )
