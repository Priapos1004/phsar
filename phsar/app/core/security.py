# app/core/security.py
import base64
import json
import zlib
from datetime import datetime, timedelta, timezone

from jose import jwt
from passlib.context import CryptContext

from app.core.config import settings
from app.exceptions import DecompressionError

pwd_context = CryptContext(
    schemes=["argon2"],
    deprecated="auto",
    argon2__type="ID",              # Make the variant explicit (Argon2id)
)

def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)

def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)

# One fixed dummy hash to equalize timing when user doesn't exist
DUMMY_HASH = get_password_hash("not-the-right-password")

def needs_rehash(hashed_password: str) -> bool:
    return pwd_context.needs_update(hashed_password)

def compress_and_encode(data: dict) -> str:
    compressed = zlib.compress(json.dumps(data).encode("utf-8"))
    return base64.urlsafe_b64encode(compressed).decode("utf-8")

def decompress_and_decode(encoded: str) -> dict:
    try:
        compressed = base64.urlsafe_b64decode(encoded.encode("utf-8"))
        return json.loads(zlib.decompress(compressed).decode("utf-8"))
    except Exception:
        raise DecompressionError()

def create_token(data: dict, secret_key: str, extra_info: dict | None = None) -> str:
    to_encode = data.copy()
    if extra_info:
        to_encode.update(extra_info)
    return jwt.encode(to_encode, secret_key, algorithm=settings.ALGORITHM)

def create_access_token(data: dict, expires_delta: timedelta | None = None) -> str:
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    return create_token(data, secret_key=settings.SECRET_KEY, extra_info={"exp": expire})

def create_url_token(data: dict) -> str:
    payload = {
        "ver": settings.CURRENT_SEARCH_API_VERSION,
        "data": compress_and_encode(data)
    }
    return create_token(payload, secret_key=settings.SEARCH_SECRET_KEY)
