# v1 接口与错误约定

所有业务端点以 `/api/v1` 开头。成功 `{"data": ...}`；失败 `{"error":{"code":"稳定错误码","message":"提示","request_id":"..."}}`，同时返回 `X-Request-ID` 和 `Server-Timing`。

| 模块 | 接口 |
|---|---|
| 登录会话 | `POST /auth/login`、`POST /auth/password`、`POST /auth/logout`、`POST /auth/ws-ticket` |
| 首屏 | `GET /bootstrap`（用户、活动、服务端UTC时间、报名、收藏、静态摘要及名额） |
| 社团 | `GET /clubs/{id}`、`GET /clubs/quotas` |
| 报名 | `GET /enrollment`、`POST /enrollment`、`DELETE /enrollment` |
| 收藏/资料 | `PUT/DELETE /favorites/{id}`、`PUT /profile`、`POST /profile/avatar` |
| 管理 | `/admin/students` 默认30/最多100分页；`/admin/clubs`；`/admin/overview` |
| 超管 | `PUT /admin/activity`、`POST /admin/activity/state`、`GET/POST /admin/administrators`、`PUT /admin/administrators/{id}` |
| 后台任务 | `POST /admin/jobs/import`、`POST /admin/jobs/{id}/confirm`、`POST /admin/jobs/export`、`GET /admin/jobs`、`GET /admin/jobs/{id}`、`GET /admin/jobs/{id}/download` |

写报名/退选必须传 `Idempotency-Key`（8–64位ASCII）。同学生同键同请求重放相同已提交结果；改请求内容返回409。同一逻辑请求在网络不确定期间复用键，明确结束后下次操作用新键。

401未登录/会话失效；403身份或资格不符；409已报名/满额/活动状态冲突；422输入格式；429账号级频率限制；503依赖故障或结果不确定；旧业务入口426要求更新。严禁把429/503算作正常容量处理成功。

WebSocket `/api/v1/ws?ticket=...` 使用登录后申请的30秒一次性票据，不把长期Token放URL。`quota` 为单社团事件；`quotas` 为合并批次，其 `items` 中每个社团含 `club_id,remaining,version`；批次带 `event_id,enqueued_at,published_at`（批次最早入队时间用于保守测量）。客户端忽略较小版本；`activity/catalog/enrollment/resync` 提示获取权威状态。`ping/pong` 心跳，账号撤销会关闭连接；断线重新申请票据并同步快照。

服务端 OpenAPI 为最新字段依据：`/api/v1/openapi.json`，交互文档 `/api/v1/docs`。公开响应使用字段白名单和显式模型；不输出密码哈希和会话版本。
