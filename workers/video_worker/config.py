from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str
    rabbitmq_url: str = "amqp://content_factory:change_me_rabbitmq@rabbitmq:5672/"
    storage_dir: str = "/app/storage"
    edge_tts_voice: str = "en-US-JennyNeural"
    openai_api_key: str = ""
    openai_tts_model: str = "tts-1-hd"
    openai_tts_voice: str = "nova"
    openai_image_model: str = "gpt-image-1"
    edge_tts_voice: str = "en-US-JennyNeural"
    app_public_url: str = "http://2.28.0.8"
    notify_email_to: str = ""
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_from: str = ""
    smtp_use_tls: bool = True


settings = Settings()


def storage_root() -> Path:
    path = Path(settings.storage_dir)
    path.mkdir(parents=True, exist_ok=True)
    return path


def video_dir(video_id: int) -> Path:
    path = storage_root() / "videos" / str(video_id)
    path.mkdir(parents=True, exist_ok=True)
    return path
