import os
from functools import lru_cache
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment variables.
    
    Supports both local development (.env) and cloud deployment (Render, Railway)
    where DATABASE_URL is injected at runtime.
    """
    APP_NAME: str = "Product Catalog API"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = False

    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/products_db"

    # Pagination
    DEFAULT_PAGE_SIZE: int = 20
    MAX_PAGE_SIZE: int = 100

    # Seeding
    SEED_BATCH_SIZE: int = 5000
    SEED_TOTAL_PRODUCTS: int = 200_000

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


@lru_cache()
def get_settings() -> Settings:
    return Settings()
