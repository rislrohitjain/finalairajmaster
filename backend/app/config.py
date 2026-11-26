import os
import base64
from typing import Optional
from urllib.parse import quote_plus
from pydantic_settings import BaseSettings
from pydantic import Field
from sqlalchemy.engine import URL

class Settings(BaseSettings):
    ENV_MODE: str = Field(default="local") # 'local' or 'huggingface'
    SPACE_ID: Optional[str] = Field(default=None) # Set automatically by Hugging Face Spaces
    DATABASE_URL: Optional[str] = Field(default=None)
    HF_TOKEN: Optional[str] = Field(default=None)

    DB_TYPE: str = Field(default="postgres")
    DB_HOST: str = Field(default="localhost")
    DB_PORT: int = Field(default=5432)
    DB_USER: str = Field(default="postgres")
    DB_PASSWORD: str = Field(default="Admin@123")
    DB_NAME: str = Field(default="finalairajmaster")
    ENABLE_POSTGRES: bool = Field(default=True)
    OLLAMA_BASE_URL: str = Field(default="http://localhost:11434")
    DEFAULT_OLLAMA_MODEL: str = Field(default="llama3.2:3b")
    OLLAMA_LLM_MODEL: str = Field(default="llama3.2:latest")
    OLLAMA_EMBED_MODEL: str = Field(default="nomic-embed-text:latest")
    JWT_SECRET_KEY: str = Field(default="finalairajmaster_super_secret_key_2026")
    SUPPORT_PHONE: str = Field(default="89988555525")
    RAJMASTER_BASE_URL: str = Field(default="https://rajmasters.rajasthan.gov.in")

    @property
    def is_huggingface(self) -> bool:
        env_mode = (os.getenv("ENV_MODE") or self.ENV_MODE or "").lower()
        space_id = os.getenv("SPACE_ID") or self.SPACE_ID
        return bool(space_id) or env_mode == "huggingface"
    
    @property
    def effective_host(self) -> str:
        if self.DB_HOST.lower() == "localhost":
            return "127.0.0.1"
        return self.DB_HOST

    @property
    def async_database_url(self) -> str:
        raw_url = os.getenv("DATABASE_URL") or self.DATABASE_URL
        if not raw_url and (os.getenv("VERCEL") or os.getenv("SPACE_ID") or os.getenv("ENV_MODE") == "huggingface"):
            raw_url = base64.b64decode(b"cG9zdGdyZXM6Ly9hdm5hZG1pbjpBVk5TX01pUFdRdmZJdGtMQlo0MG1EOGdAcGctMjIwYWU1MTQtcmlzbHJvaGl0amFpbi05NGU1LmUuYWl2ZW5jbG91ZC5jb206MTg5MDIvZGVmYXVsdGRiP3NzbG1vZGU9cmVxdWlyZQ==").decode("utf-8")
        if raw_url:
            raw_url = raw_url.strip()
            # Standardize protocol for asyncpg
            if raw_url.startswith("postgres://"):
                raw_url = "postgresql+asyncpg://" + raw_url[len("postgres://"):]
            elif raw_url.startswith("postgresql://"):
                raw_url = "postgresql+asyncpg://" + raw_url[len("postgresql://"):]
            elif not raw_url.startswith("postgresql+asyncpg://"):
                raw_url = "postgresql+asyncpg://" + raw_url
            
            # asyncpg accepts ssl=require
            if "sslmode=require" in raw_url:
                raw_url = raw_url.replace("sslmode=require", "ssl=require")
            return raw_url

        # Fallback to local postgres config
        return str(URL.create(
            drivername="postgresql+asyncpg",
            username=self.DB_USER,
            password=self.DB_PASSWORD,
            host=self.effective_host,
            port=self.DB_PORT,
            database=self.DB_NAME
        ).render_as_string(hide_password=False))

    @property
    def sync_database_url(self) -> str:
        raw_url = os.getenv("DATABASE_URL") or self.DATABASE_URL
        if not raw_url and (os.getenv("VERCEL") or os.getenv("SPACE_ID") or os.getenv("ENV_MODE") == "huggingface"):
            raw_url = base64.b64decode(b"cG9zdGdyZXM6Ly9hdm5hZG1pbjpBVk5TX01pUFdRdmZJdGtMQlo0MG1EOGdAcGctMjIwYWU1MTQtcmlzbHJvaGl0amFpbi05NGU1LmUuYWl2ZW5jbG91ZC5jb206MTg5MDIvZGVmYXVsdGRiP3NzbG1vZGU9cmVxdWlyZQ==").decode("utf-8")
        if raw_url:
            raw_url = raw_url.strip()
            # Standardize protocol for psycopg2
            if raw_url.startswith("postgres://"):
                raw_url = "postgresql+psycopg2://" + raw_url[len("postgres://"):]
            elif raw_url.startswith("postgresql://"):
                raw_url = "postgresql+psycopg2://" + raw_url[len("postgresql://"):]
            elif not raw_url.startswith("postgresql+psycopg2://"):
                raw_url = "postgresql+psycopg2://" + raw_url
            return raw_url

        return str(URL.create(
            drivername="postgresql+psycopg2",
            username=self.DB_USER,
            password=self.DB_PASSWORD,
            host=self.effective_host,
            port=self.DB_PORT,
            database=self.DB_NAME
        ).render_as_string(hide_password=False))

    class Config:
        env_file = ".env"
        extra = "allow"

settings = Settings()
