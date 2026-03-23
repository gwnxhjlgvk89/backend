#!/usr/bin/env python3
# ============================================================
# db_manager.py
# 用法：python db_manager.py <command>
#
# 可用命令：
#   init    执行 sql/init.sql  建表
#   seed    执行 sql/seed.sql  写入样例数据
#   reset   init + seed
#   drop    执行 sql/drop.sql  删除所有表
# ============================================================

import sys
import os
import pymysql


DB_CONFIG = {
    "host": "localhost",
    "port": 3306,
    "user": "root",
    "password": "GG1214",
    "database": "club_selection",
}


# ============================================================
# 颜色输出
# ============================================================
def success(msg):
    print(f"\033[92m[✓] {msg}\033[0m")


def warning(msg):
    print(f"\033[93m[!] {msg}\033[0m")


def error(msg):
    print(f"\033[91m[✗] {msg}\033[0m")


def info(msg):
    print(f"\033[96m[>] {msg}\033[0m")


# ============================================================
# 核心：读取并执行 .sql 文件
# ============================================================
def run_sql_file(filepath: str):
    with open(filepath, "r", encoding="utf-8") as f:
        lines = f.readlines()

    # 逐行去掉注释行，保留有效 SQL 行
    cleaned = "\n".join(
        line for line in lines if line.strip() and not line.strip().startswith("--")
    )

    # 再按分号切割
    statements = [s.strip() for s in cleaned.split(";") if s.strip()]
    print(f"共解析到 {len(statements)} 条语句，开始执行...")

    conn = pymysql.connect(**DB_CONFIG)
    try:
        with conn.cursor() as cursor:
            for stmt in statements:
                cursor.execute(stmt)
        conn.commit()
        success(f"执行完毕：{filepath}")
    except Exception as e:
        conn.rollback()
        error(f"执行失败：{e}")
        sys.exit(1)
    finally:
        conn.close()


# ============================================================
# 命令定义
# ============================================================
def cmd_init():
    info("建表...")
    run_sql_file("sql/init.sql")


def cmd_seed():
    info("写入样例数据...")
    run_sql_file("sql/seed.sql")


def cmd_drop():
    warning("即将删除所有表，不可恢复！")
    if input("输入 yes 确认：").strip() != "yes":
        info("已取消")
        return
    run_sql_file("sql/drop.sql")


def cmd_reset():
    warning("即将重置数据库（drop → init → seed）")
    if input("输入 yes 确认：").strip() != "yes":
        info("已取消")
        return
    run_sql_file("sql/drop.sql")
    run_sql_file("sql/init.sql")
    run_sql_file("sql/seed.sql")
    success("重置完成 🎉")


# ============================================================
# 命令路由
# ============================================================
COMMANDS = {
    "init": (cmd_init, "执行 sql/init.sql  建表"),
    "seed": (cmd_seed, "执行 sql/seed.sql  写入样例数据"),
    "drop": (cmd_drop, "执行 sql/drop.sql  删除所有表"),
    "reset": (cmd_reset, "drop + init + seed 一键重置"),
}


def print_help():
    print("\n\033[96m用法：python db_manager.py <command>\033[0m\n")
    for cmd, (_, desc) in COMMANDS.items():
        print(f"  \033[92m{cmd:<8}\033[0m {desc}")
    print()


if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        print_help()
        sys.exit(0)

    COMMANDS[sys.argv[1]][0]()
