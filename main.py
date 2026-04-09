from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from routers import auth, ws
from routers.admin import router as admin_router
from routers.student import router as student_router
from app.api import upload
import asyncio
import logging
from contextlib import asynccontextmanager

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 全局变量，存储后台任务
background_tasks = []

# ─────────────────────────────────────────
# 定时更新 Club 缓存的后台任务
# ─────────────────────────────────────────
async def club_cache_updater():
    """每隔20秒更新一次 Club 缓存"""
    from crud import get_clubs_with_major_restrictions
    from app.cache import ClubListCache
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    
    DATABASE_URL = "mysql+pymysql://root:GG1214@localhost:3306/club_selection?charset=utf8mb4"
    engine = create_engine(DATABASE_URL)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    
    while True:
        try:
            await asyncio.sleep(20)  # 每隔20秒
            
            db = SessionLocal()
            logger.info("🔄 开始更新 Club 缓存...")
            
            # 查询最新数据
            clubs_data = get_clubs_with_major_restrictions(db)
            
            # 更新缓存
            ClubListCache.set(clubs_data)
            
            logger.info(f"✅ Club 缓存更新成功，共 {len(clubs_data)} 个社团")
            db.close()
            
        except Exception as e:
            logger.error(f"❌ Club 缓存更新失败: {e}")

# ─────────────────────────────────────────
# 生命周期管理
# ─────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动
    logger.info("🚀 启动应用...")
    
    # 创建后台任务
    task = asyncio.create_task(club_cache_updater())
    background_tasks.append(task)
    
    logger.info("⏰ 定时器已启动，每20秒更新一次Club缓存")
    
    yield
    
    # 关闭
    logger.info("🛑 关闭应用...")
    for task in background_tasks:
        task.cancel()
    logger.info("✅ 定时器已关闭")

# ─────────────────────────────────────────
# 创建 FastAPI 应用实例
# title/description/version 会显示在 /docs 页面
# ─────────────────────────────────────────
app = FastAPI(
    title="社团抢课系统",
    description="先到先得，抢完即止",
    docs_url="/docs",  # Swagger UI
    version="1.0.0",
    lifespan=lifespan,  # 注册生命周期管理
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
        host="127.0.0.1",
        port=8000,
        reload=True,
        timeout_keep_alive=5,
    )