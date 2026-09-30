# 隔离测试部署与生产模板

所有容量与故障脚本仅用于 `CLUB_ENV=test`、`club_test` 数据库、`club:test` Redis前缀和纯 `load*` 合成账号；不执行生产报名压测。

## 审核体验环境（2026-09-30）

`https://wjy-1214.cloud` 当前使用正常生产运行配置，但连接独立的 **`club_v2_review` 模拟体验库**。应用仍为 Claude 已部署的 `53fc191af98204305294a583f2a1f87bd554315c`，本次没有修改业务规则、前端或发布小程序。原 `club_test` 压测库及其配置保留。

- `/etc/club/review.env`、`review-migrate.env` 分别使用独立的应用和迁移数据库账户，文件权限0600。应用账户只有审核库的查询和业务写权限。
- Redis使用逻辑库3及 `club:review:v1` 前缀；持久文件位于 `/srv/club/shared/review-files`。没有清空其他Redis库。
- 两个systemd服务通过各自 `20-review.conf` drop-in加载审核环境；4个API进程及独立worker保持原配置。
- 库内为8个完整模拟社团、3个体验学生、1个超级管理员。活动和详情明确标记模拟资料，没有真实学生或真实报名。
- 仅模拟活动开放报名和退选，截止北京时间 **2026-11-30 23:59:59**。不是正式招新开放时间；若提前导入真实名单，应先按下述流程结束体验环境。
- `review01` 为计算机专业，`review02` 为艺术专业；两者已通过正常首次改密流程。`review03` 保留首次改密体验。超级管理员仍须首次改密；不要把管理员凭据提供给审核人员。
- 一个账号再次登录会使此前会话失效，避免多人共用同一体验账号。修改名单或社团前须先在管理端暂停模拟活动，修改完再恢复。

新增 `deploy/initialize-review.py` 仅接受生产配置、loopback数据库 `club_v2_review` 和审核专用Redis前缀；检查所有业务表为空，事务初始化，保持活动草稿。显式提供带时区的截止时间及0700目录中的新凭据文件，拒绝覆盖已有文件或数据。示例（先由运维建立独立库、账户及环境文件，并通过迁移账户执行 `alembic upgrade head`）：

```sh
sudo /srv/club/current/.venv/bin/python /srv/club/current/deploy/run-private-env.py \
  /etc/club/review.env /srv/club/current/.venv/bin/python /path/to/initialize-review.py \
  --credentials /private/review/credentials.json --ends-at 2026-11-30T15:59:59Z
```

初始化工具在提交 `8f076d7` 中；服务器通过独立运维脚本使用它，没有改写不可变的应用版本目录。初始化后走正常API完成登录、改密和发布模拟活动，不增加审核专用接口或资格绕过。当前环境已初始化，**不要重复执行**。

本次功能证据见 `reports/review-environment-20260930.json`：内部和HTTPS域名验证了登录、改密、浏览、专业限制、报名幂等、退选、收藏、WSS名额事件及权限；最终无报名/收藏残留，无名额差异、待投递事件或服务异常重启。本机公网访问另经现有macOS网络路径验证（DNS返回代理fake IP，不作为直连或容量证据）。未做微信真机验收或新的容量测试。

切换前备份位于服务器 `/var/backups/club/review-20260930/`，本机副本在忽略目录 `.local/review-20260930/`；包括旧压测库、服务与Nginx等配置、校验清单。SQL已恢复到独立临时库，核对全部表行数和列定义后删除验证库。凭据单独保存在上述私有目录，禁止进入Git或公开报告。

真实名单到位后：暂停体验操作，备份体验库；创建并迁移独立的 `club_v2_prod`，初始化正式管理员和草稿活动，录入/核对真实社团、学生、预报名和时间；再切换服务环境、Redis前缀及存储目录并重启验证。不要把体验报名或压测账号迁入正式库，不要直接在已开放的模拟活动中导入真实名单。域名与API契约未变且前端代码不变时，名单更换无需重新打包前端。

若本次环境需要回退，先开启维护并备份审核库，再恢复切换前服务配置（移除本次两个 `20-review.conf`，保留其他drop-in），执行daemon-reload与服务重启。原环境是压测库，恢复后应保持公网维护，不能当作正式业务重新开放。

## 当前测试机复现

Ubuntu测试机安装Podman / podman-compose / uidmap / slirp4netns / aardvark-dns，使用普通用户。后端代码放在 `~/club-system-test/backend`，私有配置和数据不打入代码包。

1. `python3 deploy/init-test-env.py` 首次创建0600随机私有配置；在创建前将脚本中的测试IP改为自己的独立测试网卡地址。不要将它设为生产地址。
2. `CONTAINERS_CONF_OVERRIDE=$PWD/deploy/containers.conf podman build --network slirp4netns -f deploy/Dockerfile -t localhost/club-system-test:dev .`
3. `CONTAINERS_CONF_OVERRIDE=$PWD/deploy/containers.conf podman-compose -p club-capacity-test --env-file "$PWD/deploy/.env.test" -f deploy/compose.test.yml up -d`。Compose日志可能回显环境变量，重定向到私有 `.local/compose.log`，不要上传或提交。
4. **每次重建容器后**运行 `python3 deploy/limit-test-pod.py`。compose中的 `cgroup_parent` 在当前Podman版本下不能保证生效；必须找到实际共享pod slice并核实CPUQuota=400%、MemoryMax=3000MiB、MemorySwapMax=0。仅有一个空slice文件不算限制成功。
5. 检查Nginx容器的 `/etc/resolv.conf`；`nginx.test.conf`中的resolver须与实际隔离网络DNS一致。动态解析用于API容器重启后IP改变的恢复，生产模板使用固定loopback地址。
6. 空库执行 `podman exec club-capacity-test_api_1 alembic upgrade head`，再执行 `python -m club.load_fixture seed`（同样在API容器内）。生成3000合成账号、42社团，不对外提供HTTP重置接口。
7. Mac作为独立压测机运行 `python scripts/load_remote.py --url http://TEST_IP:18081 --hold-seconds 600 --rounds 3`；先建立供脚本使用的SSH ControlMaster。登录1500人/60秒、报名突发在0.85秒内计划发出（早期诊断脚本为0.95秒），报告记录实际dispatch跨度，不能以计划值替代。
8. 压测完成后单独运行 `scripts/fault_remote.py --url ...`。它会停止/恢复**命名测试容器**的worker、Redis并重启API，请勿与容量测试重叠。
9. 超容量另运行 `--users 3000 --rounds 3 --hold-seconds 90`。业务拒绝、429、503和传输错误分别统计；`data_consistency_pass`核对成功报名数与数据库占位，`correctness_pass`还要求期望全部可用名额得到响应确认。

数据库与Redis不发布主机端口，HTTP只绑定明确测试网卡；服务共用4CPU/3000MiB预算，MySQL1152MiB、API900MiB、worker192MiB、Redis192MiB、Nginx512MiB。3000人HTTPS场景曾触及Nginx原384MiB上限，因而从MySQL原1280MiB上限调拨128MiB，总预算不增加；MySQL buffer pool仍为768MiB。4个API进程，每进程写入等主池15+3连接、身份/结果查询预留池4连接；独立worker固定5+5，连接预算98/150=65.3%。查询预留池不用于报名写入，避免超容量时写请求耗尽全部查询连接。

资源报告包括每容器RSS、内存峰值、OOM计数和CPU累计时间；压测机记录整机与压测进程CPU、RSS和事件循环延迟。Podman `cpu_percent`是容器运行以来平均值，不能当作瞬时CPU峰值。此次测试主机的单核性能/NVMe与生产云机不同，带宽复现仅为测试Nginx出口限速、未复现公网RTT/TLS/丢包，不能宣称完全同硬件验收。

停止测试：从本目录使用相同compose参数执行 `stop`。保留命名卷供复核，默认不执行 `down -v`。

## 生产

`club-api.service`、`club-worker.service`、`nginx.routes.conf`、`production.env.example`为待审核模板。先参考 `docs/OPERATIONS.md`，核实生产MySQL连接预算、HTTPS站点、维护与备份；不直接覆盖运行中的配置。本开发任务没有执行生产部署、数据清理、提审或发布。

超容量保护：Nginx对报名POST/DELETE设置全局1500个进行中请求上限，登录POST单独设置1600个进行中请求上限，超过时返回带请求ID和Retry-After的JSON 429；GET结果查询使用空限流键，不计入写入限额。此限额不按IP计算，避免误伤校园共享出口。正常1500人验收仍必须无容量429，不能用限流冒充达标。依据 [Nginx limit_conn 官方语义](https://nginx.org/en/docs/http/ngx_http_limit_conn_module.html)，空key不参与计数。测试Nginx连接上限设为16384，覆盖3000WS及代理连接。

3000人超容量测试先在120秒内登录准备令牌，再执行1秒报名突发；这不是3000人60秒登录达标的声明。压测HTTP连接池也按用户数扩展，避免3000条WS占据固定连接池后在压测机侧悄悄排队。超容量场景每轮另发20次结果查询，直接检查查询可用性。

通知延迟的精确核对使用合成测试库的 `(club_id,version)` 对应出站事件时间与客户端收到时间匹配；批次最早入队时间作为保守上界单列，不能混同为每条名额变更的实际延迟。该核对CLI只读取测试库，不增加生产消息里的学生资料或冗余时间字段。

`python scripts/check_capacity.py reports/linux-capacity-confirmation.json` 可只读汇总门槛，失败时退出码1。默认报名P95为3秒，`--enrollment-p95-seconds 2`可复现旧门槛；重判应另存新文件，不覆盖原报告。该脚本只判读已有分阶段场景，明确不授予完整旅程或生产容量验收。使用独立稳定性报告前须确认同一应用源码指纹；资源、公网和真机边界仍须人工核对。

## 独立出口带宽验证

`deploy/shape-test-egress.py show|limit|clear [--mbps 10|20|50]` 只针对 `club-capacity-test_nginx_1` 的私有rootless网络命名空间，并检查项目/服务标签；拒绝宿主网络和已有流控。`limit` 在该容器的lo上把IPv4 TCP源端口8080的响应归入指定速率的TBF（默认10Mbps），其余流量不受限，当前rootless端口转发走容器lo，Nginx到API走eth0；先通过包头与实际计数器确认，不能仅看规则存在就声称限速成功。使用 `podman unshare`，不用宿主root网卡流控。

先保存 `show`，再 `limit --mbps 10` 并核实rate=1250000 bytes/s以及实际响应字节/包计数非零；执行1500人短时三轮验证，最后在 `finally` 中保存qdisc计数并 `clear`。验证已恢复noqueue，保留前后证据；不得与原10分钟无带宽限制观察混跑。此测试只模拟出口速率，不模拟公网RTT、丢包或TLS开销。

语义依据iproute2项目手册：[PRIO分类](https://man7.org/linux/man-pages/man8/tc-prio.8.html)、[TBF限速](https://man7.org/linux/man-pages/man8/tc-tbf.8.html)、[u32端口匹配](https://man7.org/linux/man-pages/man8/tc-u32.8.html)。

## 完整学生流程、TLS与资源阶梯（2026-09-28）

旧 `load_remote.py` 为分阶段测试；当前完整流程使用 `scripts/run_journey_case.py`，详见 `docs/JOURNEY_CAPACITY.md`。支持 `--mode login|login_warm|ready|mixed|reconnect`、`--scenario uniform|hot_club|last_seat`、`--users 1500|3000`、`--rounds 3`，600秒活跃测试用 `--hold-seconds 600`。短测不能替代持续测试，登录全冷模式不能用提前登录模式替代。

TLS：`python3 deploy/prepare-test-tls.py --host TEST_PRIVATE_IP --algorithm ecdsa256`（RSA对照使用rsa2048）。私钥仅在忽略目录，公开测试证书复制到压测机后传 `--ca-cert`。加载compose.test.tls.yml，ECDSA目录通过 `TEST_TLS_DIR=../.local/tls-ecdsa` 选择，HTTPS端口18082。证书校验始终开启；这不代表微信真机认可自签测试证书。

实验资源可选择CPU时间额度4/6/8/12/16和出口10/20/50Mbps；wrapper自动保存配额与流控证据并在结束恢复4CPU/noqueue。TLS出口过滤端口为8443。密码并发与API进程必须另行通过compose设置并记录，不能仅修改CPU额度：4API进程主池15+3/读池4，总预算98；8API进程主池7+0/读池4，总预算仍98。PASSWORD_CONCURRENCY按试验取值，不能无限加线程。

当前测试模板Nginx为4进程；名额合并1.5秒，通知P95目标3秒。CPU额度不含rootless网络辅助进程，不等价物理核或云机vCPU。TLS已实测，公网RTT/丢包未模拟。完整配置是否达标以连续结果为准，不因模板存在即承诺容量。
