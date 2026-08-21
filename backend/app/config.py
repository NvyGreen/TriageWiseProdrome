from functools import lru_cache
from urllib.parse import quote_plus
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


APP_DIR = Path(__file__).resolve().parent
BACKEND_ROOT = APP_DIR.parent


class Settings(BaseSettings):
    app_name: str = "TriageWiseProdrome"
    SECRET_KEY: str
    DB_USER: str
    DB_PASSWORD: str
    DB_HOST: str
    DB_PORT: int
    DB_NAME: str
    debug: bool = False
    # Comma-separated allowed origins for CORS. Default is the local Vite dev
    # server; set CORS_ALLOW_ORIGINS in the environment to the real frontend
    # origin(s) per deploy. Never "*" — allow_credentials forbids it anyway.
    CORS_ALLOW_ORIGINS: str = "http://localhost:5173"
    # Epic on FHIR "Non-Production Client ID". Consumed directly by
    # scripts/epic_fhir_pull.py via os.environ; declared here only so pydantic
    # accepts it in .env (Settings forbids undeclared env vars). Optional so
    # environments without FHIR configured (CI, tests) still build.
    FHIR_CLIENT_ID: str = ""

    @property
    def DATABASE_URL(self) -> str:
        safe_password = quote_plus(self.DB_PASSWORD)
        return f"postgresql+psycopg2://{self.DB_USER}:{safe_password}@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"

    @property
    def cors_allow_origins(self) -> list[str]:
        return [origin.strip() for origin in self.CORS_ALLOW_ORIGINS.split(",") if origin.strip()]

    model_config = SettingsConfigDict(
        env_file=BACKEND_ROOT / ".env",
        env_file_encoding="utf-8"
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()