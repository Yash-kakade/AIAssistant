# Factory ERP + AI Assistant

A dynamic ERP demo with SQLite, REST APIs, Next.js dashboard, and an integrated AI assistant powered by **Groq (Llama 3.1)** and **LangGraph**. Machine operation manuals are indexed with a **RAG** pipeline (Chroma + embeddings) so the assistant can answer manual questions accurately.

## Features

- **ERP entities**: clients, products, orders, order items, machines, suppliers, purchase orders, invoices, employees, departments, maintenance logs, inventory movements
- **REST API** at `/api/*` — dashboard KPIs and entity listings
- **AI chat** at `/chat/stream` — SSE streaming with tool use (SQL) + RAG (PDF manuals)
- **Machine manuals** — PDFs in `backend/app/manuals/`, indexed into Chroma on startup

## Quick start

### 1. Backend

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate          # Windows
pip install -r requirements.txt
copy .env.example .env          # add your GROQ_API_KEY
python scripts/generate_manuals.py
uvicorn app.main:app --reload --port 8000
```

First startup creates `erp.db`, seeds demo data, and builds the RAG index.
The `all-MiniLM-L6-v2` embedding model (~90 MB) is downloaded from HuggingFace on first run.

### 2. Frontend

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:3000

### Rebuild manual index

```bash
curl -X POST http://localhost:8000/api/rag/reindex
```

## Example AI questions

- "How many orders are pending?"
- "Show orders for Acme Corp"
- **"Add 3 Bearing Set 6205 to order 1006"** *(writes to database)*
- "Which products are low on stock?"
- "What is the startup procedure for CNC Alpha-1?" *(uses RAG manual)*

**Important:** The chat assistant requires the **backend** to be running. If you see "Backend offline", start uvicorn on port 8000 before using the chat.

## Project layout

```
backend/
  app/
    api/routes.py      # REST endpoints
    graph/             # LangGraph agent + tools
    rag/pipeline.py    # PDF → Chroma RAG
    manuals/           # Machine PDF manuals
    models.py          # SQLAlchemy entities
frontend/
  app/                 # ERP pages (dashboard, orders, machines, …)
  components/Chat.tsx  # Floating AI assistant
```
