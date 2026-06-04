"""
vector_store.py
---------------
Lightweight vector store for the Mutual Fund FAQ Assistant.
Uses NumPy for cosine similarity search and JSON for persistence.

This replaces ChromaDB, which crashes on Python 3.14 Windows due to
Rust backend binary incompatibilities (access violation in chromadb_rust_bindings).

Features:
- Cosine similarity search with metadata filtering
- JSON + .npy persistence (survives restarts)
- Drop-and-reinsert re-indexing for the daily scheduler
- Zero compiled binary dependencies (pure Python + NumPy)
"""

import json
import logging
import os
import sys
from pathlib import Path

import numpy as np
from dotenv import load_dotenv

logger = logging.getLogger("vector_store")

# ── Configuration ───────────────────────────────────────────────────────────
COLLECTION_NAME: str = "hdfc_mutual_fund_docs"
DEFAULT_PERSIST_DIR: str = "./vector_db"


def _get_persist_dir() -> str:
    """Load the vector store persistence directory from .env or use the default."""
    load_dotenv()
    persist_dir = os.getenv("CHROMA_PERSIST_DIR", DEFAULT_PERSIST_DIR)
    # Ensure the directory exists
    Path(persist_dir).mkdir(parents=True, exist_ok=True)
    return persist_dir


class VectorCollection:
    """
    A lightweight in-memory vector collection with JSON + NumPy persistence.

    Stores documents, metadata, and their embeddings. Supports cosine similarity
    search with optional metadata filtering.
    """

    def __init__(self, name: str, persist_dir: str):
        self.name = name
        self.persist_dir = persist_dir

        # In-memory storage
        self._ids: list[str] = []
        self._documents: list[str] = []
        self._metadatas: list[dict] = []
        self._embeddings: np.ndarray | None = None  # shape: (n, dim)

        # File paths for persistence
        self._meta_path = os.path.join(persist_dir, f"{name}_meta.json")
        self._embeddings_path = os.path.join(persist_dir, f"{name}_embeddings.npy")

        # Load from disk if available
        self._load()

    def _load(self) -> None:
        """Load collection data from disk if files exist."""
        if os.path.exists(self._meta_path) and os.path.exists(self._embeddings_path):
            try:
                with open(self._meta_path, "r", encoding="utf-8") as f:
                    meta = json.load(f)
                self._ids = meta["ids"]
                self._documents = meta["documents"]
                self._metadatas = meta["metadatas"]
                self._embeddings = np.load(self._embeddings_path)
                logger.info(
                    f"Loaded collection '{self.name}' from disk: "
                    f"{len(self._ids)} documents."
                )
            except Exception as e:
                logger.warning(f"Failed to load collection from disk: {e}. Starting fresh.")
                self._clear_memory()
        else:
            logger.info(f"No existing data found for collection '{self.name}'. Starting fresh.")

    def _save(self) -> None:
        """Persist collection data to disk."""
        meta = {
            "ids": self._ids,
            "documents": self._documents,
            "metadatas": self._metadatas,
        }
        with open(self._meta_path, "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False)

        if self._embeddings is not None:
            np.save(self._embeddings_path, self._embeddings)

        logger.info(f"Saved collection '{self.name}' to disk: {len(self._ids)} documents.")

    def _clear_memory(self) -> None:
        """Reset in-memory storage."""
        self._ids = []
        self._documents = []
        self._metadatas = []
        self._embeddings = None

    def count(self) -> int:
        """Return the number of documents in the collection."""
        return len(self._ids)

    def add(
        self,
        ids: list[str],
        documents: list[str],
        metadatas: list[dict],
        embeddings: list[list[float]],
    ) -> None:
        """
        Add documents with their embeddings and metadata to the collection.

        Args:
            ids: Unique identifiers for each document.
            documents: Text content of each document.
            metadatas: Metadata dictionaries for each document.
            embeddings: Embedding vectors for each document.
        """
        if not (len(ids) == len(documents) == len(metadatas) == len(embeddings)):
            raise ValueError("All input lists must have the same length.")

        new_embeddings = np.array(embeddings, dtype=np.float32)

        self._ids.extend(ids)
        self._documents.extend(documents)
        self._metadatas.extend(metadatas)

        if self._embeddings is None:
            self._embeddings = new_embeddings
        else:
            self._embeddings = np.vstack([self._embeddings, new_embeddings])

        # Auto-save after adding
        self._save()

    def query(
        self,
        query_embeddings: list[list[float]],
        n_results: int = 10,
        where: dict | None = None,
        include: list[str] | None = None,
    ) -> dict:
        """
        Query the collection using cosine similarity.

        Args:
            query_embeddings: List of query embedding vectors (typically one).
            n_results: Number of top results to return.
            where: Optional metadata filter dict (e.g., {"scheme_name": "..."}).
            include: List of fields to include in results.

        Returns:
            Dict with 'ids', 'documents', 'metadatas', 'distances' (each a list of lists).
        """
        if include is None:
            include = ["documents", "metadatas", "distances"]

        if self._embeddings is None or len(self._ids) == 0:
            return {
                "ids": [[]],
                "documents": [[]],
                "metadatas": [[]],
                "distances": [[]],
            }

        # Apply metadata filter to get candidate indices
        if where:
            candidate_indices = []
            for i, meta in enumerate(self._metadatas):
                match = all(meta.get(k) == v for k, v in where.items())
                if match:
                    candidate_indices.append(i)
            candidate_indices = np.array(candidate_indices, dtype=int)
        else:
            candidate_indices = np.arange(len(self._ids))

        if len(candidate_indices) == 0:
            return {
                "ids": [[]],
                "documents": [[]],
                "metadatas": [[]],
                "distances": [[]],
            }

        # Compute cosine distances for each query
        all_ids = []
        all_docs = []
        all_metas = []
        all_dists = []

        for query_vec in query_embeddings:
            q = np.array(query_vec, dtype=np.float32)
            candidate_embs = self._embeddings[candidate_indices]

            # Cosine similarity = dot(a, b) / (||a|| * ||b||)
            # Cosine distance = 1 - cosine_similarity
            q_norm = np.linalg.norm(q)
            emb_norms = np.linalg.norm(candidate_embs, axis=1)

            # Avoid division by zero
            safe_norms = np.where(emb_norms == 0, 1e-10, emb_norms)
            safe_q_norm = q_norm if q_norm > 0 else 1e-10

            similarities = candidate_embs @ q / (safe_norms * safe_q_norm)
            distances = 1.0 - similarities

            # Get top-n indices (smallest distance = most similar)
            top_n = min(n_results, len(candidate_indices))
            top_indices_in_candidates = np.argsort(distances)[:top_n]
            top_global_indices = candidate_indices[top_indices_in_candidates]

            result_ids = [self._ids[i] for i in top_global_indices]
            result_docs = [self._documents[i] for i in top_global_indices]
            result_metas = [self._metadatas[i] for i in top_global_indices]
            result_dists = distances[top_indices_in_candidates].tolist()

            all_ids.append(result_ids)
            all_docs.append(result_docs)
            all_metas.append(result_metas)
            all_dists.append(result_dists)

        return {
            "ids": all_ids,
            "documents": all_docs,
            "metadatas": all_metas,
            "distances": all_dists,
        }

    def delete_all(self) -> None:
        """Remove all documents from the collection and delete persisted files."""
        self._clear_memory()
        # Remove files from disk
        for path in [self._meta_path, self._embeddings_path]:
            if os.path.exists(path):
                os.remove(path)
        logger.info(f"Cleared all data from collection '{self.name}'.")


# ═══════════════════════════════════════════════════════════════════════════
# Public API (matches the interface expected by the rest of the pipeline)
# ═══════════════════════════════════════════════════════════════════════════

# Module-level client cache
_client_cache: dict[str, VectorCollection] = {}


def get_or_create_collection() -> VectorCollection:
    """
    Get or create the main document collection.

    Returns a cached collection instance to avoid reloading from disk on every call.
    """
    if COLLECTION_NAME not in _client_cache:
        persist_dir = _get_persist_dir()
        _client_cache[COLLECTION_NAME] = VectorCollection(COLLECTION_NAME, persist_dir)
    return _client_cache[COLLECTION_NAME]


def clear_collection() -> None:
    """
    Delete all data from the collection.

    Used during daily re-indexing to ensure a clean slate.
    """
    collection = get_or_create_collection()
    collection.delete_all()
    # Clear the cache so the next get_or_create starts fresh
    _client_cache.pop(COLLECTION_NAME, None)
    logger.info(f"Collection '{COLLECTION_NAME}' cleared for re-indexing.")


def index_chunks(
    chunks: list[dict],
    embeddings: list[list[float]],
) -> int:
    """
    Insert chunks with their precomputed embeddings into the vector store.

    Args:
        chunks: List of chunk dicts from chunker.py, each with 'page_content' and 'metadata'.
        embeddings: List of embedding vectors, one per chunk (same order as chunks).

    Returns:
        Number of documents successfully indexed.
    """
    if len(chunks) != len(embeddings):
        raise ValueError(
            f"Mismatch: {len(chunks)} chunks but {len(embeddings)} embeddings."
        )

    if not chunks:
        logger.warning("No chunks to index.")
        return 0

    collection = get_or_create_collection()

    ids = []
    documents = []
    metadatas = []

    for i, chunk in enumerate(chunks):
        meta = chunk["metadata"]
        chunk_id = f"{meta.get('source_url', 'unknown')}::chunk_{meta.get('chunk_index', i)}"
        ids.append(chunk_id)
        documents.append(chunk["page_content"])

        # Ensure all metadata values are JSON-serializable primitives
        clean_meta = {}
        for key, value in meta.items():
            if value is None:
                clean_meta[key] = "N/A"
            elif isinstance(value, (str, int, float, bool)):
                clean_meta[key] = value
            else:
                clean_meta[key] = str(value)
        metadatas.append(clean_meta)

    collection.add(
        ids=ids,
        documents=documents,
        metadatas=metadatas,
        embeddings=embeddings,
    )

    logger.info(f"Indexed {len(ids)} chunks. Total in collection: {collection.count()}")
    return len(ids)


def query_collection(
    query_embedding: list[float],
    n_results: int = 10,
    where_filter: dict | None = None,
) -> dict:
    """
    Query the collection with a precomputed query embedding.

    Args:
        query_embedding: The embedding vector for the user query.
        n_results: Number of results to return (default 10).
        where_filter: Optional metadata filter dict (e.g., {"scheme_name": "..."}).

    Returns:
        Dict with 'ids', 'documents', 'metadatas', 'distances' (each a list of lists).
    """
    collection = get_or_create_collection()

    results = collection.query(
        query_embeddings=[query_embedding],
        n_results=n_results,
        where=where_filter,
        include=["documents", "metadatas", "distances"],
    )

    logger.info(f"Query returned {len(results.get('ids', [[]])[0])} results.")
    return results


def run_full_indexing(chunks: list[dict]) -> int:
    """
    End-to-end indexing pipeline: embed all chunks and store them.

    This is the main entry point called by the daily scheduler and manual refresh.
    It performs a drop-and-reinsert to ensure fresh data.

    Args:
        chunks: List of chunk dicts from chunker.py.

    Returns:
        Number of documents indexed.
    """
    # Import here to avoid circular imports
    from embeddings.embedder import embed_texts  # noqa: PLC0415

    logger.info(f"Starting full indexing pipeline for {len(chunks)} chunks ...")

    # Step 1: Generate embeddings
    texts = [chunk["page_content"] for chunk in chunks]
    logger.info("Generating embeddings via Gemini API ...")
    embeddings = embed_texts(texts, task_type="RETRIEVAL_DOCUMENT")

    # Step 2: Clear existing data
    clear_collection()

    # Step 3: Index all chunks with their embeddings
    indexed = index_chunks(chunks, embeddings)

    logger.info(f"Full indexing complete. {indexed} documents indexed.")
    return indexed


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding='utf-8')
    logging.basicConfig(level=logging.INFO, format="%(name)s | %(levelname)s | %(message)s")

    # Load chunked data
    chunked_file = Path("data/chunked_text.json")
    if not chunked_file.exists():
        print(f"[-] Chunked data file {chunked_file} not found. Run chunker.py first.")
    else:
        with open(chunked_file, "r", encoding="utf-8") as f:
            chunks = json.load(f)

        print(f"[*] Loaded {len(chunks)} chunks from {chunked_file}")
        print("[*] Running full indexing pipeline ...")

        try:
            count = run_full_indexing(chunks)
            print(f"[+] Successfully indexed {count} documents into the vector store.")

            # Quick verification: query the collection
            from embeddings.embedder import embed_query
            collection = get_or_create_collection()

            test_query = "What is the expense ratio of HDFC Mid Cap Fund?"
            print(f"\n[*] Test query: \"{test_query}\"")
            query_vec = embed_query(test_query)
            results = query_collection(query_vec, n_results=3)

            for i, (doc, meta, dist) in enumerate(zip(
                results["documents"][0],
                results["metadatas"][0],
                results["distances"][0],
            )):
                print(f"\n  Result {i + 1} (distance: {dist:.4f}):")
                print(f"    Scheme: {meta.get('scheme_name', 'N/A')}")
                print(f"    Source: {meta.get('source_url', 'N/A')}")
                print(f"    Preview: {doc[:150]}...")

        except ValueError as e:
            print(f"[-] Configuration error: {e}")
        except RuntimeError as e:
            print(f"[-] API error: {e}")
