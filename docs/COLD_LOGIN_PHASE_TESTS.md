# 冷登录分阶段实测与 Surge/WireGuard 路径诊断

后续已改用同局域网有线 Linux 独立发压，实测及尚未解决的长尾超时见 [独立有线 Linux 发压复测](WIRED_LINUX_LOAD_TESTS.md)。本页保留此前 Mac/Surge 路径的历史证据。

业务版本保持547aab2，测试服务父配额8CPU/4GiB、禁Swap，4API与4Nginx进程。未改应用代码或生产。所有账号均为合成账号。TLS始终校验测试CA与192.168.100.130证书身份；超时10秒，目标突发窗口0.6秒。

## 核心结果

同一服务在测试机本机发起1500个新连接时：TLS全部成功、P95=0.001658秒；HTTPS健康检查全部成功、P95=0.003568秒；纯登录全部成功、P95=0.447717秒，实际客户端发起跨度0.599秒。该结果有力支持此前秒级连接等待来自外部路径，不能据此授予生产容量通过：发压与服务同机、没有公网带宽/RTT、只有单轮纯登录，不是独立机器的完整流程验收。

用户在测试期间提供Surge提示截图：“请求量极高，暂停来自PID的所有连接”。官方CLI进一步确认192.168.100.130命中家庭网段自动策略，最终使用Surge内置WireGuard。此前把该地址称作纯局域网不准确：私有IP并不代表当前Mac与测试机直接相连。

Mac经Surge/WireGuard即使无出口限速，1500次纯TLS仍有连接重置/超时；拆为15进程仍失败。显式HTTP CONNECT入口、SSH端口转发也未验证为可靠替代。这些失败属于实际测试路径的失败证据，不能解释成数据库/密码CPU不足，也不能称为已解决Surge限制。

## 完整分阶段结果

表中P95包含失败耗时；快速重置会使部分失败场景P95小于10秒，不能只看P95忽略成功数。0Mbps表示未施加测试TBF，不表示真实WireGuard链路无限带宽。TLS成功标准为握手完成，health/login成功标准为200且完整读取响应。

| 场景 | 成功/请求数 | P95秒 | 失败阶段/结果 |
|---|---:|---:|---|
| host3-unshaped-health-1500-0mbps | 1500/1500 | 0.003568 | 无 |
| host3-unshaped-login-1500-0mbps | 1500/1500 | 0.447717 | 无 |
| host3-unshaped-tls-1500-0mbps | 1500/1500 | 0.001658 | 无 |
| mac-explicit-proxy-health-1500-0mbps-r1 | 804/1500 | 10.000788 | {'TimeoutError': 629, 'ClientProxyConnectionError': 67} |
| mac-explicit-proxy-login-1500-0mbps-r1 | 151/1500 | 10.00126 | {'TimeoutError': 1349} |
| mac-explicit-proxy-login-1500-10mbps-r1 | 936/1500 | 10.001367 | {'TimeoutError': 564} |
| mac-explicit-proxy-login-1500-50mbps-r1 | 782/1500 | 10.001233 | {'TimeoutError': 718} |
| mac-ssh-unshaped-health-1500-0mbps | 0/0 | — | 准备失败，无有效测量 |
| mac-ssh-unshaped-login-1500-0mbps | 2/1500 | 10.000806 | {'TimeoutError': 1009, 'ConnectionResetError': 489} |
| mac-ssh-unshaped-tls-1500-0mbps | 442/1500 | 10.002562 | {'TimeoutError': 569, 'ConnectionResetError': 489} |
| mac-unshaped-health-1500-0mbps | 1175/1500 | 7.437527 | {'TimeoutError': 59, 'ConnectionResetError': 266} |
| mac-unshaped-tls-100-0mbps | 100/100 | 0.219657 | 无 |
| mac-unshaped-tls-1500-0mbps | 1467/1500 | 7.480794 | {'ConnectionResetError': 33} |
| mac-unshaped-tls-300-0mbps | 300/300 | 1.451857 | 无 |
| mac-unshaped-tls-750-0mbps | 750/750 | 2.747755 | 无 |
| mac15-recheck-tls-1500-0mbps | 869/1500 | 10.001976 | {'TimeoutError': 631} |
| mac15-shaped-login-1500-10mbps | 896/1500 | 10.001118 | {'TimeoutError': 604} |
| mac15-shaped-login-1500-50mbps | 1234/1500 | 10.001352 | {'TimeoutError': 266} |
| mac15-shaped-tls-1500-10mbps | 1227/1500 | 10.001628 | {'TimeoutError': 273} |
| mac15-shaped-tls-1500-50mbps | 1296/1500 | 10.001676 | {'TimeoutError': 204} |
| mac15-v2-unshaped-health-1500-0mbps | 1423/1500 | 10.000123 | {'TimeoutError': 77} |
| mac15-v2-unshaped-login-1500-0mbps | 792/1500 | 10.002074 | {'TimeoutError': 708} |
| mac15-v2-unshaped-tls-1500-0mbps | 1460/1500 | 7.583711 | {'TimeoutError': 40} |

## 阶段口径与监控

新驱动分别记录非阻塞TCP连接、完成TLS、写出HTTP请求、等待响应头和应用Server-Timing。未完成阶段不会伪造完成耗时；失败阶段与总耗时仍保留。每个请求新建TLS连接，测量期间只在内存采样，结束后落盘。三个无网络单元测试覆盖超时阶段、凭据响应不入报告、非TEST服务拒绝。

测试机每200ms记录测试cgroup、Nginx/API/worker进程与网络辅助进程的CPU、内存及TCP计数。多数未限速/50Mbps场景Nginx网络命名空间没有监听溢出、SYN重传或TCP超时增量；10Mbps部分场景出现TCPTimeouts增量，说明带宽排队/传输也有影响。不能把这个命名空间的零计数外推到WireGuard外部链路。

Mac显式代理对照另有Surge进程采样，观察到Surge进程最高约1.64核的采样区间CPU消耗。其他Surge组件受权限约束未取得完整进程样本，而且该进程承载整机流量，因此不是精确的测试专属CPU，也不能断言它已满核。

TCP连接时间在增强模式下可能只反映本机代理接管时间；随后TLS阶段同时包含网络等待及端点处理。SSH转发把多连接复用到少量SSH连接，新增了转发层和队首阻塞，结果差不能反推应用性能。未查明SSH重置的具体资源限制，不声称它一定是文件描述符问题。

## Surge设置与清理

本次曾备份并添加目标/32增强模式排除项与目标系统代理排除项，验证、重载后路由仍为utun8。用户补充WireGuard背景及只允许临时修改后，立即撤回；文件与修改前备份逐字节一致。Surge增强模式、系统代理和WireGuard日常策略保留。没有关闭全局保护、停止Surge、创建新WireGuard peer或保留永久排除项。

临时SSH转发仅绑定127.0.0.1:18083，已撤销；最终无监听。所有本次发压进程结束，出口TBF清除、qdisc恢复noqueue；测试机继续保留8CPU/4GiB。最终核对见final-state.json与final-resources.json。配置备份含私密配置，仅保留在用户Surge目录，不进入仓库。

## 中断与验收边界

- mac-unshaped-login组在用户提供Surge拦截截图时中断，保留局部记录，不能算完整回合。
- mac15-unshaped-tls第一组完成客户端记录，但Surge重载后SSH监控会话失效，无完整资源证据；另以v2标签重跑。
- SSH health准备失败，无有效测量；SSH50Mbps组在转发失败后中断，保留局部记录并清理限速。
- 本轮重点是TLS/健康检查/纯登录隔离，未在失败的外部路径继续重复完整业务压测。完整流程对照沿用同业务版本的EIGHT_CPU_NAME_PASSWORD.md历史记录；未声称这轮重新通过完整流程。
- 新增测试脚本与证据，前端和后端业务逻辑均未修改；没有新真机或生产验证。

## 后续方案

独立Linux发压机放在测试服务器可直达的同一局域网或同一VPC，通过原生网络访问测试服务。它与应用服务器分开，避免同时占用被测CPU/内存；Mac只通过SSH下发任务，1500条业务连接从Linux本地发出，不穿过Mac/Surge/WireGuard。若Linux仍通过相同Surge或受限VPN路径发压，仅换操作系统不能解决问题。

先做纯TLS、纯登录与完整流程；同时检查发压机CPU、文件描述符、端口、重传和实际发起跨度。容量测试稳定后，再单独加入10Mbps与公网RTT/丢包条件。与生产单核、磁盘及网络不同的测试CPU配额仍不能直接换算线上实例规格。参考[Grafana发压资源监控建议](https://grafana.com/docs/k6/latest/testing-guides/running-large-tests/)。

## 复现与证据

scripts/load_connection_phases.py使用stdlib对固定TEST目标分阶段测量；scripts/load_explicit_proxy.py只使用已有127.0.0.1:6152入口。每个分片使用不同offset、相同未来epoch启动，例如每片500人、offset=0/500/1000；CA由已核验的测试证书提供。运行前必须确认无其他压测，保持8CPU/4GiB并记录流控。deploy/monitor-test-connections.py提供只读采样。--ssh-tunnel仅用于已建立的固定回环转发，TLS身份不改。

原始驱动初版及编排脚本的精确文本保存在证据目录用于哈希复现；后续仅加入临时SSH诊断选择并格式化。每个分片记录实际driver_sha256。structured summary保留各阶段分位数、成功数、失败阶段、CPU/TCP变化，部分组的失败统计不代表应用拒绝。
