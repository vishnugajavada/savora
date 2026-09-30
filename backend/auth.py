import os
import hmac
import hashlib
import base64
import time
import secrets
import jwt
from dotenv import load_dotenv

load_dotenv()

_configured_secret = os.getenv("JWT_SECRET", "").strip()
if _configured_secret:
    if len(_configured_secret) < 32:
        raise RuntimeError("JWT_SECRET must contain at least 32 characters.")
    SECRET_KEY = _configured_secret
elif os.getenv("MONGO_URI", "").strip():
    raise RuntimeError("JWT_SECRET must be set when using a persistent database.")
else:
    # Keep zero-setup local development, but never use a predictable signing
    # key. Tokens from a local run are intentionally invalid after restart.
    SECRET_KEY = secrets.token_urlsafe(48)
TOKEN_EXPIRY_SECONDS = 60 * 60 * 24 * 7  # 7 days


def hash_password(password: str) -> str:
    """PBKDF2-HMAC-SHA256 with a random salt — pure Python stdlib, so it never
    needs a C compiler to install (unlike bcrypt, which can fail to build on
    Windows machines without Visual Studio Build Tools)."""
    salt = os.urandom(16)
    pwd_hash = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 100_000)
    return base64.b64encode(salt).decode() + "$" + base64.b64encode(pwd_hash).decode()


def verify_password(password: str, stored_hash: str) -> bool:
    try:
        salt_b64, hash_b64 = stored_hash.split("$")
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(hash_b64)
        actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 100_000)
        return hmac.compare_digest(actual, expected)
    except Exception:
        return False


def create_token(user_id: str) -> str:
    payload = {"user_id": user_id, "exp": int(time.time()) + TOKEN_EXPIRY_SECONDS}
    return jwt.encode(payload, SECRET_KEY, algorithm="HS256")


def decode_token(token: str):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
        return payload.get("user_id")
    except jwt.PyJWTError:
        return None
