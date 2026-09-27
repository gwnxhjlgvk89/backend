# 隔离测试部署与生产模板

所有容量与故障脚本仅用于 `CLUB_ENV=test`、`club_test` 数据库、`club:test` Redis前缀和纯 `load*` 合成账号；不执行生产报名压测。

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

数据库与Redis不发布主机端口，HTTP只绑定明确测试网卡；服务共用4CPU/3000MiB预算，MySQL1400MiB、API900MiB、worker192MiB、Redis192MiB、Nginx256MiB。4个API进程，每进程写入等主池15+5连接、身份/结果查询预留池2连接；独立worker固定5+5，连接预算98/150=65.3%。查询预留池不用于报名写入，避免超容量时写请求耗尽全部查询连接。

资源报告包括每容器RSS、内存峰值、OOM计数和CPU累计时间；压测机记录整机与压测进程CPU、RSS和事件循环延迟。Podman `cpu_percent`是容器运行以来平均值，不能当作瞬时CPU峰值。此次测试主机的单核性能/NVMe与生产云机不同，带宽复现仅为测试Nginx出口限速、未复现公网RTT/TLS/丢包，不能宣称完全同硬件验收。

停止测试：从本目录使用相同compose参数执行 `stop`。保留命名卷供复核，默认不执行 `down -v`。

## 生产

`club-api.service`、`club-worker.service`、`nginx.routes.conf`、`production.env.example`为待审核模板。先参考 `docs/OPERATIONS.md`，核实生产MySQL连接预算、HTTPS站点、维护与备份；不直接覆盖运行中的配置。本开发任务没有执行生产部署、数据清理、提审或发布。

超容量保护：Nginx只对报名POST/DELETE设置全局1500个进行中请求的上限，超过时返回带请求ID的JSON 429；GET结果查询使用空限流键，不计入写入限额。此限额不按IP计算，避免误伤校园共享出口。正常1500人验收仍必须无容量429。依据 [Nginx limit_conn 官方语义](https://nginx.org/en/docs/http/ngx_http_limit_conn_module.html)，空key不参与计数。测试Nginx连接上限设为16384，覆盖3000WS及代理连接。

3000人超容量测试先在120秒内登录准备令牌，再执行1秒报名突发；这不是3000人60秒登录达标的声明。压测HTTP连接池也按用户数扩展，避免3000条WS占据固定连接池后在压测机侧悄悄排队。超容量场景每轮另发20次结果查询，直接检查查询可用性。

通知延迟的精确核对使用合成测试库的 `(club_id,version)` 对应出站事件时间与客户端收到时间匹配；批次最早入队时间作为保守上界单列，不能混同为每条名额变更的实际延迟。该核对CLI只读取测试库，不增加生产消息里的学生资料或冗余时间字段。

`python scripts/check_capacity.py reports/linux-capacity-confirmation.json --stability reports/linux-capacity-final.json` 可只读汇总门槛，失败时退出码1。使用独立稳定性报告前须确认同一应用源码指纹；资源、公网和真机边界仍须人工核对。

## 独立出口带宽验证

`deploy/shape-test-egress.py show|limit|clear [--mbps 10|20|50]` 只针对 `club-capacity-test_nginx_1` 的私有rootless网络命名空间，并检查项目/服务标签；拒绝宿主网络和已有流控。`limit` 在该容器的lo上把IPv4 TCP源端口8080的响应归入指定速率的TBF（默认10Mbps），其余流量不受限，当前rootless端口转发走容器lo，Nginx到API走eth0；先通过包头与实际计数器确认，不能仅看规则存在就声称限速成功。使用 `podman unshare`，不用宿主root网卡流控。

先保存 `show`，再 `limit --mbps 10` 并核实rate=1250000 bytes/s以及实际响应字节/包计数非零；执行1500人短时三轮验证，最后在 `finally` 中保存qdisc计数并 `clear`。验证已恢复noqueue，保留前后证据；不得与原10分钟无带宽限制观察混跑。此测试只模拟出口速率，不模拟公网RTT、丢包或TLS开销。

语义依据iproute2项目手册：[PRIO分类](https://man7.org/linux/man-pages/man8/tc-prio.8.html)、[TBF限速](https://man7.org/linux/man-pages/man8/tc-tbf.8.html)、[u32端口匹配](https://man7.org/linux/man-pages/man8/tc-u32.8.html)。
