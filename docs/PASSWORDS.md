# 密码校验与同步登录容量

新建账号和修改密码使用Argon2id：`m=7168 KiB, t=5, p=1`，每次独立随机盐。参数依据 [OWASP Password Storage Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html#argon2id) 列出的CPU/内存取舍配置。先测19MiB/2轮，再对比全部低内存推荐组合；当前测试CPU上7MiB/5轮吞吐更好，两者都在OWASP列出的同等级防御配置内。已有19MiB/2轮或更高配置仍可校验，不自动降参重写。旧bcrypt仍按其原成本校验，成功后在数据库事务外生成Argon2id，再锁行复核旧hash/账号状态后更新；失败登录不迁移，不保存明文。不能将旧hash直接转换为新hash，也不将“已提前迁移”的新账号测试当成旧账号首次登录测试。

每API进程默认最多1个原生密码任务（`PASSWORD_CONCURRENCY`允许1–8）。客户端取消不会提前释放仍在执行的原生线程名额；不通过降低bcrypt成本、跳过密码校验或缓存跨账号验证结果提高压测数字。密码任务等待和执行时间分别记录Prometheus聚合指标，不含用户名、密码或hash。

本届新导入账号采用新算法；旧账号首次登录需要旧验证+新hash两次计算，单独列为迁移场景，不能承诺与新账号相同延迟。正式迁移前必须固定包含Argon2依赖的后端版本；不应回滚到只识别bcrypt的老版本。

`benchmark_passwords.py`只允许TEST环境，对固定合成密码测算单项CPU服务需求。基准不是HTTP容量验收，也不能把本机吞吐直接换算为不同CPU的云机核数。
