# gunicorn.conf.py（生产环境所有配置都在这）
import multiprocessing
from app.core.config import settings

# ── 网络 ──────────────────────────────────────────
bind = settings.BASE_URL.replace("http://", "")  # 监听地址和端口
backlog = 2048

# ── Worker ────────────────────────────────────────
worker_class = "uvicorn.workers.UvicornWorker"
workers = multiprocessing.cpu_count() * 2 + 1

# ── 超时 ──────────────────────────────────────────
timeout = 120  # Worker 超过这么久没响应 → 被 kill 重启
keepalive = 5  # 复用连接等待时间
graceful_timeout = 30  # 平滑关闭最多等这么久

# ── 日志 ──────────────────────────────────────────
loglevel = "info"
accesslog = "/var/log/fastapi/access.log"
errorlog = "/var/log/fastapi/error.log"

# ── 稳定性 ────────────────────────────────────────
max_requests = 1000  # Worker 处理满1000个请求后自动重启
max_requests_jitter = 100  # 加随机抖动，避免所有Worker同时重启
preload_app = True  # 预加载，节省内存
