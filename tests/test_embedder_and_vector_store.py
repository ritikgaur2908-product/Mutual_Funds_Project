"""
test_embedder_and_vector_store.py
---------------------------------
Unit tests for embeddings/embedder.py and embeddings/vector_store.py.
All Gemini API calls are mocked — no real API key or network access required.
Vector store tests use temporary directories for isolation.
"""

import os
import shutil
import sys
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest

# ── Python 3.14 protobuf compatibility workaround ──────────────────────────
sys.modules['google._upb._message'] = None

from embeddings.embedder import (  # noqa: E402
    BATCH_SIZE,
    EMBEDDING_DIMENSIONS,
    _embed_batch_with_retry,
    embed_query,
    embed_texts,
)
from embeddings.vector_store import (  # noqa: E402
    COLLECTION_NAME,
    VectorCollection,
    _client_cache,
    clear_collection,
    get_or_create_collection,
    index_chunks,
    query_collection,
)


# ═══════════════════════════════════════════════════════════════════════════
# Embedder Tests
# ═══════════════════════════════════════════════════════════════════════════

@pytest.fixture(autouse=True)
def disable_mock_embeddings():
    """Force MOCK_EMBEDDINGS to false to test true API integration code paths."""
    old_val = os.environ.get("MOCK_EMBEDDINGS")
    os.environ["MOCK_EMBEDDINGS"] = "false"
    yield
    if old_val is not None:
        os.environ["MOCK_EMBEDDINGS"] = old_val
    else:
        os.environ.pop("MOCK_EMBEDDINGS", None)



def _mock_embedding(n: int = 1) -> list[list[float]]:
    """Generate a list of fake embedding vectors."""
    return [[0.1] * EMBEDDING_DIMENSIONS for _ in range(n)]


@patch("embeddings.embedder.genai")
@patch("embeddings.embedder.load_dotenv")
def test_embed_texts_single_batch(mock_dotenv, mock_genai):
    """Test embedding a small batch of texts (fits in one API call)."""
    os.environ["GEMINI_API_KEY"] = "test-key-123"

    mock_genai.embed_content.return_value = {"embedding": _mock_embedding(3)}

    texts = ["text 1", "text 2", "text 3"]
    result = embed_texts(texts)

    assert len(result) == 3
    assert len(result[0]) == EMBEDDING_DIMENSIONS
    mock_genai.embed_content.assert_called_once()


@patch("embeddings.embedder.genai")
@patch("embeddings.embedder.load_dotenv")
def test_embed_texts_empty_list(mock_dotenv, mock_genai):
    """Test embedding an empty list returns an empty list."""
    os.environ["GEMINI_API_KEY"] = "test-key-123"

    result = embed_texts([])
    assert result == []
    mock_genai.embed_content.assert_not_called()


@patch("embeddings.embedder.genai")
@patch("embeddings.embedder.load_dotenv")
def test_embed_texts_multiple_batches(mock_dotenv, mock_genai):
    """Test that large input is split into multiple batches."""
    os.environ["GEMINI_API_KEY"] = "test-key-123"

    num_texts = BATCH_SIZE + 10  # Forces 2 batches

    mock_genai.embed_content.side_effect = [
        {"embedding": _mock_embedding(BATCH_SIZE)},
        {"embedding": _mock_embedding(10)},
    ]

    texts = [f"text {i}" for i in range(num_texts)]
    result = embed_texts(texts)

    assert len(result) == num_texts
    assert mock_genai.embed_content.call_count == 2


@patch("embeddings.embedder.genai")
@patch("embeddings.embedder.load_dotenv")
def test_embed_query(mock_dotenv, mock_genai):
    """Test single query embedding uses RETRIEVAL_QUERY task type."""
    os.environ["GEMINI_API_KEY"] = "test-key-123"

    mock_genai.embed_content.return_value = {"embedding": _mock_embedding(1)}

    result = embed_query("What is the expense ratio?")

    assert len(result) == EMBEDDING_DIMENSIONS
    call_args = mock_genai.embed_content.call_args
    assert call_args.kwargs["task_type"] == "RETRIEVAL_QUERY"


@patch("embeddings.embedder.time.sleep")  # Don't actually sleep in tests
@patch("embeddings.embedder.genai")
@patch("embeddings.embedder.load_dotenv")
def test_embed_batch_retry_on_failure(mock_dotenv, mock_genai, mock_sleep):
    """Test that transient failures trigger retry with exponential backoff."""
    os.environ["GEMINI_API_KEY"] = "test-key-123"

    mock_genai.embed_content.side_effect = [
        Exception("API temporarily unavailable"),
        Exception("Rate limited"),
        {"embedding": _mock_embedding(2)},
    ]

    result = _embed_batch_with_retry(["text1", "text2"], "RETRIEVAL_DOCUMENT")

    assert len(result) == 2
    assert mock_genai.embed_content.call_count == 3
    assert mock_sleep.call_count == 2


@patch("embeddings.embedder.time.sleep")
@patch("embeddings.embedder.genai")
@patch("embeddings.embedder.load_dotenv")
def test_embed_batch_exhausts_retries(mock_dotenv, mock_genai, mock_sleep):
    """Test that RuntimeError is raised after all retries are exhausted."""
    os.environ["GEMINI_API_KEY"] = "test-key-123"

    mock_genai.embed_content.side_effect = Exception("Persistent failure")

    with pytest.raises(RuntimeError, match="Failed to embed batch"):
        _embed_batch_with_retry(["text1"], "RETRIEVAL_DOCUMENT")


@patch("embeddings.embedder.load_dotenv")
def test_embed_texts_missing_api_key(mock_dotenv):
    """Test that missing API key raises ValueError."""
    os.environ["GEMINI_API_KEY"] = "your_gemini_api_key_here"

    with pytest.raises(ValueError, match="GEMINI_API_KEY is not configured"):
        embed_texts(["test"])


# ═══════════════════════════════════════════════════════════════════════════
# Vector Store Tests
# ═══════════════════════════════════════════════════════════════════════════


@pytest.fixture(autouse=True)
def isolate_vector_store(tmp_path):
    """
    Ensure each test uses its own temporary directory and a fresh collection.
    Clears the module-level cache before and after each test.
    """
    persist_dir = str(tmp_path / "test_vector_db")
    os.makedirs(persist_dir, exist_ok=True)
    os.environ["CHROMA_PERSIST_DIR"] = persist_dir

    # Clear the module-level client cache
    _client_cache.clear()

    yield persist_dir

    # Cleanup
    _client_cache.clear()
    if os.path.exists(persist_dir):
        shutil.rmtree(persist_dir, ignore_errors=True)


def _make_chunks(n: int) -> list[dict]:
    """Create n sample chunks mimicking chunker.py output."""
    return [
        {
            "page_content": f"Document: Test Fund {i}\n---\nThis is chunk {i} content about mutual funds.",
            "metadata": {
                "source_url": f"https://groww.in/mutual-funds/test-fund-{i}",
                "scheme_name": f"Test Fund {i}",
                "last_updated": "2026-06-04T00:00:00Z",
                "chunk_index": i,
                "expense_ratio": f"0.{i}%",
                "exit_load": "1% within 1 year",
                "minimum_sip": "100",
                "minimum_lumpsum": "500",
                "risk_rating": "High Risk",
                "benchmark": "NIFTY 50",
                "aum": "1000 Cr",
                "nav": "150.00",
            },
        }
        for i in range(n)
    ]


def test_get_or_create_collection():
    """Test creating and retrieving the collection."""
    collection = get_or_create_collection()

    assert collection.name == COLLECTION_NAME
    assert collection.count() == 0


def test_index_chunks():
    """Test indexing chunks into the vector store."""
    chunks = _make_chunks(5)
    embeddings = _mock_embedding(5)

    indexed = index_chunks(chunks, embeddings)

    assert indexed == 5
    collection = get_or_create_collection()
    assert collection.count() == 5


def test_index_chunks_mismatched_lengths():
    """Test that mismatched chunks/embeddings raises ValueError."""
    chunks = _make_chunks(3)
    embeddings = _mock_embedding(2)  # One fewer than chunks

    with pytest.raises(ValueError, match="Mismatch"):
        index_chunks(chunks, embeddings)


def test_index_chunks_empty():
    """Test indexing empty lists returns 0."""
    indexed = index_chunks([], [])
    assert indexed == 0


def test_clear_collection():
    """Test clearing the collection removes all documents."""
    chunks = _make_chunks(3)
    embeddings = _mock_embedding(3)
    index_chunks(chunks, embeddings)

    collection = get_or_create_collection()
    assert collection.count() == 3

    clear_collection()
    collection = get_or_create_collection()
    assert collection.count() == 0


def test_query_collection():
    """Test querying the collection returns ranked results."""
    chunks = _make_chunks(5)
    embeddings = _mock_embedding(5)
    index_chunks(chunks, embeddings)

    query_vec = [0.1] * EMBEDDING_DIMENSIONS
    results = query_collection(query_vec, n_results=3)

    assert "documents" in results
    assert "metadatas" in results
    assert "distances" in results
    assert len(results["documents"][0]) == 3  # Requested 3 results


def test_query_collection_with_filter():
    """Test querying with a metadata filter returns only matching documents."""
    chunks = _make_chunks(5)
    # Give each chunk a distinct embedding so we can differentiate
    embeddings = []
    for i in range(5):
        vec = [0.0] * EMBEDDING_DIMENSIONS
        vec[i] = 1.0  # Each chunk has a unique direction
        embeddings.append(vec)

    index_chunks(chunks, embeddings)

    # Query with a filter for a specific scheme
    query_vec = [0.1] * EMBEDDING_DIMENSIONS
    results = query_collection(
        query_vec,
        n_results=10,
        where_filter={"scheme_name": "Test Fund 2"},
    )

    # Should only get 1 result (the one matching the filter)
    assert len(results["documents"][0]) == 1
    assert results["metadatas"][0][0]["scheme_name"] == "Test Fund 2"


def test_query_empty_collection():
    """Test querying an empty collection returns empty results."""
    query_vec = [0.1] * EMBEDDING_DIMENSIONS
    results = query_collection(query_vec, n_results=3)

    assert results["documents"] == [[]]
    assert results["metadatas"] == [[]]
    assert results["distances"] == [[]]


def test_metadata_none_handling():
    """Test that None metadata values are converted to 'N/A'."""
    chunks = [
        {
            "page_content": "Test content with None metadata",
            "metadata": {
                "source_url": "https://example.com",
                "scheme_name": "Test",
                "last_updated": "2026-06-04",
                "chunk_index": 0,
                "expense_ratio": None,
                "exit_load": None,
                "minimum_sip": "100",
                "risk_rating": "High",
                "benchmark": None,
                "aum": "1000 Cr",
                "nav": None,
            },
        }
    ]
    embeddings = _mock_embedding(1)
    index_chunks(chunks, embeddings)

    query_vec = [0.1] * EMBEDDING_DIMENSIONS
    results = query_collection(query_vec, n_results=1)
    meta = results["metadatas"][0][0]

    assert meta["expense_ratio"] == "N/A"
    assert meta["exit_load"] == "N/A"
    assert meta["benchmark"] == "N/A"
    assert meta["nav"] == "N/A"
    assert meta["minimum_sip"] == "100"  # Non-None values preserved


def test_persistence(tmp_path):
    """Test that data persists across collection reloads."""
    persist_dir = str(tmp_path / "persist_test")
    os.makedirs(persist_dir, exist_ok=True)

    # Create and populate a collection
    col1 = VectorCollection("test_persist", persist_dir)
    col1.add(
        ids=["id1", "id2"],
        documents=["doc one", "doc two"],
        metadatas=[{"key": "val1"}, {"key": "val2"}],
        embeddings=_mock_embedding(2),
    )
    assert col1.count() == 2

    # Create a new instance pointing to the same directory (simulates restart)
    col2 = VectorCollection("test_persist", persist_dir)
    assert col2.count() == 2
    assert col2._documents == ["doc one", "doc two"]


def test_cosine_similarity_ranking():
    """Test that results are ranked by cosine similarity (closest first)."""
    # Create chunks with distinct embeddings pointing in different directions
    chunks = _make_chunks(3)
    embeddings = [
        [1.0, 0.0, 0.0] + [0.0] * (EMBEDDING_DIMENSIONS - 3),  # Points in x direction
        [0.0, 1.0, 0.0] + [0.0] * (EMBEDDING_DIMENSIONS - 3),  # Points in y direction
        [0.0, 0.0, 1.0] + [0.0] * (EMBEDDING_DIMENSIONS - 3),  # Points in z direction
    ]

    index_chunks(chunks, embeddings)

    # Query with a vector pointing mostly in the x direction
    query_vec = [0.9, 0.1, 0.0] + [0.0] * (EMBEDDING_DIMENSIONS - 3)
    results = query_collection(query_vec, n_results=3)

    # Fund 0 (x-direction) should be the closest match
    assert results["metadatas"][0][0]["scheme_name"] == "Test Fund 0"
    # Distances should be in ascending order
    dists = results["distances"][0]
    assert dists[0] <= dists[1] <= dists[2]
