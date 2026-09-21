"""Environment configuration; credentials stay server-side and are never serialized."""

from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=PROJECT_ROOT / ".env", extra="ignore")

    nebius_api_key: SecretStr = SecretStr("")
    nebius_base_url: str = "https://api.tokenfactory.us-north1.nebius.com/v1/"
    nebius_model: str = Field(default="zai-org/GLM-5.3", min_length=1, max_length=200)
    nebius_vision_model: str = Field(default="zai-org/GLM-5.3-Flash", min_length=1, max_length=200)
    model_timeout_seconds: float = Field(default=180, ge=1, le=300)
    model_max_tokens: int = Field(default=10000, ge=512, le=32000)
    max_image_bytes: int = Field(default=10 * 1024 * 1024, ge=1024, le=20000000)
    input_price_per_million: float | None = Field(default=None, ge=0)
    output_price_per_million: float | None = Field(default=None, ge=0)
    vision_input_price_per_million: float | None = Field(default=None, ge=0)
    vision_output_price_per_million: float | None = Field(default=None, ge=0)

    @property
    def provider_ready(self) -> bool:
        return bool(self.nebius_api_key.get_secret_value().strip())
