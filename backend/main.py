import os
import shutil
from typing import Any

from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Request, Depends
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from dotenv import load_dotenv
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent
_DOTENV = _HERE / ".env"
if not _DOTENV.exists():
    _DOTENV = _ROOT / ".env"
load_dotenv(dotenv_path=_DOTENV)

try:
    from .rag_engine import MultiModalRAG
    from .auth import require_active_user
    from .routes.auth_routes import router as auth_router
    from .routes.document_routes import router as document_router
    from .routes.chat_routes import router as chat_router
    from .database import (
        save_document_record,
        store_file_in_gridfs,
        attach_gridfs_id_to_document,
        get_session,
        create_session,
        get_messages,
        save_message,
        update_session_meta,
    )
except ImportError:
    from rag_engine import MultiModalRAG
    from auth import require_active_user
    from routes.auth_routes import router as auth_router
    from routes.document_routes import router as document_router
    from routes.chat_routes import router as chat_router
    from database import (
        save_document_record,
        store_file_in_gridfs,
        attach_gridfs_id_to_document,
        get_session,
        create_session,
        get_messages,
        save_message,
        update_session_meta,
    )

# Initialize FastAPI with OpenAPI security scheme so Swagger shows Authorize button.
app = FastAPI(
    title="Multi-Modal RAG API",
    version="1.0.0",
    swagger_ui_parameters={"persistAuthorization": True},
)

# --- CORS (for Next.js frontend) ---
_origins_raw = os.getenv("CORS_ALLOW_ORIGINS", "").strip()
if _origins_raw:
    _origins = [o.strip() for o in _origins_raw.split(",") if o.strip()]
else:
    _origins = [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:3001",
        "http://127.0.0.1:3001",
    ]

_allow_all = any(o == "*" for o in _origins)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if _allow_all else _origins,
    allow_credentials=False if _allow_all else True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routers
app.include_router(auth_router)
app.include_router(document_router)
app.include_router(chat_router)

# Initialize Engine
rag_engine = MultiModalRAG()


@app.on_event("shutdown")
def shutdown_event():
    # Close Mongo client if present
    store = getattr(rag_engine, "store", None)
    close = getattr(store, "close", None)
    if callable(close):
        close()

# --- Pydantic Models ---
class QueryRequest(BaseModel):
    question: str
    session_id: str | None = None

class QueryResponse(BaseModel):
    ok: bool = True
    status: str = "success"
    answer: str
    images: list[str] = []
    meta: dict[str, Any] = {}
    # session_id always returned so frontend can reuse it for follow-up questions.

# --- Routes ---

@app.get("/")
def home():
    return {
        "ok": True,
        "status": "success",
        "message": "Online",
        "python_version": "3.10 Compatible",
    }

@app.post("/upload")
async def upload_pdf(
    file: UploadFile = File(...),
    session_id: str = Form(None),
    current_user: dict = Depends(require_active_user),
):
    """Uploads, indexes, and stores a PDF. Optionally linked to a session via session_id form field."""
    temp_file = f"temp_{file.filename}"
    try:
        # Validate the session_id if provided
        if session_id:
            session = get_session(session_id)
            if session is None:
                raise HTTPException(status_code=404, detail="Session not found.")
            if session.get("user_id") != current_user["user_id"]:
                raise HTTPException(status_code=403, detail="Session does not belong to you.")

        # Read file bytes once so we can both index and store it.
        file_bytes = await file.read()
        file_size = len(file_bytes)

        # Write to temp disk file for the RAG engine.
        with open(temp_file, "wb") as buffer:
            buffer.write(file_bytes)

        # Index the PDF.
        result = rag_engine.process_pdf(
            temp_file,
            user_id=current_user["user_id"],
            session_id=session_id or None,
        )
        os.remove(temp_file)

        filename = file.filename or "unknown.pdf"

        # Save document metadata record, linked to the session if provided.
        saved = save_document_record(
            user_id=current_user["user_id"],
            filename=filename,
            counts=result.get("counts", {}),
            file_size_bytes=file_size,
            session_id=session_id or None,
        )
        doc_id = str(saved["_id"])

        # Store actual PDF bytes in GridFS and link to the document record.
        try:
            gridfs_id = store_file_in_gridfs(
                file_bytes=file_bytes,
                filename=filename,
                user_id=current_user["user_id"],
                content_type=file.content_type or "application/pdf",
            )
            attach_gridfs_id_to_document(doc_id, gridfs_id)
        except Exception as gridfs_err:
            # GridFS failure is non-fatal — indexing already succeeded.
            print(f"GridFS store warning: {gridfs_err}")
            gridfs_id = None

        return {
            "ok": True,
            "status": result.get("status", "success"),
            "message": "PDF indexed and stored successfully",
            "document_id": doc_id,
            "file_stored": gridfs_id is not None,
            **result,
        }

    except Exception as e:
        if os.path.exists(temp_file):
            os.remove(temp_file)
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/query", response_model=QueryResponse)
async def query_rag(
    body: QueryRequest,
    current_user: dict = Depends(require_active_user),
):
    """Ask a question with optional session memory.

    - **question**: Your question about the uploaded document.
    - **session_id**: *(optional)* Pass a previous session_id to continue a conversation with memory. Omit to auto-create a new session.
    """
    try:
        question = body.question.strip()
        session_id = body.session_id or None

        if not question:
            raise HTTPException(status_code=422, detail="Question is empty.")

        # --- Load or create session ---
        chat_history: list[dict] = []
        if session_id:
            session = get_session(session_id)
            if session is None:
                raise HTTPException(status_code=404, detail="Session not found.")
            if session.get("user_id") != current_user["user_id"]:
                raise HTTPException(status_code=403, detail="Session does not belong to you.")
        
            raw_msgs = get_messages(session_id, limit=20)
            chat_history = [
                {"role": m["role"], "content": m["content"]} for m in raw_msgs
            ]
        else:
       
            title = question[:60] + ("…" if len(question) > 60 else "")
            new_session = create_session(user_id=current_user["user_id"], title=title)
            session_id = str(new_session["_id"])


        response = rag_engine.query(
            question,
            chat_history=chat_history,
            user_id=current_user["user_id"],
            session_id=session_id,
        )
        answer = response.get("answer", "")
        images = response.get("images", [])


        save_message(session_id, role="user", content=question)
        save_message(session_id, role="assistant", content=answer)
        update_session_meta(session_id)

        return {
            "ok": True,
            "status": "success",
            "answer": answer,
            "images": images,
            "meta": {
                "question": question,
                "session_id": session_id,
                "images_count": len(images),
            },
        }
    except Exception as e:
        print(f"Query error: {e}")
        raise HTTPException(status_code=500, detail=f"Query failed: {e}")



@app.exception_handler(HTTPException)
async def http_exception_handler(_: Request, exc: HTTPException):
    
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "ok": False,
            "status": "error",
            "detail": exc.detail,
            "error": {
                "type": "http_exception",
                "message": exc.detail,
                "status_code": exc.status_code,
            },
        },
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(_: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=422,
        content={
            "ok": False,
            "status": "error",
            "detail": "Validation error",
            "error": {
                "type": "validation_error",
                "message": "Request validation failed",
                "status_code": 422,
                "issues": exc.errors(),
            },
        },
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)