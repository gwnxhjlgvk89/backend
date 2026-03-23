from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from routers import auth, ws
from routers.admin import router as admin_router
from routers.student import router as student_router
from app.api import upload


# ─────────────────────────────────────────
# 创建 FastAPI 应用实例
# title/description/version 会显示在 /docs 页面
# ─────────────────────────────────────────
app = FastAPI(
    title="社团抢课系统",
    description="先到先得，抢完即止",
    version="1.0.0",
)
# ─────────────────────────────────────────
# 跨域中间件（CORS）
# 允许前端（不同端口/域名）访问后端接口
# 开发阶段 allow_origins=["*"] 全部放行
# 上线后改为具体的前端域名
# ─────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
# ─────────────────────────────────────────
# 注册路由
# include_router 把子模块的接口挂载到主应用
# ─────────────────────────────────────────
app.include_router(auth.router)
app.include_router(ws.router)
app.include_router(upload.router)
app.include_router(student_router)
app.include_router(admin_router)

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        timeout_keep_alive=5,
    )
