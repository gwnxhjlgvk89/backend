import redis
from typing import Any, Optional
import json
import logging

logger = logging.getLogger(__name__)


class RedisClient:
    """Redis客户端单例"""

    _instance = None
    _pool = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(RedisClient, cls).__new__(cls)
        return cls._instance

    def __init__(
        self,
        host: str = "localhost",
        port: int = 6379,
        db: int = 0,
        # password: str = "your_redis_password",
        decode_responses: bool = True,
    ):
        if self._pool is None:
            self._pool = redis.ConnectionPool(
                host=host,
                port=port,
                db=db,
                # password=password,
                decode_responses=decode_responses,
            )
        self.client = redis.Redis(connection_pool=self._pool)
        self._test_connection()

    def _test_connection(self):
        """测试连接"""
        try:
            self.client.ping()
            logger.info("✅ Redis连接成功")
        except Exception as e:
            logger.error(f"❌ Redis连接失败: {e}")
            raise

    def get_json(self, key: str) -> Optional[Any]:
        """获取JSON值"""
        try:
            value = self.client.get(key)
            return json.loads(value) if value else None
        except Exception as e:
            logger.error(f"❌ 获取Redis值失败: {e}")
            return None

    def set_json(self, key: str, value: Any, ex: int = 3600) -> bool:
        """设置JSON值"""
        try:
            self.client.set(key, json.dumps(value, ensure_ascii=False), ex=ex)
            return True
        except Exception as e:
            logger.error(f"❌ 设置Redis值失败: {e}")
            return False

    def delete(self, key: str) -> bool:
        """删除键"""
        try:
            self.client.delete(key)
            return True
        except Exception as e:
            logger.error(f"❌ 删除Redis值失败: {e}")
            return False

    def close(self):
        """关闭连接"""
        if self._pool:
            self._pool.disconnect()
            logger.info("✅ Redis连接已关闭")


redis_client = RedisClient()
