"""
test_retrieval.py
-----------------
Unit and integration tests for retrieval/retriever.py.
Tests hybrid retrieval (BM25 + Semantic), query routing (filters),
RRF ranking, and minimum similarity threshold filtering.
"""

import os
import shutil
import pytest
from unittest.mock import MagicMock, patch

# Protobuf compatibility workaround
import sys
sys.modules['google._upb._message'] = None

from embeddings.vector_store import VectorCollection, _client_cache
from retrieval.retriever import HybridRetriever, MIN_SIMILARITY_THRESHOLD


# ═══════════════════════════════════════════════════════════════════════════
# Isolation Fixture
# ═══════════════════════════════════════════════════════════════════════════

@pytest.fixture(autouse=True)
def isolate_retriever_db(tmp_path):
    """
    Ensures each test has its own separate persistent directory and cache state.
    """
    persist_dir = str(tmp_path / "test_retrieval_db")
    os.makedirs(persist_dir, exist_ok=True)
    os.environ["CHROMA_PERSIST_DIR"] = persist_dir
    os.environ["MOCK_EMBEDDINGS"] = "true"  # Run using deterministic mock embeddings

    # Clear modules caches
    _client_cache.clear()

    yield persist_dir

    _client_cache.clear()
    if os.path.exists(persist_dir):
        shutil.rmtree(persist_dir, ignore_errors=True)


# ═══════════════════════════════════════════════════════════════════════════
# Helper Functions
# ═══════════════════════════════════════════════════════════════════════════

def _seed_sample_database(persist_dir):
    """Seeds the database with test chunks for search validation."""
    col = VectorCollection("hdfc_mutual_fund_docs", persist_dir)
    
    # 3 sample documents (2 Defence fund, 1 Gold fund)
    documents = [
        "This chunk details the exit load of HDFC Defence Fund, which is 1% if redeemed within 1 year.",
        "HDFC Defence Fund has an AUM of 1000 Cr and was launched in 2023.",
        "HDFC Gold ETF Fund of Fund allows minimum SIP of 100 and minimum lumpsum of 500."
    ]
    ids = [
        "defence_chunk_1",
        "defence_chunk_2",
        "gold_chunk_1"
    ]
    metadatas = [
        {
            "source_url": "https://groww.in/mutual-funds/hdfc-defence-fund-direct-growth",
            "scheme_name": "HDFC Defence Fund Direct Growth - NAV, Mutual Fund Performance &amp; Portfolio"
        },
        {
            "source_url": "https://groww.in/mutual-funds/hdfc-defence-fund-direct-growth",
            "scheme_name": "HDFC Defence Fund Direct Growth - NAV, Mutual Fund Performance &amp; Portfolio"
        },
        {
            "source_url": "https://groww.in/mutual-funds/hdfc-gold-etf-fund-of-fund-direct-plan-growth",
            "scheme_name": "HDFC Gold ETF Fund of Fund Direct Plan Growth - NAV, Mutual Fund Performance &amp; Portfolio"
        }
    ]
    
    # Generating mock embeddings (simple vectors)
    embeddings = []
    for doc in documents:
        # Simple vectors matching length of 768
        vec = [0.1] * 768
        # Make Defence chunks slightly different from Gold
        if "Defence" in doc:
            vec[0] = 0.9
        else:
            vec[1] = 0.9
        embeddings.append(vec)
        
    col.add(ids=ids, documents=documents, metadatas=metadatas, embeddings=embeddings)
    _client_cache["hdfc_mutual_fund_docs"] = col


# ═══════════════════════════════════════════════════════════════════════════
# Tests
# ═══════════════════════════════════════════════════════════════════════════

def test_query_routing_filters(isolate_retriever_db):
    """Test that query routing correctly extracts scheme keywords and filters queries."""
    _seed_sample_database(isolate_retriever_db)
    retriever = HybridRetriever()

    # Query targeted at Defence Fund
    results = retriever.retrieve("What is exit load for HDFC Defence Fund?")
    assert len(results) > 0
    # Every chunk should be from Defence Fund
    for res in results:
        assert "Defence" in res["metadata"]["scheme_name"]


def test_query_routing_gold(isolate_retriever_db):
    """Test that query routing correctly routes to Gold fund."""
    _seed_sample_database(isolate_retriever_db)
    retriever = HybridRetriever()

    # Query targeted at Gold Fund
    results = retriever.retrieve("What is SIP for Gold ETF?")
    assert len(results) > 0
    # Every chunk should be from Gold Fund
    for res in results:
        assert "Gold" in res["metadata"]["scheme_name"]


def test_retrieval_empty_db():
    """Test that retrieving from an empty database returns an empty list and logs warning."""
    retriever = HybridRetriever()
    results = retriever.retrieve("exit load")
    assert results == []


@patch("retrieval.retriever.embed_query")
def test_similarity_threshold_filtering(mock_embed, isolate_retriever_db):
    """Test that chunks failing the minimum similarity threshold are filtered out."""
    _seed_sample_database(isolate_retriever_db)
    
    # Mock query embedding pointing in an entirely orthogonal direction (similarity < 0.3)
    # The seeded vectors have positive components. A vector with negative components will be orthogonal.
    mock_embed.return_value = [-0.9] * 768
    
    retriever = HybridRetriever()
    
    # We want a query that won't match BM25 either (so BM25 doesn't return anything)
    results = retriever.retrieve("xyzabcqwe")
    
    # Should return empty list because all semantic matches are below 0.3 similarity
    assert len(results) == 0


@patch("retrieval.retriever.query_collection")
def test_semantic_failure_fallback(mock_query, isolate_retriever_db):
    """Test that if semantic search fails, the retriever falls back to BM25 results."""
    _seed_sample_database(isolate_retriever_db)
    
    # Force semantic search database query to fail
    mock_query.side_effect = Exception("Semantic database query error")
    
    retriever = HybridRetriever()
    
    # Query matching BM25 terms
    results = retriever.retrieve("exit load Defence Fund")
    
    # Should still retrieve results via BM25
    assert len(results) > 0
    assert "exit load" in results[0]["page_content"]
