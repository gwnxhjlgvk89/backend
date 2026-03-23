---
title: 社团填报助手后端说明
output: pdf_document
---

# 说明

2xx — 成功
状态码 含义 常见场景
200 OK 请求成功 GET 查询成功、POST 操作成功
201 Created 创建成功 注册用户、新建资源
204 No Content 成功但无返回内容 DELETE 删除成功
3xx — 重定向
状态码 含义 常见场景
301 Moved Permanently 永久重定向 域名迁移
302 Found 临时重定向 登录后跳转
304 Not Modified 内容未变化 ETag 命中缓存 ← 你用过的！
4xx — 客户端错误（用户/前端的锅）
状态码 含义 常见场景
400 Bad Request 请求格式/参数错误 字段缺失、类型错误
401 Unauthorized 未认证 没带 Token、Token 过期
403 Forbidden 无权限 Token 合法但权限不足
404 Not Found 资源不存在 查询不存在的社团
405 Method Not Allowed 请求方法不对 用 GET 请求了 POST 接口
409 Conflict 资源冲突 重复选社、用户名已存在
422 Unprocessable Entity 参数校验失败 FastAPI 最常见，Pydantic 校验不通过
429 Too Many Requests 请求太频繁 触发限流

# admin需要的接口

> 首先我定义: 在抢社团的过程中,需要严格禁止管理员对数据库进行操作

1. 上传文件初始化数据库
2. 查看所有数据
3. 修改所有数据
4. 导出选课数据

# 关于前端的数据刷新逻辑

1. 首页数据: onLoad初始化, onShow开始轮询(几秒请求一次), onHide(跳转页面停止轮询), 然后对于剩余人数的特定数据, 采用websocket实时连接修改
2. 管理员数据: 同理,
