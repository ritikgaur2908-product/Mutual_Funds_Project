"""
embedder.py
-----------
Embedding model wrapper using the Gemini Embedding API (models/text-embedding-004).
Generates 768-dimensional dense vector embeddings for text chunks.

Features:
- Batch embedding with configurable batch size
- Exponential backoff retry on API failures
- Python 3.14 protobuf compatibility workaround
"""

import logging
import os
import sys
import time

# ── Python 3.14 protobuf compatibility workaround ──────────────────────────
# The compiled protobuf C-extension (google._upb._message) crashes on Python 3.14
# with "TypeError: Metaclasses with custom tp_new are not supported."
# Blocking the import forces protobuf to fall back to its pure-Python implementation.
sys.modules['google._upb._message'] = None

import google.generativeai as genai  # noqa: E402
from dotenv import load_dotenv  # noqa: E402

logger = logging.getLogger("embedder")

# ── Configuration ───────────────────────────────────────────────────────────
EMBEDDING_MODEL: str = "models/text-embedding-004"
EMBEDDING_DIMENSIONS: int = 768
BATCH_SIZE: int = 100  # Gemini API supports up to 100 texts per batch request
MAX_RETRIES: int = 3
INITIAL_BACKOFF_SECONDS: float = 1.0


def _is_mock_mode() -> bool:
    """Check if the embedder should run in mock mode (explicitly requested)."""
    load_dotenv()
    return os.getenv("MOCK_EMBEDDINGS", "").lower() == "true"


def _configure_api() -> None:
    """Load the Gemini API key from .env and configure the SDK."""
    if _is_mock_mode():
        logger.warning(
            "MOCK_EMBEDDINGS is enabled. RUNNING IN MOCK EMBEDDING MODE. "
            "Factual queries will use pseudo-random mock vectors."
        )
        return
    load_dotenv()
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key or api_key == "your_gemini_api_key_here":
        raise ValueError(
            "GEMINI_API_KEY is not configured. "
            "Set it in your .env file. Get one at: https://aistudio.google.com/app/apikey"
        )
    genai.configure(api_key=api_key)
    logger.info("Gemini API configured successfully.")


def embed_texts(texts: list[str], task_type: str = "RETRIEVAL_DOCUMENT") -> list[list[float]]:
    """
    Generate embeddings for a list of texts using the Gemini Embedding API.

    Args:
        texts: List of text strings to embed.
        task_type: The task type hint for the embedding model.
                   Use "RETRIEVAL_DOCUMENT" for indexing chunks,
                   and "RETRIEVAL_QUERY" for embedding user queries.

    Returns:
        List of embedding vectors (each a list of floats with EMBEDDING_DIMENSIONS elements).

    Raises:
        ValueError: If the API key is not configured and mock mode is off.
        RuntimeError: If all retry attempts are exhausted.
    """
    _configure_api()

    if not texts:
        return []

    all_embeddings: list[list[float]] = []

    # Process in batches
    for batch_start in range(0, len(texts), BATCH_SIZE):
        batch_end = min(batch_start + BATCH_SIZE, len(texts))
        batch = texts[batch_start:batch_end]

        batch_embeddings = _embed_batch_with_retry(batch, task_type)
        all_embeddings.extend(batch_embeddings)

        logger.info(
            f"Embedded batch {batch_start // BATCH_SIZE + 1} "
            f"({batch_start + 1}-{batch_end} of {len(texts)} texts)."
        )

    return all_embeddings


def embed_query(query: str) -> list[float]:
    """
    Generate an embedding for a single user query.

    Uses task_type="RETRIEVAL_QUERY" to optimize the embedding for search queries.

    Args:
        query: The user query string.

    Returns:
        A single embedding vector (list of floats).
    """
    result = embed_texts([query], task_type="RETRIEVAL_QUERY")
    return result[0]


def _embed_batch_with_retry(batch: list[str], task_type: str) -> list[list[float]]:
    """
    Embed a single batch of texts with exponential backoff retry.

    Args:
        batch: List of text strings (max BATCH_SIZE).
        task_type: The task type hint.

    Returns:
        List of embedding vectors for the batch.

    Raises:
        RuntimeError: If all retry attempts fail.
    """
    if _is_mock_mode():
        import hashlib
        embeddings = []
        for text in batch:
            h = hashlib.sha256(text.encode("utf-8")).digest()
            vec = []
            for i in range(EMBEDDING_DIMENSIONS):
                byte_idx = (i * 7) % len(h)
                vec.append(float(h[byte_idx]) / 127.5 - 1.0)
            embeddings.append(vec)
        return embeddings

    backoff = INITIAL_BACKOFF_SECONDS

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            result = genai.embed_content(
                model=EMBEDDING_MODEL,
                content=batch,
                task_type=task_type,
            )
            embeddings = result["embedding"]

            # Validate dimensions
            for i, emb in enumerate(embeddings):
                if len(emb) != EMBEDDING_DIMENSIONS:
                    logger.warning(
                        f"Unexpected embedding dimension {len(emb)} "
                        f"(expected {EMBEDDING_DIMENSIONS}) for text index {i}."
                    )

            return embeddings

        except Exception as e:
            logger.warning(
                f"Embedding attempt {attempt}/{MAX_RETRIES} failed: {e}"
            )
            if attempt < MAX_RETRIES:
                logger.info(f"Retrying in {backoff:.1f}s ...")
                time.sleep(backoff)
                backoff *= 2  # Exponential backoff
            else:
                raise RuntimeError(
                    f"Failed to embed batch after {MAX_RETRIES} attempts. Last error: {e}"
                ) from e

    # Should never reach here, but satisfy type checker
    return []


if __name__ == "__main__":
    # Quick smoke test: embed a single sentence and print the vector shape
    sys.stdout.reconfigure(encoding='utf-8')

    logging.basicConfig(level=logging.INFO, format="%(name)s | %(levelname)s | %(message)s")

    test_texts = [
        "What is the expense ratio of HDFC Mid Cap Fund?",
        "HDFC Small Cap Fund has an exit load of 1% if redeemed within 1 year.",
    ]

    print(f"[*] Embedding {len(test_texts)} test texts using {EMBEDDING_MODEL} ...")
    try:
        vectors = embed_texts(test_texts)
        for i, vec in enumerate(vectors):
            print(f"  Text {i + 1}: {len(vec)} dimensions, first 5 values: {vec[:5]}")
        print("[+] Embedder smoke test passed.")
    except ValueError as e:
        print(f"[-] Configuration error: {e}")
    except RuntimeError as e:
        print(f"[-] API error: {e}")
