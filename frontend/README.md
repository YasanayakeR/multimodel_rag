# Multi-Modal RAG Frontend (Next.js)

## Setup

From `multimodal/frontend`:

```bash
npm install
cp .env.local.example .env.local
npm run dev
```

Open `http://localhost:3001`.

## Backend

Make sure the FastAPI backend is running on `http://localhost:8000`.

Start it from the repo root:

```bash
./venv/bin/python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000
```



