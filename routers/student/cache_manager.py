from .redis_client import redis_client
from typing import List, Dict, Optional
import logging

logger = logging.getLogger(__name__)


class ClubListCache:
    """社团列表缓存管理"""

    CACHE_KEY = "clubs:all"  # Redis缓存键
    CACHE_TTL = 3600  # 1小时过期

    @staticmethod
    def get() -> Optional[List[Dict]]:
        """获取缓存的社团列表"""
        data = redis_client.get_json(ClubListCache.CACHE_KEY)
        if data:
            logger.info("✅ 从Redis获取社团列表缓存")
        return data

    @staticmethod
    def set(clubs_data: List[Dict]) -> bool:
        """设置社团列表缓存"""
        success = redis_client.set_json(
            ClubListCache.CACHE_KEY, clubs_data, ex=ClubListCache.CACHE_TTL
        )
        if success:
            logger.info(f"✅ Redis缓存了 {len(clubs_data)} 个社团列表")
        return success

    @staticmethod
    def invalidate() -> bool:
        """清空缓存"""
        success = redis_client.delete(ClubListCache.CACHE_KEY)
        if success:
            logger.info("✅ 已清空社团列表缓存")
        return success
