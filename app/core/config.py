from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    """应用配置,从环境变量读取"""

    BASE_URL: str = "http://localhost:8000"  # 后端基础URL，生产环境请修改为实际URL
    DATABASE_URL: str = (
        "mysql+pymysql://root@localhost:3306/club_selection?charset=utf8mb4"
    )
    SERCRET_KEY: str = "gg1214"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 2  # 7天
    # R2 相关配置
    R2_ACCOUNT_ID: str = "9761696ded6114c8147d10b17e8f0073"
    R2_ACCESS_KEY_ID: str = "185421056c784a2849f4b5e871426a5f"
    R2_SECRET_ACCESS_KEY: str = (
        "1bbff1ff10158e5d8db4733d6a7b7e4b34755a58b891bfc1f497b158c3ad8f43"
    )
    R2_BUCKET_NAME: str = "club-registration-assistant"
    R2_PUBLIC_URL: str = "https://pub-3471c1f12517459ca5eb6285d7a01452.r2.dev"

    class Config:
        env_file = ".env"
        case_sensitive = True


settings = Settings()
