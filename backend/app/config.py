from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "development"
    database_url: str
    redis_url: str = "redis://redis:6379/0"
    rabbitmq_url: str = "amqp://content_factory:change_me_rabbitmq@rabbitmq:5672/"
    cursor_api_key: str = ""
    cursor_model: str = "composer-2.5"
    openai_api_key: str = ""
    storage_dir: str = "/app/storage"
    edge_tts_voice: str = "en-US-JennyNeural"


settings = Settings()


def storage_root() -> Path:
    path = Path(settings.storage_dir)
    path.mkdir(parents=True, exist_ok=True)
    return path


def video_dir(video_id: int) -> Path:
    path = storage_root() / "videos" / str(video_id)
    path.mkdir(parents=True, exist_ok=True)
    return path
