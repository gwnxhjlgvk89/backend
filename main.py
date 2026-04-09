from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from routers import auth, ws
from routers.admin import router as admin_router
from routers.student import router as student_router
from app.api import upload
import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import datetime

# ─────────────────────────────────────────
# 日志配置（详细输出）
# ─────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
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
    
    try:
        engine = create_engine(DATABASE_URL, pool_pre_ping=True)
        SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
        logger.info("✅ 数据库连接池初始化成功")
    except Exception as e:
        logger.error(f"❌ 数据库连接失败: {e}")
        return
    
    # ⭐ 首次启动立即执行一次
    logger.info("🚀 首次启动，立即执行一次缓存更新...")
    try:
        db = SessionLocal()
        clubs_data = get_clubs_with_major_restrictions(db)
        ClubListCache.set(clubs_data)
        logger.info(f"✅ 首次缓存更新成功，共 {len(clubs_data)} 个社团")
        db.close()
    except Exception as e:
        logger.error(f"❌ 首次缓存更新失败: {e}", exc_info=True)
    
    # 定期更新
    counter = 0
    while True:
        try:
            await asyncio.sleep(20)  # 每隔20秒
            counter += 1
            
            current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            logger.info(f"[{current_time}] 🔄 开始第 {counter} 次定时更新Club缓存...")
            
            db = SessionLocal()
            
            # 查询最新数据
            clubs_data = get_clubs_with_major_restrictions(db)
            
            # 更新缓存
            ClubListCache.set(clubs_data)
            
            logger.info(f"[{current_time}] ✅ 第 {counter} 次缓存更新成功，共 {len(clubs_data)} 个社团")
            db.close()
            
        except asyncio.CancelledError:
            logger.info("🛑 定时器任务已取消")
            break
        except Exception as e:
            logger.error(f"❌ 第 {counter} 次缓存更新失败: {e}", exc_info=True)
            # 继续下一次，不中断

# ─────────────────────────────────────────
# 生命周期管理
# ─────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动
    logger.info("=" * 50)
    logger.info("🚀 启动应用...")
    logger.info("=" * 50)
    
    # 创建后台任务
    logger.info("📍 创建定时器任务...")
    task = asyncio.create_task(club_cache_updater())
    background_tasks.append(task)
    logger.info("✅ 定时器任务创建成功")
    logger.info("⏰ 定时器已启动，每20秒更新一次Club缓存")
    
    yield
    
    # 关闭
    logger.info("=" * 50)
    logger.info("🛑 关闭应用...")
    logger.info("=" * 50)
    
    for task in background_tasks:
        logger.info("📍 取消定时器任务...")
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            logger.info("✅ 定时器任务已取消")

# ─────────────────────────────────────────
# 创建 FastAPI 应用实例
# ─────────────────────────────────────────
app = FastAPI(
    title="社团抢课系统",
    description="先到先得，抢完即止",
    docs_url="/docs",
    version="1.0.0",
    lifespan=lifespan,
)

# ─────────────────────────────────────────
# 跨域中间件
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
# ─────────────────────────────────────────
app.include_router(auth.router)
app.include_router(ws.router)
app.include_router(upload.router)
app.include_router(student_router)
app.include_router(admin_router)

# ─────────────────────────────────────────
# 健康检查 + 定时器状态接口
# ─────────────────────────────────────────
@app.get("/health", summary="健康检查")
def health_check():
    """检查应用和定时器状态"""
    return {
        "status": "✅ OK",
        "timestamp": datetime.now().isoformat(),
        "background_tasks_count": len(background_tasks),
        "tasks_running": [not task.done() for task in background_tasks],
    }

@app.get("/admin/scheduler/status", summary="查看定时器详细状态")
def get_scheduler_status():
    """查看定时器运行状态"""
    logger.info("📊 查询定时器状态...")
    
    return {
        "status": "✅ 运行中" if background_tasks and not background_tasks[0].done() else "❌ 已停止",
        "tasks_total": len(background_tasks),
        "tasks_running": len([t for t in background_tasks if not t.done()]),
        "tasks_done": len([t for t in background_tasks if t.done()]),
        "update_interval": "20秒",
        "timestamp": datetime.now().isoformat(),
    }

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host="127.0.0.1",
        port=8000,
        reload=False,  # ⚠️ 必须是 False
        timeout_keep_alive=5,
    )