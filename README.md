# Multi-Modal RAG Chatbot (FastAPI + Next.js)

This project is a **multi-modal RAG** app where you can **upload PDFs** and chat with **session memory**, user authentication, and document storage.

### Tech stack
- **Backend**: FastAPI (Python **3.10**), LangChain, Chroma, MongoDB 
- **Frontend**: 

### Default ports (
- **Backend API**: `http://localhost:8000`
- **Frontend UI**: `http://localhost:3001`

## Backend (FastAPI) — Python 3.10

### 1) Create/activate venv (Python 3.10)

From repo root:

```bash
python3.10 -m venv venv
./venv/bin/python -m pip install -r backend/requirements.txt
```

### 2) Environment variables

Backend loads `.env` from `backend/.env` 

Minimum recommended env vars:

- **LLM (Gemini)**:
  - `GOOGLE_API_KEY` *(or `GEMINI_API_KEY`)*
- **Embeddings (OpenAI)**:
  - `OPENAI_API_KEY`
- **MongoDB** (recommended for persistence):
  - `MONGODB_URI` (example: `mongodb://localhost:27017`)
  - `MONGODB_DB` (default: `multimodal`)
- **JWT auth**:
  - `JWT_SECRET_KEY`
  - `JWT_EXPIRE_MINUTES` (optional)
  - `ADMIN_EMAIL` *(this email auto-creates as admin + active on signup)*
- **CORS** (optional):
  - `CORS_ALLOW_ORIGINS` (comma-separated). If unset, allows `http://localhost:3000` and `http://localhost:3001`.

### 3) Run backend

From repo root:

```bash
./venv/bin/python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload
```

Open Swagger UI:
- `http://localhost:8000/docs`

## Frontend (Next.js)

### 1) Install dependencies

```bash
cd frontend
npm install
```

### 2) Configure API base URL

Set `NEXT_PUBLIC_API_BASE_URL` in `frontend/.env.local` (example):

```bash
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
```

### 3) Run frontend (port 3001)

```bash
cd frontend
npm run dev
```

Open the UI:
- `http://localhost:3001`

## How the app works

### Authentication
- `POST /auth/signup` creates an account.
  - If signup email matches `ADMIN_EMAIL`, the user becomes **admin + active**.
  - Other users start as **pending** until activated by an admin.
- `POST /auth/login` returns an `access_token` (JWT).
- Most endpoints require `Authorization: Bearer <token>`.

### Chat sessions + memory
- A chat **session** is created via `POST /chat/sessions`.
- Asking questions via `POST /query` uses the `session_id` to load recent messages for memory.

### Uploading PDFs (session-linked)
- Upload is `POST /upload` with **multipart/form-data**:
  - `file`: the PDF
  - `session_id`: the chat session to link the upload to
- Document bytes are stored in **MongoDB GridFS** (when Mongo is configured).
- The UI shows documents uploaded to the current session and supports **download** and **delete**.




