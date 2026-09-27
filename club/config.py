from functools import lru_cache
from pathlib import Path
from urllib.parse import urlsplit

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", hide_input_in_errors=True)
    club_env: str = "development"
    database_url: str
    redis_url: str
    jwt_secret: str
    token_minutes: int = 120
    pool_size: int = 10
    pool_overflow: int = 5
    password_concurrency: int = 2
    storage_backend: str = "local"
    storage_dir: Path = Path(".local/uploads")
    public_url: str = "http://127.0.0.1:8001"
    r2_endpoint: str = ""
    r2_access_key: str = ""
    r2_secret_key: str = ""
    r2_bucket: str = ""
    r2_public_url: str = ""
    redis_prefix: str = "club:v2"

    @model_validator(mode="after")
    def validate_environment(self):
        if not 1 <= self.password_concurrency <= 8:
            raise ValueError("PASSWORD_CONCURRENCY must be between 1 and 8 per API process")
        if self.club_env not in {"development", "test", "production"}:
            raise ValueError("Invalid CLUB_ENV")
        if not self.database_url.startswith("mysql+asyncmy://"):
            raise ValueError("DATABASE_URL must use mysql+asyncmy")
        if len(self.jwt_secret) < 32:
            raise ValueError("JWT_SECRET must contain at least 32 characters")
        if self.club_env != "production":
            for value in (self.database_url, self.redis_url):
                if urlsplit(value).hostname not in {"localhost", "127.0.0.1", "::1", "mysql", "redis"}:
                    raise ValueError("Development/test resources must be local")
            if self.storage_backend != "local":
                raise ValueError("Development/test must use local file storage")
        else:
            if any(
                v in self.jwt_secret for v in ("local-development", "REPLACE", "synthetic")
            ) or not self.public_url.startswith("https://"):
                raise ValueError("Production requires an independent secret and HTTPS")
        if self.storage_backend not in {"local", "r2"}:
            raise ValueError("Unsupported storage backend")
        if self.storage_backend == "r2" and not all(
            (self.r2_endpoint, self.r2_access_key, self.r2_secret_key, self.r2_bucket, self.r2_public_url)
        ):
            raise ValueError("R2 configuration incomplete")
        return self


@lru_cache
def settings():
    return Settings()
