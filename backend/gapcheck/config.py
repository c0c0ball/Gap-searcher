from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql://gapcheck:gapcheck@localhost:5432/gapcheck"
    redis_url: str = "redis://localhost:6379/0"

    minio_endpoint: str = "localhost:9000"
    minio_root_user: str = "gapcheck"
    minio_root_password: str = "gapcheck"
    minio_buckets: str = "quarantine,raw,derived,reports"

    clamav_host: str = "localhost"
    clamav_port: int = 3310

    ollama_url: str = "http://localhost:11434"
    ollama_gen_model: str = "qwen3:8b"
    ollama_embed_model: str = "bge-m3"

    @property
    def bucket_list(self) -> list[str]:
        return [b.strip() for b in self.minio_buckets.split(",") if b.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
