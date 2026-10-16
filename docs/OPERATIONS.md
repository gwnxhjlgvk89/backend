# 迁移、备份与发布操作手册

> 密码迁移更新（2026-09-28）：升级到0005会重置所有学生及管理员密码为姓名原文，强制改密并使旧会话失效；0004负责删除旧哈希字段。必须先停止API/worker、备份并预演恢复，不可直接回滚旧代码。姓名非空且UTF-8不超过72字节，内部空格与中间点保留。旧表导入也采用姓名原文，旧哈希格式待确认导入预览需重传。具体步骤见 [PASSWORDS.md](PASSWORDS.md)。

2026-09-28 已按授权完成全新数据库部署，实际生产状态与回退边界见 [本次上线记录](PRODUCTION_DEPLOYMENT_20260928.md)。本文件其余迁移、重置章节是备选操作手册，本次未执行旧数据迁移。所有命令须从明确版本的后端根目录运行，先核对 `CLUB_ENV` 与目标数据库，禁止将测试 `.env` 用于生产。

## 已做的真实验证

2026-09-27，本地 `club_test` 合成数据通过 mysqldump 导出并恢复到空 `club_restore`：SHA256 一致，恢复后学生、报名、收藏与名额指纹一致。报告 `reports/backup-rehearsal.json`；加强学生全字段指纹后再次在新空库验证，见 `reports/backup-profilecheck.json`。这不等于生产备份已完成。

## 旧数据迁移

1. 维护窗口停止所有旧版写操作并备份。Alembic `upgrade head` 仅新增 v2 表和精度变更，不删除旧表。
2. 运行 `python -m club.operations legacy-plan --file .local/legacy-review.json`。报告包含数量、指纹和冲突；可能包含学生标识，文件0600，禁止提交。
3. 核对普通报名标志、预报名、旧记录表、专业限制、总名额/剩余名额、账号冲突、管理员角色。任何冲突都会阻止自动迁移，不能猜测名额后强行通过。
4. 数据修正后重新生成报告。确认维护后执行 `legacy-apply --file .local/legacy-review.json --maintenance-confirm --legacy-timezone Asia/Shanghai`。迁移要求 v2 学生及社团表为空，源指纹未变化；整批事务应用，活动保持草稿。
5. `python -m club.cli check` 核对。旧表保留，供审核后的备份与清理；新版不读取旧标志。

默认假定旧数据的无时区时间是北京时间，迁移前核实；可以明确传入其他 IANA 时区。管理员迁移后首次登录必须改密。旧表中的专业/班级字典仍保留；新版学生使用专业/班级字符串。

## 备份及恢复演练

`python -m club.operations backup --file /secure/backup-YYYYMMDD.sql`

- 活动先暂停，停止其他管理写入。
- MySQL 密码通过0600临时配置文件传递，不放进命令行。
- 同时生成 `.manifest.json` 校验和与数据指纹；备份期间数据变化则拒绝将其用于重置。
- 配置、R2/本地文件、当前部署 commit 另行备份。数据库备份不能替代头像文件备份。
- 在独立、**空的**测试数据库（名称以 `_restore` 结尾，`CLUB_ENV=test`）运行 `restore-test --file /secure/backup-YYYYMMDD.sql`。验证成功生成 `.restore-verified.json`。
- 工具禁止自动向生产恢复，也不覆盖非空恢复库。实际故障先保留新数据，不能用旧备份覆盖新报名。

## 换届重置

1. 备份并完成上面的恢复演练。
2. `reset-preview --file .local/reset-review.json` 输出当前 v2 学生、报名、收藏数量及指纹（完整学生字段仅参与哈希，预览不含明文个人资料）；向负责人展示并确认。
3. `reset-apply --file .local/reset-review.json --backup /secure/backup-YYYYMMDD.sql --actor SUPER_USERNAME --maintenance-confirm`：验证恢复凭证、备份和预览匹配；交互验证超级管理员密码并输入确认指纹。
4. 事务清理当前 v2 学生、报名、收藏、幂等记录、通知、导入导出任务；保留管理员、社团和审计，恢复名额，活动改草稿并清空时间。
5. 旧版表、历史备份和私有导出/头像文件**不会被这个工具删除**。上线清理前需要另外列出这些遗留数据的范围、数量、保留期限和删除方案。当前版本不把“v2 重置”描述为整个存储的数据清理已完成。
6. 导入本届名单，核对预报名和专业限制，再配置活动；保持未发布直到人工验收。

## 部署与回滚

- `deploy/club-api.service`、`club-worker.service` 为 systemd 模板；工作目录 `/srv/club/current` 指向不可变版本目录，持久文件 `/srv/club/shared`。
- `/etc/club/production.env` 由管理员配置0600凭据，参考模板；应用使用无登录 `club` 用户。生产为4个API worker，每进程主池15常驻+3溢出、查询预留池4连接，加独立worker固定5+5后最大98连接；上线前查询 MySQL `max_connections`，总预算不得超过70%。
- API bind 127.0.0.1:8001；Nginx HTTPS代理所有 `/api/v1/`，单独代理 WebSocket，支持6MB上传。`/health/live` 与 `/health/ready` 必须有路由，`/metrics` 不对公网开放。在http块配置上游keepalive128与WebSocket map，参考 `deploy/nginx.routes.conf`，合并到已核实的正式站点，不直接覆盖现有TLS配置。
- 维护状态统一返回503；旧业务路由全部426，删除旧的特殊代理入口，不能留下旧版报名旁路。
- `scripts/package_release.py` 只从已提交、干净的指定 commit 制作归档和 SHA256 清单，不包含 `.env`/数据库/日志/依赖。
- 在新版本目录 `uv sync --frozen --no-dev`，用生产配置做迁移预演和启动检查。数据库迁移单独审核执行。
- 维护窗口启用维护提示、备份及验证后，更新 `current` 软链接并重启指定的2个服务。验收健康、查询、测试账号流程、名额核对后才退出维护。
- 回滚只切换已验证兼容当前 schema 的代码版本。已有新报名时先暂停、保留数据库，再修复或兼容回滚，不自动降级 schema，不自动恢复旧库。
- journald 和反向代理日志应设磁盘额度与轮转；禁止记录 Authorization、完整查询字符串、Token、密码和学生资料。应用记录请求ID、路由、状态、耗时；监控看分位数、连接池等待、SQL耗时、事件循环延迟、在线WS及任务积压。

## 特批预报名（免专业限制）

个别学生经批准需要预报名到其专业不在允许名单内的社团时，管理端会提示“预报名不符合专业要求”。处理方式：

1. 管理端照常新增该学生，填写真实专业，**预报名社团选“不设置预报名”**。
2. 活动未处于报名进行中时，在服务器上执行（`--actor` 为批准人，须是启用的超级管理员）：
   `sudo python3 deploy/run-private-env.py /etc/club/production.env .venv/bin/python -m club.cli exempt-reserve --username 学号 --club-id 社团ID --actor admin`
3. 命令在一个事务中校验学生无报名、社团开放且有名额，写入带 `major_exempt` 标记的预报名，名额减一并记审计 `enrollment.exempt_reserve`。发布前检查对该记录跳过专业比较，其余检查不变。

管理端编辑该学生且预报名社团不变时，特批保留；在管理端改换或取消其预报名后，特批失效，需要重新执行命令。学生自行报名、导入名单的专业检查不受影响。

## 小程序上线

固定前后端配套 commit → 隔离环境及 iOS/Android 真机验收 → 独立审核账号/数据的体验版与审核 → 维护和生产备份 → 新后端及迁移/本届导入 → 发布小程序 → 正式入口验收 → 最后发布活动。当前不自动执行这些外部发布步骤。
