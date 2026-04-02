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

    student_cols_prefix = "student_"
    all_possible_student_keys = set()
    for row_dict in all_rows:
        for key in row_dict:
            if key.startswith(student_cols_prefix):
                all_possible_student_keys.add(key)

    for col in all_possible_student_keys:
        if col not in df.columns:
            df[col] = None

    club_columns = [
        col for col in df.columns if not col.startswith(student_cols_prefix)
    ]
    student_columns = sorted(
        [col for col in df.columns if col.startswith(student_cols_prefix)]
    )

    # ✅ 让 club_name 在第一列
    if "club_name" in df.columns:
        club_columns = ["club_name"] + [c for c in club_columns if c != "club_name"]

    df = df[club_columns + student_columns]

    # ✅ 为了合并：确保相同 club_name 连续
    if "club_name" in df.columns:
        df = df.sort_values(by=["club_name"], kind="stable").reset_index(drop=True)

    output = io.BytesIO()

    # 1) 为了保证相同 club_name 连续：在写入前先排序（只做一次 to_excel）
    if "club_name" in df.columns and len(df) > 0:
        df_sorted = df.copy()
        df_sorted["club_name"] = df_sorted["club_name"].fillna("").astype(str)
        df_sorted = df_sorted.sort_values(by="club_name", kind="stable").reset_index(
            drop=True
        )
    else:
        df_sorted = df

    with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
        sheet_name = "社团报名情况"
        df_sorted.to_excel(writer, index=False, sheet_name=sheet_name)

        worksheet = writer.sheets[sheet_name]
        first_data_row = 1  # 第0行是表头

        # 2) 计算 club 部分列在 df_sorted 中的真实列索引（从0开始对应Excel列）
        if "club_name" in df_sorted.columns and len(df_sorted) > 0:
            club_idxs = [
                df_sorted.columns.get_loc(c)
                for c in club_columns
                if c in df_sorted.columns
            ]

            # 建议：先把 NaN/INF 全处理掉，降低出错概率
            df_sorted = df_sorted.replace([np.inf, -np.inf], np.nan).fillna("")

            # 3) 生成连续分组：同 club_name 的行连续时才会合并
            norm_name = df_sorted["club_name"].fillna("").astype(str)
            group_id = (norm_name != norm_name.shift(1)).cumsum()

            for _, g in df_sorted.groupby(group_id, sort=False):
                if len(g) <= 1:
                    continue

                start_i = g.index.min()
                end_i = g.index.max()

                # 合并 club 部分所有列（包括 club_name）
                for col_idx in club_idxs:
                    worksheet.merge_range(
                        first_data_row + start_i,
                        col_idx,
                        first_data_row + end_i,
                        col_idx,
                        g.iloc[0, col_idx],
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
