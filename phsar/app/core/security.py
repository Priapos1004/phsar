# app/core/security.py
from datetime import datetime, timedelta, timezone

from jose import jwt
from passlib.context import CryptContext

from app.core.config import settings

SECRET_KEY = settings.SECRET_KEY
SEARCH_SECRET_KEY = settings.SEARCH_SECRET_KEY
ALGORITHM = settings.ALGORITHM
ACCESS_TOKEN_EXPIRE_MINUTES = settings.ACCESS_TOKEN_EXPIRE_MINUTES
CURRENT_SEARCH_API_VERSION = settings.CURRENT_SEARCH_API_VERSION

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def verify_password(plain_password, hashed_password):
    return pwd_context.verify(plain_password, hashed_password)

def get_password_hash(password):
    return pwd_context.hash(password)

def create_token(data: dict, secret_key: str, extra_info: dict | None = None):
    to_encode = data.copy()
    if extra_info:
        to_encode.update(extra_info)
    return jwt.encode(to_encode, secret_key, algorithm=ALGORITHM)

def create_access_token(data: dict, expires_delta: timedelta | None = None):
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    return create_token(data, secret_key=SECRET_KEY, extra_info={"exp": expire})

def create_url_token(data: dict):
    return create_token(data, secret_key=SEARCH_SECRET_KEY, extra_info={"ver": CURRENT_SEARCH_API_VERSION})
