import os
import ssl
import httpx
from langchain_groq import ChatGroq
from dotenv import load_dotenv

load_dotenv()

# Module-level singletons — created once, reused for every request.
# Building httpx clients (especially with SSL context) is expensive; doing it
# inside get_llm() on every LLM call was adding ~100-300ms of overhead.
_sync_client: httpx.Client | None = None
_async_client: httpx.AsyncClient | None = None
_llm_instance: ChatGroq | None = None


def _get_httpx_clients() -> tuple[httpx.Client, httpx.AsyncClient]:
    global _sync_client, _async_client
    if _sync_client is None or _async_client is None:
        try:
            ctx = ssl.create_default_context()
            ctx.load_default_certs()
            _sync_client = httpx.Client(verify=ctx)
            _async_client = httpx.AsyncClient(verify=ctx)
        except Exception:
            _sync_client = httpx.Client(verify=False)
            _async_client = httpx.AsyncClient(verify=False)
    return _sync_client, _async_client


def get_llm() -> ChatGroq:
    global _llm_instance
    if _llm_instance is not None:
        return _llm_instance

    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise ValueError("GROQ_API_KEY environment variable is not set. Please set it in .env")

    sync_client, async_client = _get_httpx_clients()

    _llm_instance = ChatGroq(
        api_key=api_key,
        model_name="llama-3.1-8b-instant",
        temperature=0.2,
        streaming=True,
        http_client=sync_client,
        http_async_client=async_client,
    )
    return _llm_instance
