"""
ChromaDB vector store helpers.
Used by tools.py for semantic product search and RAG over the knowledge base.
"""
from pathlib import Path

CHROMA_PATH = Path(__file__).parent.parent / "chroma_db"
COLLECTION_NAME = "spicenutrition_products"

_client = None
_collection = None


def get_client():
    global _client
    if _client is None:
        import chromadb
        _client = chromadb.PersistentClient(path=str(CHROMA_PATH))
    return _client


def get_collection():
    global _collection
    if _collection is None:
        _collection = get_client().get_or_create_collection(COLLECTION_NAME)
    return _collection


def semantic_search(query: str, n: int = 5, category_filter: str = None) -> list[dict]:
    """Return top-n semantically similar documents with metadata."""
    col = get_collection()
    where = {}
    if category_filter:
        where["category"] = {"$eq": category_filter}

    kwargs = {"query_texts": [query], "n_results": min(n, col.count() or 1)}
    if where:
        kwargs["where"] = where

    res = col.query(**kwargs)
    results = []
    for doc, meta in zip(res["documents"][0], res["metadatas"][0]):
        results.append({"document": doc, "metadata": meta})
    return results


def upsert_document(doc_id: str, text: str, metadata: dict):
    col = get_collection()
    col.upsert(documents=[text], metadatas=[metadata], ids=[doc_id])


def collection_count() -> int:
    try:
        return get_collection().count()
    except Exception:
        return 0
