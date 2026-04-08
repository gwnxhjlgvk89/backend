from sqlalchemy.orm import Session
from fastapi import APIRouter, HTTPException, Depends, Request
from database import get_db
from collections import defaultdict

import models


def get_club_with_major_restrictions(club_name: str, db: Session):
    club = db.query(models.Clubs).filter(models.Clubs.club_name == club_name).first()
    if not club:
        return None

    major_restrictions = (
        db.query(models.Club_Major_Restrictions)
        .filter(models.Club_Major_Restrictions.club_name == club_name)
        .all()
    )
    major_restrictions_list = [r.major_name for r in major_restrictions]

    club = {
        **{k: v for k, v in club.__dict__.items() if not k.startswith("_")},
        "major_restrictions": major_restrictions_list,
    }

    return club


def get_clubs_with_major_restrictions(
    db: Session, clubs: list[models.Clubs] | None = None
):
    """
    获取所有社团及其专业限制信息
    """
    if clubs is None:
        clubs = db.query(models.Clubs).all()

    club_major_restricions = db.query(models.Club_Major_Restrictions).all()

    club_major_restrictions_map = defaultdict(list)

    for r in club_major_restricions:
        club_major_restrictions_map[r.club_name].append(r.major_name)

    club_list = [
        {
            "club_name": club.club_name,
            "teacher_advisor": club.teacher_advisor,
            "club_president": club.club_president,
            "super_club": club.super_club,
            "description": club.description,
            "description_detail": club.description_detail,
            "cover_image": club.cover_image,
            "activity_position": club.activity_position,
            "activity_time": club.activity_time,
            "foundation_year": club.foundation_year,
            "total_quota": club.total_quota,
            "reserved_quota": club.reserved_quota,
            "remaining_quota": club.remaining_quota,
            "has_major_limit": club.has_major_limit,
            "major_restrictions": club_major_restrictions_map.get(club.club_name, []),
            "club_status": club.club_status,
        }
        for club in clubs
    ]

    return club_list


def get_club_with_major_restrictions_with_students(club_name: str, db: Session):
    club = db.query(models.Clubs).filter(models.Clubs.club_name == club_name).first()
    if not club:
        return None

    major_restrictions = (
        db.query(models.Club_Major_Restrictions)
        .filter(models.Club_Major_Restrictions.club_name == club_name)
        .all()
    )
    major_restrictions_list = [r.major_name for r in major_restrictions]

    students = (
        db.query(models.Students)
        .filter(models.Students.selected_club_name == club_name)
        .all()
    )
    students_list = [
        {**{k: v for k, v in s.__dict__.items() if not k.startswith("_")}}
        for s in students
    ]

    club_with_students = {
        **{k: v for k, v in club.__dict__.items() if not k.startswith("_")},
        "major_restrictions": major_restrictions_list,
        "students": students_list,
    }

    return club_with_students


def normalize_club_name(club_name: str) -> str:
    """
    规范化社团名称：
    1. 移除所有空格（包括前后和中间）
    2. 统一各种不规范引号为标准英文双引号 "

    Args:
        club_name: 原始社团名称

    Returns:
        规范化后的社团名称

    Examples:
        >>> normalize_club_name('职"行生涯社')
        '职"行生涯社'  # 英文双引号保持不变

        >>> normalize_club_name('职"行生涯社')  # 中文智能引号
        '职"行生涯社'  # 转为英文双引号

        >>> normalize_club_name('大学 生 会')
        '大学生会'

        >>> normalize_club_name('「编程」社')
        '"编程"社'  # 方括号引号转为英文双引号
    """
    if not club_name:
        return ""

    # 移除所有空格（包括中文空格）
    normalized = club_name.replace(" ", "").replace("\u3000", "")

    # 统一各种不规范引号为标准英文双引号 "
    # 中文智能引号："" (U+201C U+201D)
    normalized = normalized.replace("\u201c", '"')  # 左中文智能引号 "
    normalized = normalized.replace("\u201d", '"')  # 右中文智能引号 "

    # 中文单引号：'' (U+2018 U+2019)
    normalized = normalized.replace("\u2018", '"')  # 左中文单引号 '
    normalized = normalized.replace("\u2019", '"')  # 右中文单引号 '

    # 方括号引号：「」(U+300C U+300D)
    normalized = normalized.replace("\u300c", '"')  # 左方括号 「
    normalized = normalized.replace("\u300d", '"')  # 右方括号 」

    # 双层方括号：『』(U+300E U+300F)
    normalized = normalized.replace("\u300e", '"')  # 左双层方括号 『
    normalized = normalized.replace("\u300f", '"')  # 右双层方括号 』

    # 其他不规范引号
    normalized = normalized.replace("\u201e", '"')  # 低位双引号 „
    normalized = normalized.replace("\u201f", '"')  # 高位反向引号 ‟

    # 保留英文单引号 '，如需替换为双引号取消下一行注释
    # normalized = normalized.replace("'", '"')

    return normalized


def get_base_club_name(club_name: str) -> str:
    """
    获取社团名称的基础形式（去掉末尾的"社"字）
    用于判断名称等效性：\"商务大数据分析\" 和 \"商务大数据分析社\" 等效

    Args:
        club_name: 原始或已规范化的社团名称

    Returns:
        去掉末尾\"社\"字后的基础名称

    Examples:
        >>> get_base_club_name(\"商务大数据分析社\")
        \"商务大数据分析\"

        >>> get_base_club_name(\"商务大数据分析\")
        \"商务大数据分析\"
    """
    normalized = normalize_club_name(club_name)
    if normalized.endswith("社"):
        return normalized[:-1]
    return normalized


def clubs_name_equivalent(name1: str, name2: str) -> bool:
    """
    判断两个社团名称是否等效
    规则：末尾是否有\"社\"字不影响等效性

    Args:
        name1: 第一个社团名称
        name2: 第二个社团名称

    Returns:
        如果两个名称等效返回 True，否则返回 False

    Examples:
        >>> clubs_name_equivalent(\"商务大数据分析\", \"商务大数据分析社\")
        True

        >>> clubs_name_equivalent(\"微短剧创作\", \"微短剧创作社\")
        True

        >>> clubs_name_equivalent(\"掼蛋社\", \"掼蛋社\")
        True
    """
    return get_base_club_name(name1) == get_base_club_name(name2)


def get_clubs_with_major_restrictions_with_students(db, clubs: list = None):
    """
    获取所有社团及其专业限制信息和已报名学生列表

    重要：所有社团名称都会进行规范化处理，确保不同格式的名称能正确关联
    并且末尾\"社\"字的有无不影响数据关联
    """
    print("正在获取社团列表及其专业限制和学生信息...")

    if clubs is None:
        clubs = db.query(models.Clubs).all()

    # ✅ 查询专业限制时使用规范化的社团名称进行匹配
    # 使用 get_base_club_name 确保末尾是否有"社"字都能正确匹配
    club_major_restricions = db.query(models.Club_Major_Restrictions).all()
    club_major_restrictions_map = defaultdict(list)
    for r in club_major_restricions:
        base_name = get_base_club_name(r.club_name)
        club_major_restrictions_map[base_name].append(r.major_name)

    # ✅ 只查一次，查询学生时使用规范化的社团名称
    students_all = (
        db.query(models.Students)
        .filter(
            (models.Students.has_selected == True)
            | (models.Students.is_reserved == True)
        )
        .all()
    )

    club_students_map = defaultdict(list)
    for s in students_all:
        # 优先使用 selected_club_name，否则使用 reserved_club_name
        club_name = s.selected_club_name or s.reserved_club_name
        if club_name:
            # 使用基础名称作为 key，忽略末尾是否有"社"字
            base_name = get_base_club_name(club_name)
            student_dict = {
                k: v for k, v in s.__dict__.items() if not k.startswith("_")
            }
            club_students_map[base_name].append(student_dict)

    # ✅ 构建返回数据，使用规范化的社团名称
    club_list_with_students = []
    for club in clubs:
        base_name = get_base_club_name(club.club_name)
        normalized_name = normalize_club_name(club.club_name)
        club_data = {
            **{k: v for k, v in club.__dict__.items() if not k.startswith("_")},
            "normalized_name": normalized_name,  # 新增规范化后的名称（含"社"字）
            "base_name": base_name,  # 新增去掉末尾"社"字的基础名称（用于匹配）
            "major_restrictions": club_major_restrictions_map.get(base_name, []),
            "students": club_students_map.get(base_name, []),
        }
        club_list_with_students.append(club_data)

    return club_list_with_students


def get_students(db: Session):

    students = db.query(models.Students).all()

    student_list = [
        {**{k: v for k, v in s.__dict__.items() if not k.startswith("_")}}
        for s in students
    ]

    return student_list


def get_majors(db: Session):
    majors = db.query(models.Majors).all()

    major_list = [
        {**{k: v for k, v in m.__dict__.items() if not k.startswith("_")}}
        for m in majors
    ]

    return major_list
