from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.core.auth import (
    ALLOW_SELF_REGISTRATION,
    AuthenticatedUser,
    authenticate_user,
    create_access_token,
    create_user,
    ensure_bootstrap_admin,
    require_authenticated_user,
)

router = APIRouter()


class RegisterRequest(BaseModel):
    username: str
    password: str
    full_name: Optional[str] = None


class LoginRequest(BaseModel):
    username: str
    password: str


class AuthResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: AuthenticatedUser


@router.get("/auth/config")
async def get_auth_config():
    ensure_bootstrap_admin()
    return {"allow_self_registration": ALLOW_SELF_REGISTRATION}


@router.post("/auth/register", response_model=AuthResponse)
async def register(payload: RegisterRequest):
    if not ALLOW_SELF_REGISTRATION:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Self-registration is disabled")

    try:
        user = create_user(payload.username, payload.password, payload.full_name)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    return AuthResponse(access_token=create_access_token(user), user=user)


@router.post("/auth/login", response_model=AuthResponse)
async def login(payload: LoginRequest):
    user = authenticate_user(payload.username, payload.password)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid username or password")
    return AuthResponse(access_token=create_access_token(user), user=user)


@router.get("/auth/me", response_model=AuthenticatedUser)
async def get_me(current_user: AuthenticatedUser = Depends(require_authenticated_user)):
    return current_user
