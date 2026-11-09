from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str = "sqlite:///./retail_meeting_check.db"
    api_tokens: str = "dev-token-change-me"
    callback_hmac_secret: str = ""
    model_version: str = "vision-0.1.0"

    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    # 双模型：OCR/通用 vs 全景数人（空则回退到 vision_model）
    vision_model: str = "gpt-4o"
    vision_ocr_model: str = ""
    vision_count_model: str = ""
    vision_timeout_sec: float = 120.0
    vision_max_retries: int = 2
    # 手册当期年份（无旧版负样本时用封面年份判定）
    handbook_current_year: int = 2026

    # 仓库根目录；空则取 cwd
    local_asset_root: str = ""
    # 样例照片根（相对 asset_root）：药师大讲堂 / 微型药师
    sample_photos_dirname: str = "零售照片ai审核"
    # file_url → 相对路径 JSON
    s3_local_map_path: str = "docs/fixtures/s3_local_map.json"
    # 真 S3：开启后本地 map 未命中时走 boto3 GetObject
    use_real_s3: bool = False
    aws_region: str = "cn-north-1"
    aws_access_key_id: str = ""
    aws_secret_access_key: str = ""
    # API 限流（每 token / IP 滑动窗口）
    rate_limit_per_minute: int = 60

    @property
    def token_set(self) -> set[str]:
        return {t.strip() for t in self.api_tokens.split(",") if t.strip()}

    @property
    def asset_root(self) -> Path:
        if self.local_asset_root:
            return Path(self.local_asset_root).expanduser().resolve()
        return Path.cwd().resolve()

    @property
    def sample_photos_root(self) -> Path:
        return self.asset_root / self.sample_photos_dirname

    @property
    def hall_samples_dir(self) -> Path:
        return self.sample_photos_root / "药师大讲堂"

    @property
    def micro_samples_dir(self) -> Path:
        return self.sample_photos_root / "微型药师"


@lru_cache
def get_settings() -> Settings:
    return Settings()
