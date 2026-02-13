import os
import shutil
import json
from typing import Any

from fastapi import FastAPI, UploadFile, File, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from rag_engine import MultiModalRAG

# Initialize FastAPI
app = FastAPI(title="Python 3.10 Multi-Modal RAG")

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

class QueryResponse(BaseModel):
    answer: str
    images: list[str] = []

# --- Routes ---

@app.get("/")
def home():
    return {"status": "Online", "python_version": "3.10 Compatible"}

@app.post("/upload")
async def upload_pdf(file: UploadFile = File(...)):
    """Uploads and indexes a PDF."""
    temp_file = f"temp_{file.filename}"
    try:
        # Save upload to disk
        with open(temp_file, "wb+") as buffer:
            shutil.copyfileobj(file.file, buffer)
            
        # Process
        result = rag_engine.process_pdf(temp_file)
        
        # Cleanup
        os.remove(temp_file)
        return result
        
    except Exception as e:
        if os.path.exists(temp_file):
            os.remove(temp_file)
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/query", response_model=QueryResponse)
async def query_rag(request: Request):
    """Ask a question.

    Accepts either:
    - JSON: {"question": "..."}
    - Plain text body: "..."
    """
    try:
        raw = await request.body()
        if not raw:
            raise HTTPException(
                status_code=422,
                detail='Request body required. Send JSON: {"question":"..."} or plain text.',
            )

        content_type = (request.headers.get("content-type") or "").lower()
        question: str

        # If it's JSON, parse it ourselves so malformed JSON returns a clear message.
        if "application/json" in content_type or content_type.endswith("+json"):
            try:
                data: Any = json.loads(raw.decode("utf-8"))
            except json.JSONDecodeError as e:
                raise HTTPException(
                    status_code=400,
                    detail=f'Invalid JSON body ({e.msg} at char {e.pos}). Expected: {{"question":"..."}}',
                )

            if isinstance(data, dict) and "question" in data:
                question = str(data["question"]).strip()
            elif isinstance(data, str):
                # Allow a JSON string body: "my question"
                question = data.strip()
            else:
                raise HTTPException(
                    status_code=422,
                    detail='JSON body must be {"question":"..."} (or a JSON string).',
                )
        else:
            # Treat anything else as plain text.
            question = raw.decode("utf-8", errors="replace").strip()

        if not question:
            raise HTTPException(status_code=422, detail="Question is empty.")

        response = rag_engine.query(question)
        return response
    except Exception as e:
        print(f"Query error: {e}")
        raise HTTPException(status_code=500, detail=f"Query failed: {e}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)