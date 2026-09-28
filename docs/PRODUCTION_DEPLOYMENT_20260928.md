# 2026-09-28 全新数据库生产部署记录

> 后续已获用户授权，在同一正式主机和公网入口切换隔离合成数据完成 1500 人实测。实际套餐为 **4 核 / 4GB / 5Mbps**，整体容量未通过，主要证据指向公网回程；测试后生产配置恢复、正式库全表指纹不变。详见 [腾讯云容量与网络诊断](TENCENT_PRODUCTION_CAPACITY.md)。下文保留最初部署验收记录。

本次已按授权切换 `https://wjy-1214.cloud` 后端，保留原服务器4核/约4GB，未升级资源。旧系统完整备份后停用，旧数据未迁移。未上传、提审或发布小程序，未开放报名。容量结论仍以隔离压测报告为准，本次生产验收仅验证部署、功能和空闲稳定性。

## 交付版本与目录

- 应用基线：`bb393fe0048200f9f37dee25d7ca16829bc2d3a2`。
- 部署工具提交：`3922c0a`、`81adef2`，没有修改业务功能。
- 实际部署：`81adef2bfa4441fc54d014f445e1f81383242a13`，版本目录 `/srv/club/releases/81adef2bfa4441fc54d014f445e1f81383242a13`，`/srv/club/current` 指向该目录。
- 发布包 SHA256：`89f4dab71224158ba82e794be5cc8f3f6343be13573be5fe3444397b687c868a`。
- 后续上线记录提交仅包含文档/证据，不改变服务器版本。所有提交留在本地 `develop`，没有 push；前端仍为 `210eaaa`，本次无修改。

使用独立 Python 3.11.15，旧 Conda 环境未修改。官方源下载缓慢，实际安装采用 `uv export --frozen --no-dev --no-emit-project` 导出锁定依赖，再使用腾讯云 HTTPS 镜像执行 `uv pip sync --require-hashes`，版本及哈希仍由 `uv.lock` 约束。依赖清单位于服务器 `/etc/club/locked-requirements.txt`。

## 旧系统备份与恢复证据

旧服务 `club-system.service` 停止写入、Nginx 进入维护后，原生 `mysqldump` 导出 `club_selection` 的全部表，并开启 routines/events/triggers 导出选项。SQL 不含 `CREATE DATABASE` 或 `USE` 语句。恢复到独立临时库后，对全部12张表逐一比较行数、完整行内容指纹和建表语句指纹，全部一致；临时恢复库随后删除。

备份含旧代码、本地附件、systemd、Nginx、证书及续期、MySQL 和 Redis 配置。旧外部存储配置留在私密代码归档中，另将两处对象存储地址记录于服务器 `/etc/club/legacy-external-storage.json` 和本机 `.local/production-20260928/legacy-external-storage.json`，未删除远端对象。`pre-cutover-config.tar.gz` 保存修改前配置，`legacy-files.tar.gz` 中 Nginx 已处于维护状态，回退时必须区分二者。

- 服务器：`/srv/club/backups/legacy-20260928-200203`。
- 本机：后端 `.local/production-20260928/legacy-20260928-200203`，另有完整外层 `legacy-backup.tar.gz`。
- 目录700、文件600；本机三份归档 SHA256 与服务器一致。SQL/配置/凭据未进入 Git。
- 旧库和旧代码保留；新版应用账号无旧库访问权限。

| 文件 | SHA256 |
|---|---|
| database.sql | ee4d3151e2c8c24fd934ed8f526d282e4a763766707d9851b915957d359243bd |
| legacy-files.tar.gz | 7f009cc230ff451f270c1275ed626ebd33ae72751e78f028dbf2539d43fed84c |
| pre-cutover-config.tar.gz | e46cdf5c7b8b924b64c67ab67d117b61594fcb299a1e4d7bb4f0c5e14ac23a72 |

主要旧数据数量：2367学生、42社团、5管理员、263收藏；全部表数量见 [备份收据](../reports/production-20260928/backup-result.json)。

## 生产配置与结束状态

| 项目 | 实际状态 |
|---|---|
| 数据库 | 独立 `club_v2_prod`，utf8mb4，Alembic head 0005 |
| 初始数据 | 1个超级管理员 `admin`；0学生、0社团、0报名、0任务 |
| 活动 | 草稿，开始/结束时间为空 |
| 管理员密码 | 随机生成，保留首次强制改密；只在私密文件交付 |
| 应用账户 | 新库 SELECT/INSERT/UPDATE/DELETE；无旧库访问权限 |
| 迁移账户 | 与应用分离，迁移后 ACCOUNT LOCK |
| 服务 | `club-api` 4个API worker + `club-worker` 独立进程，无登录 `club` 用户 |
| 连接预算 | API每进程15+3主池、4查询池；worker最多10；总98/151 |
| MySQL | buffer pool 768MiB，动态设置及配置文件均生效 |
| Redis | DB1，前缀 `club:prod:v2`；192MiB/noeviction；未清空旧数据 |
| 文件存储 | `/srv/club/shared/uploads`，本地持久存储，无头像服务 |
| 私密配置 | `/etc/club/production.env`，root0600，全新 JWT 密钥 |
| API监听 | 仅 `127.0.0.1:8001`；旧8000及验收8002均无监听 |
| 日志 | journald namespace `club`，128MiB额度/14天保留；Nginx由logrotate管理 |
| 旧服务 | 停止且禁用自启动，旧代码/数据库保留 |

Nginx 验证配置后 reload，保留域名、TLS 和证书续期；当前证书到2026-10-29，certbot.timer active。公网 `/api/v1/`、WebSocket、健康检查可用，`/metrics` 返回403，旧业务接口返回426。旧小程序可能表现为登录或网络错误。访问日志不记录查询参数；WebSocket 路由关闭票据可能出现的日志，Uvicorn 使用 warning 级别。

管理员凭据位于服务器 `/etc/club/admin-initial.json` 和本机后端 `.local/production-20260928/admin-credentials.json`，文件权限600。首次改密后该文件中的初始密码失效；不要提交或转发凭据文件。

## 验收

隔离库 `club_v2_verify`、Redis DB2/独立前缀、8002端口完成：空库建表、管理员登录及改密、权限拒绝、学生/社团管理、Excel预览确认、后台导出下载、草稿拒绝报名、专业限制、满额、报名/退选、名额一致性、WebSocket事件、API/worker重启后结果保留及重连。通过后删除验收库/账户/文件/配置/服务，仅保留验收报告，未将测试数据写入正式库。

正式域名验证：TLS证书链校验、live/ready、管理员登录、首次改密限制、匿名401、WebSocket resync、报名拒绝、旧接口426、metrics403、旧库访问拒绝均通过。正式管理员没有为测试而修改初始密码。

- [隔离验收](../reports/production-20260928/isolated-acceptance.json)
- [正式入口验收](../reports/production-20260928/public-acceptance.json)
- [最终资源与数据状态](../reports/production-20260928/final-state.json)

10分钟生产观察实际持续600.08秒、采样61次：122次本机/正式HTTPS健康检查全部200；所有服务进程身份保持不变、重启0、OOM增量0；MySQL/Redis始终可用，outbox积压0，应用错误/警告和Nginx 5xx均为0。API进程组内存293.8–296.0MiB，后台worker54.3–54.6MiB，服务器可用内存最低2252.6MiB；Swap占用最高0.5MiB。服务器业务模块指纹与本地部署源文件一致。从本机独立访问公网ready同样200且TLS校验通过。

完整证据：[监控摘要](../reports/production-20260928/monitor-summary.json)、[61次原始采样](../reports/production-20260928/monitor-samples.json)。这些为空业务、低负载观察数据，不等同于腾讯云1500人容量验收；未对生产报名接口压测。

## 维护与故障处理

1. 进入维护：`sudo touch /srv/club/shared/maintenance.on`。Nginx 即时返回503，无需重启；健康问题仍可通过本机8001排查。
2. 查看服务：`sudo systemctl status club-api club-worker`；日志：`sudo journalctl --namespace=club -u club-api -u club-worker`。不要将私密环境文件内容打印到聊天或日志。
3. 已有新版正式数据时，先暂停操作、备份新库和文件，再修复或切换到兼容0005的新版代码。禁止用旧库覆盖新数据，禁止自动重新开放旧版。
4. 尚未开始录入且确定需要撤销本次切换时，也先保存新库与诊断信息。停止新服务，从私密 `pre-cutover-config.tar.gz` 中选择恢复原Nginx配置（不要整包覆盖系统）；移除本次专属Nginx include冲突，`nginx -t`通过后才reload。启动旧 `club-system` 使用保留的旧库。回退恢复公网业务属于单独人工决定，不作为自动故障动作。
5. 新版恢复正常并验证后，`sudo rm /srv/club/shared/maintenance.on` 退出维护。活动继续保持草稿，录入/核对本届数据及新版小程序发布完成后再单独开放。

后续数据库迁移需由管理员暂时解锁迁移账户，使用私密迁移配置执行已审核迁移，结束后重新锁定；应用账号不授予DDL权限。
