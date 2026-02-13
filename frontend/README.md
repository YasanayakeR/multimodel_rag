# Multi-Modal RAG Frontend (Next.js)

## Setup

From `multimodal/frontend`:

```bash
npm install
cp .env.local.example .env.local
npm run dev
```

Open `http://localhost:3000`.

## Backend

Make sure the FastAPI backend is running on `http://localhost:8000`.

The frontend calls:
- `POST /upload` (multipart form-data with `file`)
- `POST /query` (JSON: `{"question":"..."}`)

