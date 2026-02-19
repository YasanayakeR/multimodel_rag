"""JWT creation / verification + bcrypt password helpers."""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Optional

import bcrypt
from jose import JWTError, jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer

try:
    from .database import find_user_by_id, doc_to_user_response
except ImportError:
    from database import find_user_by_id, doc_to_user_response




SECRET_KEY: str = os.getenv("JWT_SECRET_KEY", "change-me-in-production-please")
ALGORITHM: str = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES: int = int(os.getenv("JWT_EXPIRE_MINUTES", "60"))



oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/token")




def hash_password(plain: str) -> str:
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(plain.encode(), salt).decode()


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode(), hashed.encode())
    except Exception:
        return False




def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    to_encode["exp"] = expire
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token.",
            headers={"WWW-Authenticate": "Bearer"},
        ) from e




def get_current_user(token: str = Depends(oauth2_scheme)) -> dict:
    payload = decode_token(token)
    user_id: str = payload.get("sub", "")
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid token payload.")
    user = find_user_by_id(user_id)
    if user is None:
        raise HTTPException(status_code=401, detail="User not found.")
    return doc_to_user_response(user)


def require_active_user(current_user: dict = Depends(get_current_user)) -> dict:
    """Dependency: user must be active (not pending/disabled)."""
    if current_user["status"] != "active":
        raise HTTPException(
            status_code=403,
            detail="Your account is not active. Please wait for admin activation.",
        )
    return current_user


def require_admin(current_user: dict = Depends(get_current_user)) -> dict:
    """Dependency: user must be an admin."""
    if current_user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Admin access required.")
    return current_user
