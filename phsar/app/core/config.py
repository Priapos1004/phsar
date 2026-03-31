from pydantic import ConfigDict
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
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30  # Default 30 minutes expiry

    SEARCH_SECRET_KEY: str
    CURRENT_SEARCH_API_VERSION: str = "v1.0.0" # Used to expire tokens when API changes

    # Filter settings
    MAX_ITEMS: int = 5  # Maximum number of items to keep search token size manageable
    MAX_TOKEN_LENGTH: int = 1400  # Safe for URLs

    model_config = ConfigDict(env_file=".env")  # Tell Pydantic to load from .env

settings = Settings()
