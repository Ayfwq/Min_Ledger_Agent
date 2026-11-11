from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration, loaded from environment / .env."""

    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_name: str = "Mini Ledger Agent"
    environment: str = "dev"
    debug: bool = False
    api_prefix: str = "/api/v1"

    database_url: str = "postgresql+asyncpg://ledger:ledger@127.0.0.1:5432/ledger"

    # SiliconFlow (OpenAI compatible)
    siliconflow_api_key: str = ""
    siliconflow_base_url: str = "https://api.siliconflow.cn/v1"
    llm_text_model: str = "deepseek-ai/DeepSeek-V3.2"
    llm_vision_model: str = "Qwen/Qwen3-VL-32B-Instruct"
    llm_timeout_seconds: float = 90.0
    llm_max_retries: int = 2
    # Optional explicit proxy for the LLM call (e.g. http://127.0.0.1:7890).
    # Empty means a direct connection; ambient HTTP(S)_PROXY is ignored.
    llm_proxy: str = ""

    upload_dir: str = "data/uploads"
    max_upload_mb: int = 10

    # Optional single shared password. Empty = disabled.
    app_password: str = ""
    allowed_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    worker_enabled: bool = True
    worker_poll_interval: float = 1.0
    worker_max_attempts: int = 5
    timezone: str = "Asia/Shanghai"

    @property
    def upload_path(self) -> Path:
        path = Path(self.upload_dir)
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.allowed_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
