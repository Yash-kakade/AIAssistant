import json
import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from pydantic import BaseModel, Field
from langchain_core.messages import AIMessage, HumanMessage
from fastapi.responses import StreamingResponse

from .seed import init_db
from .api.routes import router as api_router
from .graph.workflow import create_workflow
from .rag.pipeline import build_vectorstore
from .assistant_actions import try_direct_erp_action

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    try:
        build_vectorstore(force_rebuild=False)
        logger.info("RAG vector store ready")
    except FileNotFoundError as e:
        logger.warning("RAG index not built: %s", e)
    except Exception as e:
        logger.warning("RAG init failed (will retry on first manual search): %s", e)
    yield


app = FastAPI(title="Factory ERP AI Assistant", lifespan=lifespan)

class NoCacheMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        if request.url.path.startswith("/api"):
            response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
        return response


app.add_middleware(NoCacheMiddleware)
# Compress JSON responses ≥ 500 bytes — typically 60-80% smaller for
# list endpoints (orders, employees, inventory movements, etc.).
# GZipMiddleware skips StreamingResponse automatically, so SSE is unaffected.
app.add_middleware(GZipMiddleware, minimum_size=500)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router)
workflow = create_workflow()

MUTATION_TOOLS = {
    "add_order_line_item",
    "place_product_order",
    "replenish_stock",
    "update_inventory_record",
    "create_supplier_purchase_order",
    "receive_supplier_purchase_order",
    "remove_order_line_item",
    "remove_order",
    "update_order_status",
    "add_employee_record",
    "update_employee_salary",
    "remove_employee_record",
}


def _mutation_applied(output) -> bool:
    """True when a tool wrote to the ERP database."""
    s = str(output).lower()
    if '"success": false' in s or "'success': false" in s:
        return False
    if '"erp_updated": true' in s or "'erp_updated': true" in s:
        return True
    if '"success": true' not in s and "'success': true" not in s:
        return False
    markers = (
        "order_name", "new_order_total", "deleted_order", "new_salary",
        "removed_employee", "new_stock_qty", "quantity_added", "created_order",
        "inventory_updated",
    )
    return any(m in s for m in markers)


class ChatRequest(BaseModel):
    message: str
    history: list[dict[str, str]] = Field(default_factory=list)
    current_page: str = "unknown"
    user_role: str = "user"
    hover_context: str = "none"


@app.get("/")
def read_root():
    return {"status": "ERP assistant backend running", "docs": "/docs"}


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/chat/stream")
async def chat_stream(req: ChatRequest):
    async def event_generator():
        direct_action = try_direct_erp_action(req.message, req.history)
        if direct_action.handled:
            if direct_action.erp_changed:
                yield f"data: {json.dumps({'erp_refresh': True, 'instant': True})}\n\n"
            yield f"data: {json.dumps({'content': direct_action.content})}\n\n"
            yield f"data: {json.dumps({'erp_refresh': direct_action.erp_changed})}\n\n"
            yield "data: [DONE]\n\n"
            return

        history_messages = []
        for item in req.history[-12:]:
            role = item.get("role")
            content = (item.get("content") or "").strip()
            if not content:
                continue
            if role == "user":
                history_messages.append(HumanMessage(content=content))
            elif role == "assistant":
                history_messages.append(AIMessage(content=content))
        state = {
            "messages": history_messages + [HumanMessage(content=req.message)],
            "current_page": req.current_page,
            "user_role": req.user_role,
            "hover_context": req.hover_context or "none",
        }
        erp_changed = False
        try:
            config = {"recursion_limit": 25}
            async for event in workflow.astream_events(state, version="v2", config=config):
                if event["event"] == "on_chat_model_stream":
                    content = event["data"]["chunk"].content
                    if content:
                        yield f"data: {json.dumps({'content': content})}\n\n"
                        await asyncio.sleep(0)
                elif event["event"] in ("on_tool_end", "on_chain_end"):
                    output = event.get("data", {}).get("output")
                    if _mutation_applied(output):
                        erp_changed = True
                        # Push to browser immediately (Cursor-style instant UI sync)
                        yield f"data: {json.dumps({'erp_refresh': True, 'instant': True})}\n\n"
                        await asyncio.sleep(0)
        except Exception as e:
            logger.exception("Chat stream failed")
            detail = str(e)
            if "failed_generation" in detail or "Failed to call a function" in detail:
                msg = (
                    "The AI model returned an invalid tool call, so I did not write anything "
                    "to the ERP. Try the command with a product SKU and quantity, for example: "
                    "'add 5 units to PRD-006'."
                )
            else:
                msg = f"Assistant error: {e}. Check backend/.env and restart the server."
            yield f"data: {json.dumps({'content': msg})}\n\n"

        yield f"data: {json.dumps({'erp_refresh': erp_changed})}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@app.post("/api/rag/reindex")
def reindex_manuals():
    build_vectorstore(force_rebuild=True)
    return {"status": "ok", "message": "Manual index rebuilt"}
