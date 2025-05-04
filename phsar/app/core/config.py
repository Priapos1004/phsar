from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    DB_USER: str
    DB_PASSWORD: str
    DB_HOST: str = "localhost"
    DB_PORT: int = 5432
    DB_NAME: str

    ADMIN_USERNAME: str
    ADMIN_PASSWORD: str

    # JWT / Security settings
    SECRET_KEY: str
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60  # Default 1 hour expiry

    class Config:
        env_file = ".env"  # Tell Pydantic to load from .env

settings = Settings()
