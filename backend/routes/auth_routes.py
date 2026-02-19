"""Authentication routes: signup, login, me, admin endpoints."""

from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import OAuth2PasswordRequestForm
from pymongo.errors import DuplicateKeyError

try:
    from ..models import (
        SignupRequest, LoginRequest, TokenResponse,
        UserResponse, AdminActivateResponse,
    )
    from ..database import (
        create_user, find_user_by_email, find_user_by_id,
        activate_user, deactivate_user, list_all_users, doc_to_user_response,
    )
    from ..auth import (
        hash_password, verify_password, create_access_token,
        get_current_user, require_active_user, require_admin,
    )
except ImportError:
    from models import (
        SignupRequest, LoginRequest, TokenResponse,
        UserResponse, AdminActivateResponse,
    )
    from database import (
        create_user, find_user_by_email, find_user_by_id,
        activate_user, deactivate_user, list_all_users, doc_to_user_response,
    )
    from auth import (
        hash_password, verify_password, create_access_token,
        get_current_user, require_active_user, require_admin,
    )


router = APIRouter(prefix="/auth", tags=["auth"])


# ------------------------------------------------------------------
# POST /auth/signup
# ------------------------------------------------------------------
@router.post("/signup", status_code=201)
def signup(body: SignupRequest):
    """Register a new user.

    - If the email matches ADMIN_EMAIL env var, the account is created as admin + active.
    - All other accounts start as 'pending' until an admin activates them.
    """
    import os
    from datetime import datetime, timezone

    admin_email = (os.getenv("ADMIN_EMAIL") or "").lower().strip()
    is_admin = body.email.lower().strip() == admin_email

    hashed = hash_password(body.password)
    try:
        doc = create_user(
            email=body.email,
            hashed_password=hashed,
            full_name=body.full_name,
            role="admin" if is_admin else "user",
        )
    except DuplicateKeyError:
        raise HTTPException(status_code=409, detail="Email already registered.")

    # Auto-activate the designated admin.
    if is_admin:
        activate_user(str(doc["_id"]))
        doc["status"] = "active"

    return {
        "ok": True,
        "message": (
            "Admin account created and activated. You can log in now."
            if is_admin
            else "Account created. Wait for admin to activate your account before logging in."
        ),
        "user_id": str(doc["_id"]),
        "email": doc["email"],
        "status": doc["status"],
    }


# ------------------------------------------------------------------
# POST /auth/login
# ------------------------------------------------------------------
@router.post("/login", response_model=TokenResponse)
def login(body: LoginRequest):
    """Login and receive a JWT access token. Account must be active."""
    user = find_user_by_email(body.email)
    if not user or not verify_password(body.password, user["hashed_password"]):
        raise HTTPException(status_code=401, detail="Invalid email or password.")

    if user["status"] == "pending":
        raise HTTPException(
            status_code=403,
            detail="Account pending activation. Please contact an admin.",
        )
    if user["status"] == "disabled":
        raise HTTPException(status_code=403, detail="Account has been disabled.")

    token = create_access_token({"sub": str(user["_id"]), "role": user["role"]})

    return {
        "ok": True,
        "access_token": token,
        "token_type": "bearer",
        "user_id": str(user["_id"]),
        "email": user["email"],
        "role": user["role"],
        "status": user["status"],
    }


# ------------------------------------------------------------------
# POST /auth/token  ← OAuth2 password-flow endpoint (form data)
#   Used by Swagger UI "Authorize" dialog.
#   username field = email (OAuth2 spec uses "username").
# ------------------------------------------------------------------
@router.post("/token", response_model=TokenResponse, include_in_schema=False)
def token_form(form: OAuth2PasswordRequestForm = Depends()):
    """OAuth2 password-flow token endpoint (form data).

    Swagger UI sends ``username`` + ``password`` as form fields.
    We treat ``username`` as the email address.
    """
    user = find_user_by_email(form.username)
    if not user or not verify_password(form.password, user["hashed_password"]):
        raise HTTPException(status_code=401, detail="Invalid email or password.")

    if user["status"] == "pending":
        raise HTTPException(
            status_code=403,
            detail="Account pending activation. Please contact an admin.",
        )
    if user["status"] == "disabled":
        raise HTTPException(status_code=403, detail="Account has been disabled.")

    token = create_access_token({"sub": str(user["_id"]), "role": user["role"]})
    return {
        "ok": True,
        "access_token": token,
        "token_type": "bearer",
        "user_id": str(user["_id"]),
        "email": user["email"],
        "role": user["role"],
        "status": user["status"],
    }


# ------------------------------------------------------------------
# GET /auth/me
# ------------------------------------------------------------------
@router.get("/me", response_model=UserResponse)
def me(current_user: dict = Depends(get_current_user)):
    """Return the currently authenticated user's profile."""
    return {"ok": True, **current_user}


# ------------------------------------------------------------------
# Admin: GET /auth/admin/users
# ------------------------------------------------------------------
@router.get("/admin/users")
def admin_list_users(_: dict = Depends(require_admin)):
    """List all registered users. Admin only."""
    users = list_all_users()
    return {
        "ok": True,
        "total": len(users),
        "users": [doc_to_user_response(u) for u in users],
    }


# ------------------------------------------------------------------
# Admin: POST /auth/admin/activate/{user_id}
# ------------------------------------------------------------------
@router.post("/admin/activate/{user_id}", response_model=AdminActivateResponse)
def admin_activate(user_id: str, _: dict = Depends(require_admin)):
    """Activate a pending user account. Admin only."""
    updated = activate_user(user_id)
    if updated is None:
        raise HTTPException(status_code=404, detail="User not found.")
    return {
        "ok": True,
        "message": "User activated successfully.",
        "user_id": str(updated["_id"]),
        "status": updated["status"],
    }


# ------------------------------------------------------------------
# Admin: POST /auth/admin/deactivate/{user_id}
# ------------------------------------------------------------------
@router.post("/admin/deactivate/{user_id}", response_model=AdminActivateResponse)
def admin_deactivate(user_id: str, _: dict = Depends(require_admin)):
    """Disable a user account. Admin only."""
    updated = deactivate_user(user_id)
    if updated is None:
        raise HTTPException(status_code=404, detail="User not found.")
    return {
        "ok": True,
        "message": "User disabled.",
        "user_id": str(updated["_id"]),
        "status": updated["status"],
    }
