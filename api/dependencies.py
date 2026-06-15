"""
SalesCoach AI — Authentication dependencies
=============================================
JWT-based auth with role validation.
"""

import os
import hashlib
from datetime import datetime, timedelta, timezone
from typing import Optional
from functools import wraps

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from dotenv import load_dotenv
load_dotenv()

# ---------------------------------------------------------------------------
# JWT implementation using PyJWT
# ---------------------------------------------------------------------------
try:
    import jwt as pyjwt
except ImportError:
    pyjwt = None

SECRET_KEY = os.environ.get("JWT_SECRET_KEY", "salescoach-dev-secret-change-in-prod")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60
REFRESH_TOKEN_EXPIRE_DAYS = 7

security = HTTPBearer(auto_error=False)


def hash_password(password: str) -> str:
    """SHA-256 hash — matches the seed script. In production use bcrypt."""
    return hashlib.sha256(password.encode()).hexdigest()


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire, "type": "access"})
    return pyjwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def create_refresh_token(data: dict) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
    to_encode.update({"exp": expire, "type": "refresh"})
    return pyjwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def decode_token(token: str) -> dict:
    try:
        payload = pyjwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except pyjwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token has expired")
    except pyjwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")


# In-memory token blacklist (use Redis in production)
_blacklisted_tokens: set = set()


def blacklist_token(token: str):
    _blacklisted_tokens.add(token)


def is_blacklisted(token: str) -> bool:
    return token in _blacklisted_tokens


async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)) -> dict:
    """
    FastAPI dependency: extracts and validates the JWT from the Authorization header.
    Returns the user payload dict with user_id, role, full_name, email.
    """
    if credentials is None:
        raise HTTPException(status_code=401, detail="Not authenticated")

    token = credentials.credentials
    if is_blacklisted(token):
        raise HTTPException(status_code=401, detail="Token has been revoked")

    payload = decode_token(token)
    if payload.get("type") != "access":
        raise HTTPException(status_code=401, detail="Invalid token type")

    return {
        "user_id": payload.get("user_id"),
        "role": payload.get("role"),
        "full_name": payload.get("full_name"),
        "email": payload.get("email"),
    }


def require_role(*allowed_roles):
    """
    Returns a FastAPI dependency that checks the user's role.
    Usage:  current_user = Depends(require_role("Admin", "Manager"))
    """
    async def role_checker(user: dict = Depends(get_current_user)) -> dict:
        if user["role"] not in allowed_roles:
            raise HTTPException(
                status_code=403,
                detail=f"Access denied. Required role: {', '.join(allowed_roles)}"
            )
        return user
    return role_checker
