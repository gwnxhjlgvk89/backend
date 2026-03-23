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


def get_clubs_with_major_restrictions_with_students(
    db: Session, clubs: list[models.Clubs] | None = None
):
    """
    获取所有社团及其专业限制信息和已报名学生列表
    """
    if clubs is None:
        clubs = db.query(models.Clubs).all()

    club_major_restricions = db.query(models.Club_Major_Restrictions).all()
    club_major_restrictions_map = defaultdict(list)
    for r in club_major_restricions:
        club_major_restrictions_map[r.club_name].append(r.major_name)

    club_students_map = defaultdict(list)
    # ✅ 只查一次
    students_all = (
        db.query(models.Students).filter(models.Students.has_selected == True).all()
    )

    club_students_map = defaultdict(list)
    for s in students_all:
        club_students_map[s.selected_club_name].append(
            {**{k: v for k, v in s.__dict__.items() if not k.startswith("_")}}
        )

    club_list_with_students = [
        {
            **{k: v for k, v in club.__dict__.items() if not k.startswith("_")},
            "major_restrictions": club_major_restrictions_map.get(club.club_name, []),
            "students": club_students_map.get(club.club_name, []),
        }
        for club in clubs
    ]

    return club_list_with_students


def get_students(db: Session):

    students = db.query(models.Students).all()

    student_list = [
        {**{k: v for k, v in s.__dict__.items() if not k.startswith("_")}}
        for s in students
    ]

    return student_list
