import os
import re
from pathlib import Path

from langchain_community.document_loaders import PyPDFLoader
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_chroma import Chroma
from langchain_text_splitters import RecursiveCharacterTextSplitter

MANUALS_DIR = Path(__file__).resolve().parent.parent / "manuals"
CHROMA_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "chroma_db"
COLLECTION_NAME = "machine_manuals"

_vectorstore: Chroma | None = None


def _machine_name_from_filename(filename: str) -> str:
    base = filename.replace("_Manual.pdf", "").replace(".pdf", "")
    return base.replace("_", " ")


def _load_pdf_documents():
    documents = []
    if not MANUALS_DIR.exists():
        MANUALS_DIR.mkdir(parents=True, exist_ok=True)
        return documents

    for pdf_path in sorted(MANUALS_DIR.glob("*.pdf")):
        loader = PyPDFLoader(str(pdf_path))
        pages = loader.load()
        machine_name = _machine_name_from_filename(pdf_path.name)
        for page in pages:
            page.metadata["machine_name"] = machine_name
            page.metadata["source_file"] = pdf_path.name
        documents.extend(pages)
    return documents


def build_vectorstore(force_rebuild: bool = False) -> Chroma:
    global _vectorstore

    embeddings = HuggingFaceEmbeddings(
        model_name="sentence-transformers/all-MiniLM-L6-v2",
        model_kwargs={"device": "cpu"},
    )

    if not force_rebuild and CHROMA_DIR.exists() and any(CHROMA_DIR.iterdir()):
        _vectorstore = Chroma(
            collection_name=COLLECTION_NAME,
            embedding_function=embeddings,
            persist_directory=str(CHROMA_DIR),
        )
        return _vectorstore

    documents = _load_pdf_documents()
    if not documents:
        raise FileNotFoundError(
            f"No PDF manuals found in {MANUALS_DIR}. Run: python scripts/generate_manuals.py"
        )

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=800,
        chunk_overlap=120,
        separators=["\n\n", "\n", ". ", " ", ""],
    )
    chunks = splitter.split_documents(documents)

    if CHROMA_DIR.exists():
        import shutil
        shutil.rmtree(CHROMA_DIR, ignore_errors=True)
    CHROMA_DIR.mkdir(parents=True, exist_ok=True)

    _vectorstore = Chroma.from_documents(
        documents=chunks,
        embedding=embeddings,
        collection_name=COLLECTION_NAME,
        persist_directory=str(CHROMA_DIR),
    )
    return _vectorstore


def get_vectorstore() -> Chroma:
    global _vectorstore
    if _vectorstore is None:
        build_vectorstore(force_rebuild=False)
    return _vectorstore


def search_manuals(query: str, machine_name: str | None = None, top_k: int = 6) -> list[dict]:
    store = get_vectorstore()
    search_query = f"{machine_name}: {query}" if machine_name else query
    results = store.similarity_search(search_query, k=top_k)

    if machine_name:
        needle = machine_name.lower().replace(" ", "").replace("-", "")
        filtered = [
            r for r in results
            if needle in r.metadata.get("machine_name", "").lower().replace(" ", "").replace("-", "")
            or needle in r.metadata.get("source_file", "").lower().replace("_", "").replace("-", "")
        ]
        if filtered:
            results = filtered[:top_k]

    output = []
    for doc in results:
        output.append({
            "machine_name": doc.metadata.get("machine_name", "Unknown"),
            "source_file": doc.metadata.get("source_file", ""),
            "content": doc.page_content.strip(),
        })
    return output


def format_manual_context(results: list[dict]) -> str:
    if not results:
        return "No relevant manual sections found for this query."
    parts = []
    for i, r in enumerate(results, 1):
        parts.append(
            f"[Excerpt {i} | Machine: {r['machine_name']} | Source: {r['source_file']}]\n{r['content']}"
        )
    return "\n\n---\n\n".join(parts)
