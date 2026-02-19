"""Pydantic models for users and auth."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, EmailStr, Field


class UserRole(str, Enum):
    admin = "admin"
    user = "user"


class UserStatus(str, Enum):
    pending = "pending"    # registered, waiting for admin activation
    active = "active"      # can use the API
    disabled = "disabled"  # blocked by admin




class SignupRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)
    full_name: str = Field(min_length=1, max_length=100)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    ok: bool = True
    access_token: str
    token_type: str = "bearer"
    user_id: str
    email: str
    role: UserRole
    status: UserStatus


class UserResponse(BaseModel):
    ok: bool = True
    user_id: str
    email: str
    full_name: str
    role: UserRole
    status: UserStatus
    created_at: datetime
    activated_at: Optional[datetime] = None


class AdminActivateResponse(BaseModel):
    ok: bool = True
    message: str
    user_id: str
    status: UserStatus
