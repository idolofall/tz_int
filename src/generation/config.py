from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://app:app@localhost:5432/generation"
    webhook_secret: str = "dev-webhook-secret"
    provider_timeout_seconds: int = 60
    provider_dispatch_timeout_seconds: float = 3.0
    watchdog_interval_seconds: float = 2.0
    app_public_url: str = "http://app:8000"
    alpha_url: str = "http://provider-alpha:8000"
    beta_url: str = "http://provider-beta:8000"
    log_level: str = "INFO"
    max_active_tasks: int = 3

    def provider_base_url(self, name: str) -> str:
        if name == "alpha":
            return self.alpha_url.rstrip("/")
        if name == "beta":
            return self.beta_url.rstrip("/")
        raise ValueError(f"unknown provider: {name}")


settings = Settings()
