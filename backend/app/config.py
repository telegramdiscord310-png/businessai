"""Configuration lue depuis l'environnement (.env). Aucun secret n'est codé en dur."""
from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Config(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://businessai:businessai@db:5432/businessai"
    # Clé Fernet (44 caractères) : chiffre la session Telegram, les clés API et le token du bot.
    fernet_key: str = ""
    # Secret partagé entre le backend et le worker Telegram (réseau interne Docker).
    internal_token: str = ""
    # Code demandé par la page d'installation pour créer le compte administrateur.
    setup_token: str = ""
    # Adresse publique du site, ex. https://app.mondomaine.fr (sert au CORS et au contrôle d'origine).
    app_origin: str = "http://localhost:5173"
    cookie_secure: bool = True
    session_days: int = 14
    worker_url: str = "http://worker:8100"
    worker_port: int = 8100
    data_dir: str = "/data"
    timezone: str = "Europe/Paris"
    max_upload_mb: int = 500
    media_max_mb: int = 20
    log_retention_days: int = 30

    @field_validator("app_origin")
    @classmethod
    def _strip_slash(cls, v: str) -> str:
        return v.rstrip("/")

    @field_validator("database_url")
    @classmethod
    def _async_driver(cls, v: str) -> str:
        if v.startswith("postgres://"):
            v = "postgresql://" + v[len("postgres://"):]
        if v.startswith("postgresql://"):
            v = "postgresql+asyncpg://" + v[len("postgresql://"):]
        return v


@lru_cache
def get_config() -> Config:
    return Config()
