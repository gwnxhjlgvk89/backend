from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from models import Base
from app.core.config import settings

DATABASE_URL = settings.DATABASE_URL

# 创建数据库引擎

engine = create_engine(
    DATABASE_URL,
    pool_size=100,  # 核心连接数，从20提升到100
    max_overflow=200,  # 溢出连接数，从40提升到200（峰值最多300个连接）
    pool_timeout=30,  # 等待连接超时时间，从30s改为60s
    pool_recycle=300,  # 连接存活30分钟后自动回收，防止MySQL断开
    pool_pre_ping=True,  # 每次使用前检测连接是否存活
)

# 数据库会话
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# 把db返回给接口函数


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
