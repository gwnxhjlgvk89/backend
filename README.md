# 社团填报系统后端 v2

Python 3.11 / FastAPI / SQLAlchemy async / MySQL / Redis。新版入口为 `club.api:app`，后台任务入口 `python -m club.worker`。

## 本地启动

```sh
uv sync --frozen
.venv/bin/python scripts/local.py start
cp .env.example .env
.venv/bin/alembic upgrade head
.venv/bin/python -m club.cli init
.venv/bin/python -m club.cli seed
.venv/bin/python -m uvicorn club.api:app --host 127.0.0.1 --port 8001 --workers 2 --no-access-log
# 另一个终端
.venv/bin/python -m club.worker
```

上述配置复制用于首次初始化；已有 `.env` 时先核对环境，不要直接覆盖。

本地依赖需要 MySQL 8.4、Redis（macOS Homebrew 安装）。数据库端口 13306、Redis 16379，数据保存在 `.local`。`seed` 仅允许非生产空库，生成 1500 个合成学生和 42 个社团。
测试账号 `student0001`～`student1500`、`admin`，合成密码 `ClubDemo2026!`。仅限本地测试，不能用于生产。

```sh
.venv/bin/python -m pytest -q
.venv/bin/ruff check club tests scripts deploy
.venv/bin/python -m club.cli check
.venv/bin/python scripts/local.py stop
```

测试固定使用本地 `club_test` 和 Redis DB15，每项测试重建测试表；不读取生产资源。API 文档 `/api/v1/docs`，健康检查 `/health/live`、`/health/ready`。

## 隔离与兼容

配置见 `.env.example`；开发环境拒绝非本地数据库、Redis 和 R2。生产必须显式配置独立凭据和 HTTPS。不要复制历史仓库中的凭据；发布前在服务提供商轮换旧凭据。

旧业务代码、自动写库测试脚本、真实名单和日志已从当前源码移除。Git 历史未改写，历史中的密钥不能因此视为已撤销。新版对旧接口统一返回 HTTP 426，提示更新；不得部署旧 `main.py`。

迁移采用独立 `v2_*` 表，不自动删除旧数据。正式环境的迁移、重置、发布均需维护窗口、已验证备份和人工确认。详见 `docs/IMPLEMENTATION.md`。

交付状态见 [docs/DELIVERY.md](docs/DELIVERY.md)，隔离Linux环境见 [deploy/README.md](deploy/README.md)。28项后端回归已通过；容量结论以最终报告为准，真机验收由用户要求暂缓。

管理员说明：[docs/ADMIN.md](docs/ADMIN.md)；接口：[docs/API.md](docs/API.md)；迁移与回滚：[docs/OPERATIONS.md](docs/OPERATIONS.md)。

最新现有环境实测结论、通过项及未达标项：[容量验收摘要](docs/CURRENT_ACCEPTANCE.md)。本项目尚未完成生产容量验收。

密码规则更新：新建账号留空初始密码时使用姓名原文；已有库升级0005会重置所有账号并要求首次改密。上面的固定演示密码仅适用于重新执行合成 seed 创建的数据，不适用于已迁移账号。迁移和回滚边界见 [PASSWORDS.md](docs/PASSWORDS.md)。
