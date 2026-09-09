"""Configuration. Every secret comes from the environment — nothing is hardcoded."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # --- Database ---
    postgres_user: str = "llb"
    postgres_password: str = "llb_local_dev"
    postgres_db: str = "llbsutra"
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    database_url: str | None = None

    # --- Anthropic (Phase 3+) ---
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-opus-5"

    # --- Ingestion ---
    # Government portals (India Code in particular) return HTTP 403 to default HTTP
    # clients. A real browser UA is required, and the crawl must stay polite.
    fetch_user_agent: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
    )
    fetch_rate_limit_seconds: float = 1.0
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    embedding_dim: int = 384

    # Windows installers put tesseract.exe outside PATH; Linux/Docker have it on PATH.
    # Question papers are scans, so OCR is not optional for the PYQ corpus.
    tesseract_cmd: str = ""

    # --- Deployment ---
    # Loading the embedding model costs a few hundred MB of RSS. That is fine locally
    # and fine on a paid instance, but a 512MB free tier can OOM on it. Turning this
    # off keeps the site fully usable on keyword search alone - which for statutes is
    # a smaller loss than it sounds, since section numbers and case names are lexical.
    enable_vector_search: bool = True

    # Free hosts inject the port to bind. Read by the container entrypoint, not by app
    # code, but kept here so the setting is discoverable in one place.
    port: int = 8000

    @property
    def dsn(self) -> str:
        if self.database_url:
            return self.database_url
        return (
            f"postgresql://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
