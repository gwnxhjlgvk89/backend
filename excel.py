import pandas as pd
import numpy as np
import io
from typing import List, Dict, Any


def export_clubs_data_to_excel(
    clubs_data: List[Dict[str, Any]], output_filename: str = "clubs_with_students.xlsx"
) -> io.BytesIO:
    all_rows = []

    for club in clubs_data:
        club_info = {
            k: v for k, v in club.items() if k not in ["major_restrictions", "students"]
        }

        club_info["major_restrictions"] = (
            ", ".join(club["major_restrictions"]) if club["major_restrictions"] else ""
        )

        if club.get("students"):
            for student in club["students"]:
                row = {**club_info, **{f"student_{k}": v for k, v in student.items()}}
                all_rows.append(row)
        else:
            row = {**club_info}
            all_rows.append(row)

    df = pd.DataFrame(all_rows)

    # ===== 明确：你要保留的 club 字段（原字段名，用于逻辑/合并）=====
    ordered_club_columns = [
        "club_name",
        "teacher_advisor",
        "club_president",
        "total_quota",
        "remaining_quota",
        "reserved_quota",
        "has_major_limit",
    ]
    existing_club_columns = [c for c in ordered_club_columns if c in df.columns]

    # ===== 明确：你要保留的 student 字段（原字段名，用于逻辑/合并）=====
    ordered_student_columns = [
        "student_student_id",
        "student_name",
        "student_major_name",
        "student_department",
        "student_class_name",
    ]
    existing_student_columns = [c for c in ordered_student_columns if c in df.columns]

    # 只保留需要的列
    keep_cols = existing_club_columns + existing_student_columns
    df = df[keep_cols] if keep_cols else df

    # 为合并准备：确保 NaN/INF 不会影响 merge_range
    df = df.replace([np.inf, -np.inf], np.nan).fillna("")

    # 确保相同 club_name 连续
    if "club_name" in df.columns and len(df) > 0:
        df_sorted = df.copy()
        df_sorted["club_name"] = df_sorted["club_name"].astype(str)
        df_sorted = df_sorted.sort_values(by=["club_name"], kind="stable").reset_index(
            drop=True
        )
    else:
        df_sorted = df

    # =========================
    # 仅用于写入 Excel 的中文列名映射（不改你的合并逻辑字段）
    # =========================
    col_cn_map = {
        # club
        "club_name": "社团名称",
        "teacher_advisor": "指导老师",
        "club_president": "社长",
        "total_quota": "招生名额",
        "remaining_quota": "剩余名额",
        "reserved_quota": "已预留名额",
        "has_major_limit": "是否有专业名额限制",
        # student
        "student_student_id": "学生学号",
        "student_name": "姓名",
        "student_major_name": "专业",
        "student_department": "学院",
        "student_class_name": "班级",
    }

    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
        sheet_name = "社团报名情况"

        # 写入前把列名换成中文；列顺序不变，所以合并列索引仍然正确
        df_to_write = df_sorted.rename(columns=col_cn_map)

        df_to_write.to_excel(writer, index=False, sheet_name=sheet_name)

        worksheet = writer.sheets[sheet_name]
        first_data_row = 1  # 0行为表头，数据从1开始

        # club 部分列在 Excel 中的索引（基于原 df_sorted 列顺序）
        club_idxs = [df_sorted.columns.get_loc(c) for c in existing_club_columns]

        if (
            "club_name" in df_sorted.columns
            and len(df_sorted) > 0
            and len(club_idxs) > 0
        ):
            norm_name = df_sorted["club_name"].fillna("").astype(str)
            group_id = (norm_name != norm_name.shift(1)).cumsum()

            for _, g in df_sorted.groupby(group_id, sort=False):
                if len(g) <= 1:
                    continue

                start_i = g.index.min()
                end_i = g.index.max()

                # 用组内第一个单元格的值作为合并内容
                for col_idx in club_idxs:
                    val = g.iloc[0, col_idx]
                    if pd.isna(val):
                        val = ""

                    worksheet.merge_range(
                        first_data_row + start_i,
                        col_idx,
                        first_data_row + end_i,
                        col_idx,
                        val,
                    )

    output.seek(0)
    return output


# 示例用法（在实际应用中，clubs_data 会由你的 API 接口提供）
if __name__ == "__main__":
    # 假设这是 get_clubs_with_major_restrictions_with_students 返回的模拟数据
    sample_data = [
        {
            "teacher_advisor": "刘颖",
            "club_name": '"职"行生涯社',
            "description": "掌握科学的求职方法，提升求职就业能力",
            "total_quota": 15,
            "remaining_quota": 8,
            "has_major_limit": 0,
            "club_president": "会计2504谢怡湘",
            "super_club": '"小先生"兴趣社',
            "reserved_quota": 7,
            "club_status": 1,
            "major_restrictions": [],
            "students": [],
        },
        {
            "teacher_advisor": "刘淼龙",
            "club_name": "“小先生”宣讲社",
            "description": "提高社团成员的宣讲技巧、语言表达能力和逻辑思维",
            "total_quota": 27,
            "remaining_quota": 17,
            "has_major_limit": 0,
            "club_president": "跨境2502卢佳轩",
            "super_club": "“小先生”宣讲社",
            "reserved_quota": 10,
            "club_status": 1,
            "major_restrictions": [],
            "students": [
                {
                    "phone": None,
                    "department": "商务管理学院",
                    "name": "徐玲慧",
                    "student_id": "2025319240",
                    "class_name": "会计2505",
                    "major_name": "大数据与会计",
                },
                {
                    "phone": None,
                    "department": "商务管理学院",
                    "name": "胡峻熙",
                    "student_id": "2025320210",
                    "class_name": "跨境2502",
                    "major_name": "跨境电子商务",
                },
            ],
        },
        {
            "teacher_advisor": "王老师",
            "club_name": "编程兴趣社",
            "description": "学习Python编程",
            "total_quota": 20,
            "remaining_quota": 10,
            "has_major_limit": 1,
            "club_president": "计科2501张三",
            "super_club": "技术类社团",
            "reserved_quota": 5,
            "club_status": 1,
            "major_restrictions": ["计算机科学", "软件工程"],
            "students": [
                {
                    "phone": "13800001234",
                    "department": "信息工程学院",
                    "name": "李四",
                    "student_id": "2025100001",
                    "class_name": "计科2501",
                    "major_name": "计算机科学",
                }
            ],
        },
    ]

    # 导出Excel文件
    excel_buffer = export_clubs_data_to_excel(sample_data, "社团报名详情.xlsx")

    # 在实际应用中，你可以将这个 BytesIO 对象作为 FastAPI 的 FileResponse 返回
    # from fastapi.responses import FileResponse
    # return FileResponse(excel_buffer, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", filename="社团报名详情.xlsx")

    # 为了演示，我们将其写入一个文件
    with open("社团报名详情.xlsx", "wb") as f:
        f.write(excel_buffer.getbuffer())
    print("Excel文件 '社团报名详情.xlsx' 已生成！")
