"""MongoDB helpers for users and documents collections."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Optional

import gridfs
from bson import ObjectId
from pymongo import MongoClient, ASCENDING, DESCENDING
from pymongo.collection import Collection


def _get_db():
    uri = os.getenv("MONGODB_URI", "mongodb://localhost:27017")
    db_name = os.getenv("MONGODB_DB", "multimodal")
    client = MongoClient(
        uri,
        serverSelectionTimeoutMS=5000,
        connectTimeoutMS=5000,
    )
    return client[db_name]


def _get_users_collection() -> Collection:
    db = _get_db()
    col = db["users"]
    col.create_index([("email", ASCENDING)], unique=True, background=True)
    return col


def _get_documents_collection() -> Collection:
    db = _get_db()
    col = db["documents"]
    col.create_index([("user_id", ASCENDING)], background=True)
    col.create_index([("session_id", ASCENDING)], background=True)
    col.create_index([("uploaded_at", DESCENDING)], background=True)
    return col


_users_col: Optional[Collection] = None
_docs_col: Optional[Collection] = None
_gridfs: Optional[gridfs.GridFS] = None


def get_users_col() -> Collection:
    global _users_col
    if _users_col is None:
        _users_col = _get_users_collection()
    return _users_col


def get_docs_col() -> Collection:
    global _docs_col
    if _docs_col is None:
        _docs_col = _get_documents_collection()
    return _docs_col


def get_gridfs() -> gridfs.GridFS:
    global _gridfs
    if _gridfs is None:
        _gridfs = gridfs.GridFS(_get_db())
    return _gridfs


# --- CRUD helpers ---

def create_user(email: str, hashed_password: str, full_name: str, role: str = "user") -> dict:
    col = get_users_col()
    doc = {
        "email": email.lower().strip(),
        "hashed_password": hashed_password,
        "full_name": full_name,
        "role": role,
        "status": "pending",
        "created_at": datetime.now(timezone.utc),
        "activated_at": None,
    }
    result = col.insert_one(doc)
    doc["_id"] = result.inserted_id
    return doc


def find_user_by_email(email: str) -> Optional[dict]:
    return get_users_col().find_one({"email": email.lower().strip()})


def find_user_by_id(user_id: str) -> Optional[dict]:
    try:
        oid = ObjectId(user_id)
    except Exception:
        return None
    return get_users_col().find_one({"_id": oid})


def activate_user(user_id: str) -> Optional[dict]:
    try:
        oid = ObjectId(user_id)
    except Exception:
        return None
    col = get_users_col()
    col.update_one(
        {"_id": oid},
        {"$set": {"status": "active", "activated_at": datetime.now(timezone.utc)}},
    )
    return col.find_one({"_id": oid})


def deactivate_user(user_id: str) -> Optional[dict]:
    try:
        oid = ObjectId(user_id)
    except Exception:
        return None
    col = get_users_col()
    col.update_one({"_id": oid}, {"$set": {"status": "disabled"}})
    return col.find_one({"_id": oid})


def list_all_users() -> list[dict]:
    return list(get_users_col().find({}, {"hashed_password": 0}))


def doc_to_user_response(doc: dict) -> dict:
    """Convert a MongoDB user document to a safe dict (no password)."""
    return {
        "user_id": str(doc["_id"]),
        "email": doc["email"],
        "full_name": doc.get("full_name", ""),
        "role": doc.get("role", "user"),
        "status": doc.get("status", "pending"),
        "created_at": doc.get("created_at"),
        "activated_at": doc.get("activated_at"),
    }


# -----------------------------------------------------------------------
# Document upload records
# -----------------------------------------------------------------------

def save_document_record(
    user_id: str,
    filename: str,
    counts: dict,
    file_size_bytes: int = 0,
    session_id: Optional[str] = None,
) -> dict:
    """Persist upload metadata for a user, optionally linked to a session."""
    col = get_docs_col()
    doc = {
        "user_id": user_id,
        "session_id": session_id,  
        "filename": filename,
        "counts": counts,          # {"texts": n, "tables": n, "images": n}
        "file_size_bytes": file_size_bytes,
        "uploaded_at": datetime.now(timezone.utc),
    }
    result = col.insert_one(doc)
    doc["_id"] = result.inserted_id
    return doc


def get_documents_by_user(user_id: str) -> list[dict]:
    """Return all upload records for a given user, newest first."""
    col = get_docs_col()
    return list(col.find({"user_id": user_id}).sort("uploaded_at", DESCENDING))


def get_documents_by_session(session_id: str) -> list[dict]:
    """Return all upload records linked to a specific session, newest first."""
    col = get_docs_col()
    return list(col.find({"session_id": session_id}).sort("uploaded_at", DESCENDING))


def get_all_documents(limit: int = 500) -> list[dict]:
    """Return all upload records across all users (admin use). Newest first."""
    col = get_docs_col()
    return list(col.find({}).sort("uploaded_at", DESCENDING).limit(limit))


def get_document_by_id(doc_id: str) -> Optional[dict]:
    """Return a single document record by its MongoDB _id."""
    try:
        oid = ObjectId(doc_id)
    except Exception:
        return None
    return get_docs_col().find_one({"_id": oid})


def delete_document_record(doc_id: str) -> bool:
    """Delete a document record. Returns True if deleted."""
    try:
        oid = ObjectId(doc_id)
    except Exception:
        return False
    result = get_docs_col().delete_one({"_id": oid})
    return result.deleted_count > 0


def doc_to_document_response(doc: dict) -> dict:
    return {
        "document_id": str(doc["_id"]),
        "user_id": doc.get("user_id", ""),
        "session_id": doc.get("session_id"),
        "filename": doc.get("filename", ""),
        "counts": doc.get("counts", {}),
        "file_size_bytes": doc.get("file_size_bytes", 0),
        "uploaded_at": doc.get("uploaded_at"),
        "has_file": bool(doc.get("gridfs_id")),
    }


def store_file_in_gridfs(
    file_bytes: bytes,
    filename: str,
    user_id: str,
    content_type: str = "application/pdf",
) -> str:
    """Store raw file bytes in GridFS and return the GridFS file id (str)."""
    fs = get_gridfs()
    gridfs_id = fs.put(
        file_bytes,
        filename=filename,
        user_id=user_id,
        content_type=content_type,
        upload_date=datetime.now(timezone.utc),
    )
    return str(gridfs_id)


def get_file_from_gridfs(gridfs_id: str) -> Optional[gridfs.GridOut]:
    """Return a GridOut object (readable stream) or None if not found."""
    try:
        oid = ObjectId(gridfs_id)
    except Exception:
        return None
    fs = get_gridfs()
    try:
        return fs.get(oid)
    except gridfs.errors.NoFile:
        return None


def delete_file_from_gridfs(gridfs_id: str) -> bool:
    """Delete a file from GridFS. Returns True if deleted."""
    try:
        oid = ObjectId(gridfs_id)
    except Exception:
        return False
    try:
        get_gridfs().delete(oid)
        return True
    except Exception:
        return False


def attach_gridfs_id_to_document(doc_id: str, gridfs_id: str) -> None:
    """Link a GridFS file id to an existing document record."""
    try:
        oid = ObjectId(doc_id)
    except Exception:
        return
    get_docs_col().update_one({"_id": oid}, {"$set": {"gridfs_id": gridfs_id}})


# -----------------------------------------------------------------------
# Chat sessions & message history
# -----------------------------------------------------------------------

_sessions_col: Optional[Collection] = None
_messages_col: Optional[Collection] = None


def get_sessions_col() -> Collection:
    global _sessions_col
    if _sessions_col is None:
        db = _get_db()
        col = db["chat_sessions"]
        col.create_index([("user_id", ASCENDING)], background=True)
        col.create_index([("created_at", DESCENDING)], background=True)
        _sessions_col = col
    return _sessions_col


def get_messages_col() -> Collection:
    global _messages_col
    if _messages_col is None:
        db = _get_db()
        col = db["chat_messages"]
        col.create_index([("session_id", ASCENDING)], background=True)
        col.create_index([("created_at", ASCENDING)], background=True)
        _messages_col = col
    return _messages_col


def create_session(user_id: str, title: str = "New Chat") -> dict:
    col = get_sessions_col()
    doc = {
        "user_id": user_id,
        "title": title,
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
        "message_count": 0,
    }
    result = col.insert_one(doc)
    doc["_id"] = result.inserted_id
    return doc


def get_session(session_id: str) -> Optional[dict]:
    try:
        oid = ObjectId(session_id)
    except Exception:
        return None
    return get_sessions_col().find_one({"_id": oid})


def list_sessions(user_id: str) -> list[dict]:
    return list(
        get_sessions_col()
        .find({"user_id": user_id})
        .sort("updated_at", DESCENDING)
    )


def delete_session(session_id: str) -> bool:
    try:
        oid = ObjectId(session_id)
    except Exception:
        return False
    get_sessions_col().delete_one({"_id": oid})
    # Also delete all messages in the session.
    get_messages_col().delete_many({"session_id": session_id})
    return True


def update_session_meta(session_id: str, title: str = None) -> None:
    try:
        oid = ObjectId(session_id)
    except Exception:
        return
    update: dict = {"updated_at": datetime.now(timezone.utc)}
    if title is not None:
        update["title"] = title
    get_sessions_col().update_one({"_id": oid}, {"$set": update, "$inc": {"message_count": 1}})


def save_message(session_id: str, role: str, content: str) -> dict:
    """role: 'user' | 'assistant'"""
    col = get_messages_col()
    doc = {
        "session_id": session_id,
        "role": role,
        "content": content,
        "created_at": datetime.now(timezone.utc),
    }
    result = col.insert_one(doc)
    doc["_id"] = result.inserted_id
    return doc


def get_messages(session_id: str, limit: int = 50) -> list[dict]:
    """Return last `limit` messages for a session, oldest first."""
    col = get_messages_col()
    total = col.count_documents({"session_id": session_id})
    skip = max(0, total - limit)
    return list(
        col.find({"session_id": session_id})
        .sort("created_at", ASCENDING)
        .skip(skip)
    )


def doc_to_session_response(doc: dict) -> dict:
    return {
        "session_id": str(doc["_id"]),
        "user_id": doc.get("user_id", ""),
        "title": doc.get("title", "New Chat"),
        "message_count": doc.get("message_count", 0),
        "created_at": doc.get("created_at"),
        "updated_at": doc.get("updated_at"),
    }


def doc_to_message_response(doc: dict) -> dict:
    return {
        "message_id": str(doc["_id"]),
        "session_id": doc.get("session_id", ""),
        "role": doc.get("role", ""),
        "content": doc.get("content", ""),
        "created_at": doc.get("created_at"),
    }
