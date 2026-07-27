from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "development"
    database_url: str
    redis_url: str = "redis://redis:6379/0"
    rabbitmq_url: str = "amqp://content_factory:change_me_rabbitmq@rabbitmq:5672/"
    openai_api_key: str = ""
    openai_model: str = "gpt-5-mini"


settings = Settings()
