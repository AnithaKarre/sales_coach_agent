"""
Phase 1 — Authentication APIs
POST /api/v1/auth/login
POST /api/v1/auth/refresh
POST /api/v1/auth/logout
GET  /api/v1/auth/me
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional

from api.database import get_db
from api.dependencies import (
    hash_password,
    create_access_token,
    create_refresh_token,
    decode_token,
    blacklist_token,
    get_current_user,
    security,
)
from fastapi.security import HTTPAuthorizationCredentials

router = APIRouter(prefix="/api/v1/auth", tags=["Authentication"])


# ── Request / Response Models ─────────────────────────────────
class LoginRequest(BaseModel):
    email: str
    password: str


class LoginResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user: dict


class RefreshRequest(BaseModel):
    refresh_token: str


# ── POST /login ───────────────────────────────────────────────
@router.post("/login", response_model=LoginResponse)
async def login(req: LoginRequest, conn=Depends(get_db)):
    """Authenticate user and return JWT tokens."""
    cur = conn.cursor()
    cur.execute(
        "SELECT id, email, full_name, role, password_hash FROM users WHERE email = %s AND is_active = TRUE",
        (req.email,),
    )
    user = cur.fetchone()

    if not user or user["password_hash"] != hash_password(req.password):
        raise HTTPException(status_code=401, detail="Invalid email or password")

    token_data = {
        "user_id": str(user["id"]),
        "email": user["email"],
        "full_name": user["full_name"],
        "role": user["role"],
    }

    return LoginResponse(
        access_token=create_access_token(token_data),
        refresh_token=create_refresh_token(token_data),
        user={
            "user_id": str(user["id"]),
            "name": user["full_name"],
            "role": user["role"],
        },
    )


# ── POST /refresh ────────────────────────────────────────────
@router.post("/refresh")
async def refresh(req: RefreshRequest):
    """Exchange a valid refresh token for a new access token."""
    payload = decode_token(req.refresh_token)
    if payload.get("type") != "refresh":
        raise HTTPException(status_code=401, detail="Invalid refresh token")

    token_data = {
        "user_id": payload["user_id"],
        "email": payload["email"],
        "full_name": payload["full_name"],
        "role": payload["role"],
    }
    return {
        "access_token": create_access_token(token_data),
        "token_type": "bearer",
    }


# ── POST /logout ─────────────────────────────────────────────
@router.post("/logout")
async def logout(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    user: dict = Depends(get_current_user),
):
    """Revoke the current access token."""
    blacklist_token(credentials.credentials)
    return {"message": "Logged out successfully"}


# ── GET /me ──────────────────────────────────────────────────
@router.get("/me")
async def me(user: dict = Depends(get_current_user), conn=Depends(get_db)):
    """Return the current authenticated user's profile."""
    cur = conn.cursor()
    cur.execute(
        "SELECT id, email, full_name, role, region, area FROM users WHERE id = %s::uuid",
        (user["user_id"],),
    )
    row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="User not found")

    return {
        "user_id": str(row["id"]),
        "name": row["full_name"],
        "email": row["email"],
        "role": row["role"],
        "region": row["region"],
        "area": row["area"],
    }
