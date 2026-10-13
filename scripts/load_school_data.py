"""Load prepared school data through the public admin API only.

Two explicit stages so a person reviews the import preview before it is applied:

  preview  create clubs (or reuse an exact earlier set), upload the students in
           batches and wait for each import preview; job ids go to jobs.json.
  confirm  apply those preview jobs one at a time, then verify counts and quotas.
  verify   re-run the verification only.

Input comes from scripts/prepare_school_data.py. The admin password is read from
CLUB_ADMIN_PASSWORD or prompted; it is never accepted as an argument.
"""

import argparse
import getpass
from io import BytesIO
import json
import os
from pathlib import Path
import time

import httpx
from openpyxl import Workbook

HEADER = ("username", "name", "major", "class_name", "password", "reserved_club_id")
BATCH = 400


def api(client, method, path, **kwargs):
    response = client.request(method, "/api/v1" + path, **kwargs)
    body = response.json() if response.content else {}
    if response.status_code >= 400:
        raise SystemExit(f"{method} {path} 失败：{response.status_code} {json.dumps(body, ensure_ascii=False)}")
    return body.get("data")


def connect(args):
    client = httpx.Client(base_url=args.url, timeout=30, verify=args.ca_cert or True, trust_env=False)
    password = os.environ.get("CLUB_ADMIN_PASSWORD") or getpass.getpass(f"{args.username} 密码：")
    data = api(client, "POST", "/auth/login", json={"username": args.username, "password": password})
    if data["user"]["role"] not in {"admin", "super_admin"}:
        raise SystemExit("该账号不是管理员")
    client.headers["Authorization"] = f"Bearer {data['token']}"
    return client


def wait_job(client, job_id, states):
    for _ in range(600):
        job = api(client, "GET", f"/admin/jobs/{job_id}")
        if job["state"] in states | {"failed"}:
            return job
        time.sleep(1)
    raise SystemExit(f"任务 {job_id} 等待超时")


def preview(client, clubs, students, args_data):
    overview = api(client, "GET", "/admin/overview")
    if overview["activity"]["configured_state"] == "published":
        raise SystemExit("活动已发布，拒绝录入")
    if overview["students"]:
        raise SystemExit(f"库中已有 {overview['students']} 名学生，拒绝录入")
    existing = {c["name"]: c for c in api(client, "GET", "/admin/clubs")}
    if existing:
        # Resume only when the earlier run created exactly this club set.
        same = set(existing) == {c["name"] for c in clubs} and all(
            existing[c["name"]]["capacity"] == c["capacity"]
            and existing[c["name"]]["allowed_majors"] == c["allowed_majors"]
            and existing[c["name"]]["category"] == c["category"]
            for c in clubs
        )
        if not same:
            raise SystemExit(f"库中已有 {len(existing)} 个与本次数据不一致的社团，拒绝录入")
        print(f"复用已创建的 {len(existing)} 个社团")
    else:
        for c in clubs:
            body = {k: c[k] for k in ("name", "category", "description", "capacity", "allowed_majors")}
            existing[c["name"]] = api(client, "POST", "/admin/clubs", json={**body, "active": True})
        print(f"已创建 {len(clubs)} 个社团")

    # The worker sorts queued job rows including their JSON payload; a single
    # 1553-row payload (~420KB) exceeds MySQL's default 256KB sort buffer and
    # the job retries forever. Batches keep each payload far below that.
    jobs = []
    for start in range(0, len(students), BATCH):
        if jobs:
            time.sleep(21)  # Import uploads are limited to 3 per minute per admin.
        batch = students[start : start + BATCH]
        book = Workbook()
        sheet = book.active
        sheet.append(HEADER)
        for s in batch:
            club_id = existing[s["reserved_club"]]["id"] if s["reserved_club"] else None
            sheet.append([s["username"], s["name"], s["major"], s["class_name"], None, club_id])
        buffer = BytesIO()
        book.save(buffer)
        files = {"file": ("students.xlsx", buffer.getvalue(), "application/vnd.ms-excel")}
        job = wait_job(client, api(client, "POST", "/admin/jobs/import", files=files)["id"], {"preview"})
        if job["state"] != "preview":
            raise SystemExit(f"第{len(jobs) + 1}批预览失败：{json.dumps(job['result'], ensure_ascii=False)}")
        if job["result"]["rows"] != len(batch):
            raise SystemExit(f"第{len(jobs) + 1}批预览 {job['result']['rows']} 行，预期 {len(batch)}，未确认")
        jobs.append({"id": job["id"], "rows": len(batch), "first": batch[0]["username"]})
        print(f"第{len(jobs)}批预览通过：{len(batch)} 行")
    path = Path(args_data) / "jobs.json"
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump({"url": str(client.base_url), "jobs": jobs}, f, ensure_ascii=False, indent=1)
    print(f"共 {len(jobs)} 批 {sum(j['rows'] for j in jobs)} 行，核对无误后执行 --stage confirm")


def confirm(client, data):
    plan = json.loads((data / "jobs.json").read_text())
    if plan["url"] != str(client.base_url):
        raise SystemExit(f"jobs.json 属于 {plan['url']}，与本次目标不一致")
    for number, item in enumerate(plan["jobs"], 1):
        job = api(client, "GET", f"/admin/jobs/{item['id']}")
        if job["state"] == "done":
            print(f"第{number}批已导入，跳过")
            continue
        api(client, "POST", f"/admin/jobs/{item['id']}/confirm")
        job = wait_job(client, item["id"], {"done"})
        if job["state"] != "done":
            raise SystemExit(f"第{number}批导入失败（该批未写入）：{json.dumps(job['result'], ensure_ascii=False)}")
        print(f"第{number}批已导入 {job['result']['rows']} 名学生")


def verify(client, clubs, students):
    overview = api(client, "GET", "/admin/overview")
    actual = {c["name"]: c for c in api(client, "GET", "/admin/clubs")}
    reserved = sum(1 for s in students if s["reserved_club"])
    problems = []
    for key, expected in (("students", len(students)), ("clubs", len(clubs)), ("enrolled", reserved)):
        if overview[key] != expected:
            problems.append(f"{key}: 实际 {overview[key]}，预期 {expected}")
    if overview["inconsistencies"]:
        problems.append(f"名额不一致：{overview['inconsistencies']}")
    for c in clubs:
        a = actual.get(c["name"])
        if not a:
            problems.append(f"缺少社团 {c['name']}")
        elif (a["capacity"], a["remaining"], a["allowed_majors"]) != (
            c["capacity"],
            c["remaining"],
            c["allowed_majors"],
        ):
            problems.append(f"{c['name']}: 实际 {a['capacity']}/{a['remaining']}，预期 {c['capacity']}/{c['remaining']}")
    # Compare every student, not just totals. (The `selected` filter of this
    # endpoint currently fails with a correlation error, so it is not used.)
    found, page = {}, 1
    while True:
        data = api(client, "GET", "/admin/students", params={"page": page, "page_size": 100})
        found.update({s["username"]: s for s in data["items"]})
        if page * 100 >= data["total"]:
            break
        page += 1
    for s in students:
        a = found.get(s["username"])
        if not a:
            problems.append(f"缺少学生 {s['username']}")
        elif (a["name"], a["major"], a["class_name"], a["club_name"] or "", a["source"] or "") != (
            s["name"],
            s["major"],
            s["class_name"],
            s["reserved_club"],
            "reserved" if s["reserved_club"] else "",
        ):
            problems.append(f"学生 {s['username']} 资料或预留社团与清洗结果不一致")
    if problems:
        raise SystemExit("核对未通过：\n" + "\n".join(problems))
    print(json.dumps({"verified": True, **{k: overview[k] for k in ("students", "clubs", "enrolled")}}))


def main(args):
    data = Path(args.data)
    clubs = json.loads((data / "clubs.json").read_text())
    students = json.loads((data / "students.json").read_text())
    client = connect(args)
    try:
        if args.stage == "preview":
            preview(client, clubs, students, data)
        elif args.stage == "confirm":
            confirm(client, data)
            verify(client, clubs, students)
        else:
            verify(client, clubs, students)
    finally:
        client.close()


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--url", required=True)
    p.add_argument("--data", required=True)
    p.add_argument("--username", default="admin")
    p.add_argument("--stage", choices=["preview", "confirm", "verify"], required=True)
    p.add_argument("--ca-cert")
    main(p.parse_args())
