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

from database import get_db

router = APIRouter(prefix="/admin", tags=["管理员接口"])

REQUIRED_STU_COLS = {
    "student_id",
    "name",
    "major_name",
    "class_name",
    "department",
    "is_reserved",
    "reserved_club_name",
}
REQUIRED_CLUB_COLS = {
    "club_name",
    "super_club",
    "teacher_advisor",
    "club_president",
    "description",
    "total_quota",
    "reserved_quota",
    "remaining_quota",
    "has_major_limit",
}


# 读取Excel文件并转换为DataFrame
def read_excel(upload: UploadFile) -> pd.DataFrame:
    raw = upload.file.read()
    if not raw:
        raise HTTPException(400, "上传文件为空")
    df = pd.read_excel(io.BytesIO(raw))
    df.columns = [str(c).strip() for c in df.columns]
    return df


# 去除字符串列的空格，并把 ""/nan 转 None
def trim_df(df: pd.DataFrame) -> pd.DataFrame:
    # 去空格、把 ""/nan 转 None
    for c in df.columns:
        if df[c].dtype == "object":
            df[c] = df[c].astype(str).str.strip()
            df.loc[df[c].isin(["", "nan", "None", "NaT"]), c] = None
    return df


def to_int01(v, field: str) -> int:
    if v is None:
        raise HTTPException(400, f"{field} 不能为空")
    try:
        iv = int(v)
    except:
        raise HTTPException(400, f"{field} 必须是整数(0/1)")
    if iv not in (0, 1):
        raise HTTPException(400, f"{field} 必须是 0/1")
    return iv


# 生成初始密码hash
def bcrypt_hash_from_name(name: str) -> str:
    if not name:
        raise HTTPException(400, "name 为空，无法生成初始密码")

    return hash_password(name)


# 解析社团的专业限制字符串，返回专业列表(按照;或者,或者 分割)
def parse_restrictions(raw: Optional[str]) -> List[str]:
    if raw is None:
        return []
    # 支持使用 ; , 或者任意空白字符分隔专业列表
    parts = [x.strip() for x in re.split(r"[;,\s]+", str(raw))]
    return [x for x in parts if x]


@router.post(
    "/student/import", response_model=ResponseSchema, summary="批量导入学生数据"
)
def import_students(
    file: UploadFile = File(
        ...,
        description="Excel文件，必须包含以下列：student_id, name, major_name, class_name, department, is_reserved, reserved_club_name",
    ),
    db: Session = Depends(get_db),
):
    """
    1. 解析Excel文件，验证必填列是否存在
    2. 对每行数据进行清洗和验证
    3. 根据 student_id 判断是新增还是更新
    4. 新增学生时，生成初始密码哈希（使用姓名的bcrypt哈希）
    5. 更新学生时，如果 is_pwd_changed=0 则重置密码哈希，否则保持不变
    6. 返回导入结果统计（新增多少，更新多少，失败多少）
    """
    start_time = pd.Timestamp.now()

    df = trim_df(read_excel(file))
    df = df.replace({np.nan: None})  # 把空值统一成 pd.NA，方便后续处理

    # 验证必填列
    missing_cols = REQUIRED_STU_COLS - set(df.columns)
    if missing_cols:
        raise HTTPException(400, f"缺少必填列: {', '.join(missing_cols)}")
    if df.empty:
        return ResponseSchema(
            code=0,
            message="导入成功（空数据）",
            data={"added": 0, "updated": 0, "failed": 0, "errors": []},
        )
    added, updated, failed = 0, 0, 0
    errors = []  # 记录每行的错误信息

    # 排除 student_id 的空值和重复值（Excel内先校验）
    if df["student_id"].isnull().any():
        raise HTTPException(400, "student_id 存在空值")
    if df["student_id"].duplicated().any():
        raise HTTPException(400, "student_id 存在重复值")

    try:
        with db.begin():
            # 1. 从学生表中抽取专业表(去重)
            majors_df = df[["major_name", "department"]].drop_duplicates()
            # 如果一个专业同时存在多个学院，报错
            dup_majors = majors_df["major_name"].duplicated()
            if dup_majors.any():
                dup_names = majors_df.loc[dup_majors, "major_name"].tolist()
                raise HTTPException(
                    400, f"major_name 存在重复值: {', '.join(dup_names)}"
                )
            # _是行索引，r是行数据（Series），_表示不关心这个数据
            for _, r in majors_df.iterrows():
                major_name = r["major_name"]
                department = r["department"]
                m = db.get(models.Majors, major_name)
                if not m:
                    db.add(models.Majors(major_name=major_name, department=department))
                else:
                    # 更新学院（如不希望覆盖可改成不更新）
                    # 相当于不同系的同专业，但是一般不会出现同名专业，所以暂时不做更复杂的处理了
                    m.department = department

            db.flush()  # 先把专业写入数据库，但是此时还可回滚

            # 2. 从学生表中抽取班级表
            classes_df = df[["class_name", "major_name"]].drop_duplicates()
            dup_classes = classes_df["class_name"].duplicated()
            if dup_classes.any():
                dup_names = classes_df.loc[dup_classes, "class_name"].tolist()
                raise HTTPException(
                    400, f"class_name 存在重复值: {', '.join(dup_names)}"
                )

            for _, r in classes_df.iterrows():
                class_name = r["class_name"]
                major_name = r["major_name"]
                c = db.get(models.Classes, class_name)
                if not c:
                    db.add(models.Classes(class_name=class_name, major_name=major_name))
                else:
                    # 更新专业（如不希望覆盖可改成不更新）
                    c.major_name = major_name

            db.flush()  # 把班级写入数据库，但还可回滚

            # 3. 处理学生表
            for idx, r in df.iterrows():

                try:
                    student_id = str(r["student_id"]).strip()
                    name = r["name"]
                    class_name = r["class_name"]
                    major_name = r["major_name"]
                    department = r["department"]
                    is_reserved = int(r["is_reserved"])
                    reserved_club_name = r["reserved_club_name"]

                    if not student_id or not name or not major_name or not class_name:
                        raise ValueError(
                            "student_id/name/major_name/class_name 不能为空"
                        )
                    if is_reserved not in (0, 1):
                        raise ValueError("is_reserved 必须为0或1")
                    # if has_selected == 0 and selected_club_id is not None:
                    #     raise ValueError("has_selected=0 时 selected_club_id 必须为空")

                    if not db.get(models.Classes, class_name):
                        raise ValueError(f"班级 {class_name} 不存在")
                    if not db.get(models.Majors, major_name):
                        raise ValueError(f"专业 {major_name} 不存在")

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
                                reserved_club_name=reserved_club_name,
                                password_hash=hash_password(name),
                            )
                        )
                        added += 1
                    else:
                        # 更新学生信息
                        student.name = name
                        student.major_name = major_name
                        student.class_name = class_name
                        student.department = department
                        student.is_reserved = is_reserved
                        student.reserved_club_name = reserved_club_name
                        student.password_hash = hash_password(name)
                        updated += 1
                except Exception as e:
                    failed += 1
                    errors.append(
                        f"第{idx}行: {str(e)}"
                    )  # +2 因为DataFrame索引从0开始，且Excel有表头

        print(errors)

        end_time = pd.Timestamp.now()
        duration = (end_time - start_time).total_seconds()
        print(
            f"导入完成: {added}新增, {updated}更新, {failed}失败, 耗时 {duration:.2f} 秒"
        )

        return ResponseSchema(
            code=200,
            message="导入完成",
            data={
                "added": added,
                "updated": updated,
                "failed": failed,
                "errors": errors,
            },
        )

    except HTTPException:
        raise  # 直接抛出HTTPException，FastAPI会自动转换成响应
    except Exception as e:
        # 捕获其他异常，返回500错误
        raise HTTPException(500, f"服务器错误: {str(e)}")


@router.post("/club/import", response_model=ResponseSchema, summary="批量导入社团数据")
def import_clubs(
    file: UploadFile = File(..., description="Excel文件"),
    db: Session = Depends(get_db),
):
    start_time = pd.Timestamp.now()

    df = trim_df(read_excel(file))
    df = df.replace({np.nan: None})  # 把空值统一成 pd.NA，方便后续处理

    missing_cols = REQUIRED_CLUB_COLS - set(df.columns)
    if missing_cols:
        raise HTTPException(400, f"缺少必填列: {', '.join(sorted(missing_cols))}")

    if df.empty:
        return ResponseSchema(
            code=0,
            message="导入成功（空数据）",
            data={"added": 0, "updated": 0, "failed": 0, "errors": []},
        )

    added, updated, failed = 0, 0, 0
    errors = []

    # club_name 唯一性（Excel内先校验）
    if df["club_name"].isnull().any():
        raise HTTPException(400, "club_name 存在空值")
    if df["club_name"].duplicated().any():
        raise HTTPException(400, "club_name 存在重复值")

    try:
        with db.begin():
            # majors_set 用于校验 restrictions 专业必须存在(获取专业set)
            majors_set = set(db.scalars(select(models.Majors.major_name)).all())

            # 先插入/更新 clubs
            club_name_map = {}  # 导入后再查也行，这里简单直接查
            for i, r in df.iterrows():
                try:
                    club_name = r["club_name"]
                    super_club = r.get("super_club")
                    teacher_advisor = r.get("teacher_advisor")
                    club_president = r.get("club_president")
                    description = r.get("description")
                    total_quota = int(r["total_quota"])
                    reserved_quota = int(r["reserved_quota"])
                    remaining_quota = int(r["remaining_quota"])
                    has_major_limit = int(r["has_major_limit"])

                    if total_quota < 0:
                        raise ValueError("total_quota 不能小于0")
                    if remaining_quota < 0 or remaining_quota > total_quota:
                        raise ValueError("remaining_quota 必须在[0,total_quota]")

                    if has_major_limit not in (0, 1):
                        raise ValueError("has_major_limit 必须为0或1")

                    club = (
                        db.query(models.Clubs)
                        .filter(models.Clubs.club_name == club_name)
                        .first()
                    )
                    if not club:
                        club = models.Clubs(
                            club_name=club_name,
                            description=description,
                            total_quota=total_quota,
                            remaining_quota=remaining_quota,
                            has_major_limit=has_major_limit,
                            super_club=super_club,
                            teacher_advisor=teacher_advisor,
                            club_president=club_president,
                            reserved_quota=reserved_quota,
                            club_status=2 if remaining_quota <= 0 else 1,
                        )
                        db.add(club)
                        db.flush()  # 得到 club_id
                        added += 1
                    else:
                        club.description = description
                        club.total_quota = total_quota
                        club.remaining_quota = remaining_quota
                        club.has_major_limit = has_major_limit
                        club.super_club = super_club
                        club.teacher_advisor = teacher_advisor
                        club.club_president = club_president
                        club.reserved_quota = reserved_quota
                        club.club_status = 2 if remaining_quota <= 0 else 1
                        updated += 1

                    club_name_map[club_name] = club.club_name

                except Exception as e:
                    failed += 1
                    errors.append(
                        {
                            "row": i,
                            "club_name": r.get("club_name"),
                            "error": str(e),
                        }
                    )

            # 再写 club_major_restrictions
            # 简单策略：先删后插（以Excel为准）
            for i, r in df.iterrows():
                try:
                    club_name = r["club_name"]
                    club_name = club_name_map.get(club_name)
                    if not club_name:
                        continue  # 该行 club 插入失败，跳过

                    has_major_limit = int(r["has_major_limit"])
                    # 这里是获取缩写，然后根据专业名是否包含缩写判断
                    cmra = r.get("club_major_restrictions_abbreviation")

                    # 清理旧限制（以Excel为准）
                    db.query(models.Club_Major_Restrictions).filter(
                        models.Club_Major_Restrictions.club_name == club_name
                    ).delete()

                    if has_major_limit == 0:
                        continue

                    if not cmra:
                        raise ValueError(
                            "has_major_limit=1 时 club_major_restrictions_abbreviation 不能为空"
                        )

                    majors = [x.strip() for x in str(cmra).split(";") if x.strip()]
                    if not majors:
                        raise ValueError("club_major_restrictions 解析为空")

                    for m in majors:
                        # 在 majors_set 中找到所有包含 m 的专业
                        matched = [full for full in majors_set if m in full]

                        if not matched:
                            raise ValueError(
                                f"限制专业不存在: {m}（请先在学生导入中出现该专业）"
                            )
                        for full in matched:
                            db.add(
                                models.Club_Major_Restrictions(
                                    club_name=club_name, major_name=full
                                )
                            )

                except Exception as e:
                    failed += 1
                    errors.append(
                        {
                            "row": i,
                            "club_name": r.get("club_name"),
                            "error": str(e),
                        }
                    )

        end_time = pd.Timestamp.now()
        duration = (end_time - start_time).total_seconds()
        print(
            f"导入完成: {added}新增, {updated}更新, {failed}失败, 耗时 {duration:.2f} 秒"
        )

        return ResponseSchema(
            code=0,
            message="导入完成",
            data={
                "added": added,
                "updated": updated,
                "failed": failed,
                "errors": errors,
            },
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"导入失败: {e}")
