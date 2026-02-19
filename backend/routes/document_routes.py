"""Document endpoints — list uploads per user, admin view all."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
import io

try:
    from ..database import (
        get_documents_by_user,
        get_all_documents,
        get_document_by_id,
        delete_document_record,
        delete_file_from_gridfs,
        get_file_from_gridfs,
        doc_to_document_response,
        find_user_by_id,
    )
    from ..auth import require_active_user, require_admin
except ImportError:
    from database import (
        get_documents_by_user,
        get_all_documents,
        get_document_by_id,
        delete_document_record,
        delete_file_from_gridfs,
        get_file_from_gridfs,
        doc_to_document_response,
        find_user_by_id,
    )
    from auth import require_active_user, require_admin


router = APIRouter(prefix="/documents", tags=["documents"])


# ------------------------------------------------------------------
# GET /documents/me
# Returns all documents uploaded by the currently logged-in user.
# ------------------------------------------------------------------
@router.get("/me")
def my_documents(current_user: dict = Depends(require_active_user)):
    """List all documents uploaded by the currently authenticated user."""
    docs = get_documents_by_user(current_user["user_id"])
    return {
        "ok": True,
        "user_id": current_user["user_id"],
        "total": len(docs),
        "documents": [doc_to_document_response(d) for d in docs],
    }


# ------------------------------------------------------------------
# GET /documents/user/{user_id}
# Admin: get all documents uploaded by a specific user.
# ------------------------------------------------------------------
@router.get("/user/{user_id}")
def documents_by_user(
    user_id: str,
    current_user: dict = Depends(require_admin),
):
    """List all documents uploaded by a specific user. Admin only."""
    target = find_user_by_id(user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="User not found.")

    docs = get_documents_by_user(user_id)
    return {
        "ok": True,
        "user_id": user_id,
        "email": target.get("email"),
        "total": len(docs),
        "documents": [doc_to_document_response(d) for d in docs],
    }


# ------------------------------------------------------------------
# GET /documents
# Admin: get all documents across all users.
# ------------------------------------------------------------------
@router.get("")
def all_documents(
    limit: int = 100,
    current_user: dict = Depends(require_admin),
):
    """List all uploaded documents across all users. Admin only."""
    docs = get_all_documents(limit=min(limit, 500))
    return {
        "ok": True,
        "total": len(docs),
        "documents": [doc_to_document_response(d) for d in docs],
    }


# ------------------------------------------------------------------
# GET /documents/{document_id}
# Get a single document record.
# Active users can view their own; admins can view any.
# ------------------------------------------------------------------
@router.get("/{document_id}")
def get_document(
    document_id: str,
    current_user: dict = Depends(require_active_user),
):
    """Get a single document record by ID."""
    doc = get_document_by_id(document_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found.")

    # Non-admin users can only view their own documents.
    if current_user["role"] != "admin" and doc.get("user_id") != current_user["user_id"]:
        raise HTTPException(status_code=403, detail="Access denied.")

    return {"ok": True, "document": doc_to_document_response(doc)}


# ------------------------------------------------------------------
# DELETE /documents/{document_id}
# Delete a document record (not the indexed vectors).
# Owner or admin can delete.
# ------------------------------------------------------------------
@router.delete("/{document_id}")
def delete_document(
    document_id: str,
    current_user: dict = Depends(require_active_user),
):
    """Delete a document record and its stored file. Owner or admin only."""
    doc = get_document_by_id(document_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found.")

    if current_user["role"] != "admin" and doc.get("user_id") != current_user["user_id"]:
        raise HTTPException(status_code=403, detail="Access denied.")

    # Remove the stored PDF from GridFS first.
    gridfs_id = doc.get("gridfs_id")
    if gridfs_id:
        delete_file_from_gridfs(gridfs_id)

    delete_document_record(document_id)
    return {
        "ok": True,
        "message": "Document record and stored file deleted.",
        "document_id": document_id,
    }


# ------------------------------------------------------------------
# GET /documents/{document_id}/file
# Download the stored PDF. Owner or admin only.
# ------------------------------------------------------------------
@router.get("/{document_id}/file")
def download_document_file(
    document_id: str,
    current_user: dict = Depends(require_active_user),
):
    """Download the original stored PDF for a document. Owner or admin only."""
    doc = get_document_by_id(document_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found.")

    if current_user["role"] != "admin" and doc.get("user_id") != current_user["user_id"]:
        raise HTTPException(status_code=403, detail="Access denied.")

    gridfs_id = doc.get("gridfs_id")
    if not gridfs_id:
        raise HTTPException(
            status_code=404,
            detail="No stored file found for this document. It may have been uploaded before file storage was enabled.",
        )

    grid_out = get_file_from_gridfs(gridfs_id)
    if grid_out is None:
        raise HTTPException(status_code=404, detail="File not found in storage.")

    filename = doc.get("filename", "document.pdf")
    return StreamingResponse(
        io.BytesIO(grid_out.read()),
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Length": str(grid_out.length),
        },
    )
