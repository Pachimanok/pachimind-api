from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    vault_path: str
    api_keys: dict[str, str] = {}  # {"key_value": "scope"}
    log_level: str = "INFO"
    cors_origins: list[str] = ["*"]
    node_url: str = "http://127.0.0.1:3000"
    pm_api_key: str = ""  # Shared internal Node credential (PM_API_KEY)
    notebooklm_bin: str = "notebooklm"

    # Áreas válidas del vault — extensible
    areas: list[str] = [
        "Personal",
        "Laboral",
        "Familia",
        "Amigos",
        "Apostolado",
    ]

    model_config = SettingsConfigDict(env_file=".env", env_nested_delimiter="__")


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
