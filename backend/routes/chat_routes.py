"""Chat session management routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

try:
    from ..database import (
        create_session, get_session, list_sessions, delete_session,
        get_messages, get_documents_by_session,
        doc_to_session_response, doc_to_message_response, doc_to_document_response,
    )
    from ..auth import require_active_user, require_admin
except ImportError:
    from database import (
        create_session, get_session, list_sessions, delete_session,
        get_messages, get_documents_by_session,
        doc_to_session_response, doc_to_message_response, doc_to_document_response,
    )
    from auth import require_active_user, require_admin


router = APIRouter(prefix="/chat", tags=["chat"])


class CreateSessionRequest(BaseModel):
    title: str = "New Chat"


# ------------------------------------------------------------------
# POST /chat/sessions  — create a new session
# ------------------------------------------------------------------
@router.post("/sessions", status_code=201)
def new_session(
    body: CreateSessionRequest = CreateSessionRequest(),
    current_user: dict = Depends(require_active_user),
):
    """Create a new chat session for the authenticated user."""
    session = create_session(user_id=current_user["user_id"], title=body.title)
    return {
        "ok": True,
        "message": "Session created.",
        "session": doc_to_session_response(session),
    }


# ------------------------------------------------------------------
# GET /chat/sessions  — list current user's sessions
# ------------------------------------------------------------------
@router.get("/sessions")
def my_sessions(current_user: dict = Depends(require_active_user)):
    """List all chat sessions for the currently authenticated user."""
    sessions = list_sessions(current_user["user_id"])
    return {
        "ok": True,
        "total": len(sessions),
        "sessions": [doc_to_session_response(s) for s in sessions],
    }


# ------------------------------------------------------------------
# GET /chat/sessions/{session_id}  — get session + its messages
# ------------------------------------------------------------------
@router.get("/sessions/{session_id}")
def get_session_detail(
    session_id: str,
    limit: int = 50,
    current_user: dict = Depends(require_active_user),
):
    """Get a session and its message history."""
    session = get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found.")

    # Only the owner or an admin can view the session.
    if current_user["role"] != "admin" and session.get("user_id") != current_user["user_id"]:
        raise HTTPException(status_code=403, detail="Access denied.")

    messages = get_messages(session_id, limit=limit)
    return {
        "ok": True,
        "session": doc_to_session_response(session),
        "messages": [doc_to_message_response(m) for m in messages],
    }


# ------------------------------------------------------------------
# DELETE /chat/sessions/{session_id}  — delete session + messages
# ------------------------------------------------------------------
@router.delete("/sessions/{session_id}")
def remove_session(
    session_id: str,
    current_user: dict = Depends(require_active_user),
):
    """Delete a session and all its messages. Owner or admin only."""
    session = get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found.")

    if current_user["role"] != "admin" and session.get("user_id") != current_user["user_id"]:
        raise HTTPException(status_code=403, detail="Access denied.")

    delete_session(session_id)
    return {
        "ok": True,
        "message": "Session and all messages deleted.",
        "session_id": session_id,
    }


# ------------------------------------------------------------------
# GET /chat/sessions/{session_id}/documents
# List all documents uploaded to a specific session.
# ------------------------------------------------------------------
@router.get("/sessions/{session_id}/documents")
def session_documents(
    session_id: str,
    current_user: dict = Depends(require_active_user),
):
    """List all documents uploaded to a chat session. Owner or admin only."""
    session = get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found.")

    if current_user["role"] != "admin" and session.get("user_id") != current_user["user_id"]:
        raise HTTPException(status_code=403, detail="Access denied.")

    docs = get_documents_by_session(session_id)
    return {
        "ok": True,
        "session_id": session_id,
        "total": len(docs),
        "documents": [doc_to_document_response(d) for d in docs],
    }


# ------------------------------------------------------------------
# Admin: GET /chat/sessions/user/{user_id}
# ------------------------------------------------------------------
@router.get("/admin/sessions/{user_id}")
def admin_user_sessions(
    user_id: str,
    _: dict = Depends(require_admin),
):
    """List all sessions for a specific user. Admin only."""
    sessions = list_sessions(user_id)
    return {
        "ok": True,
        "user_id": user_id,
        "total": len(sessions),
        "sessions": [doc_to_session_response(s) for s in sessions],
    }
