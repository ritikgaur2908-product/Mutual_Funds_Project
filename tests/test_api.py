"""
test_api.py
-----------
Unit and integration tests for the FastAPI backend application in api/main.py.
"""

import os
import sys
from unittest.mock import MagicMock, patch
import pytest
from fastapi.testclient import TestClient

# Protobuf compatibility workaround
sys.modules['google._upb._message'] = None

from api.main import app

client = TestClient(app)


# ── Health Endpoint Tests ───────────────────────────────────────────────────

@patch("api.main.get_or_create_collection")
def test_health_endpoint_healthy(mock_collection):
    """Test GET /health returns 200 with vector store collection metadata when database is healthy."""
    mock_coll_inst = MagicMock()
    mock_coll_inst.name = "test_collection"
    mock_coll_inst.count.return_value = 42
    mock_collection.return_value = mock_coll_inst

    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["vector_db"]["collection"] == "test_collection"
    assert data["vector_db"]["count"] == 42


@patch("api.main.get_or_create_collection")
def test_health_endpoint_unhealthy(mock_collection):
    """Test GET /health returns 503 when the database collection fails to load."""
    mock_collection.side_effect = Exception("Database access violation on disk")

    response = client.get("/health")
    assert response.status_code == 503
    data = response.json()
    assert "detail" in data
    assert "unreachable" in data["detail"]


# ── Query Endpoint Tests ────────────────────────────────────────────────────

def test_query_validation_error():
    """Test that an empty query message triggers a 422 validation error."""
    response = client.post("/query", json={"message": ""})
    assert response.status_code == 422


@patch("api.main.classify_intent")
@patch("api.main.get_retriever")
@patch("api.main.execute_rag")
def test_query_factual(mock_execute_rag, mock_get_retriever, mock_classify):
    """Test standard factual query flow returning correct JSON and status."""
    mock_classify.return_value = "factual"
    
    mock_retriever = MagicMock()
    mock_retriever.retrieve.return_value = [{"page_content": "sample context text", "metadata": {}}]
    mock_get_retriever.return_value = mock_retriever
    
    mock_execute_rag.return_value = {
        "answer": "This is a factual test answer.",
        "source_url": "https://groww.in/mutual-funds/hdfc-defence-fund-direct-growth",
        "last_updated": "2026-06-04"
    }

    response = client.post("/query", json={"message": "What is the exit load?"})
    assert response.status_code == 200
    data = response.json()
    assert data["query_type"] == "factual"
    assert data["answer"] == "This is a factual test answer."
    assert data["source_url"] == "https://groww.in/mutual-funds/hdfc-defence-fund-direct-growth"
    assert data["last_updated"] == "2026-06-04"


@patch("api.main.classify_intent")
def test_query_advisory(mock_classify):
    """Test advisory query flow returning SEBI/AMFI refusal and status."""
    mock_classify.return_value = "advisory"

    response = client.post("/query", json={"message": "Should I invest in Gold?"})
    assert response.status_code == 200
    data = response.json()
    assert data["query_type"] == "advisory"
    assert "cannot offer investment advice" in data["answer"]
    assert "https://www.amfiindia.com/investor-corner" in data["answer"]
    assert data["source_url"] == "N/A"
    assert data["last_updated"] == "N/A"


@patch("api.main.classify_intent")
@patch("api.main.get_retriever")
@patch("api.main.execute_rag")
def test_query_pii_redaction(mock_execute_rag, mock_get_retriever, mock_classify):
    """Test that query parameters containing sensitive PII are redacted before downstream logic."""
    mock_classify.return_value = "factual"
    
    mock_retriever = MagicMock()
    mock_retriever.retrieve.return_value = []
    mock_get_retriever.return_value = mock_retriever
    
    mock_execute_rag.return_value = {
        "answer": "Sample response.",
        "source_url": "N/A",
        "last_updated": "N/A"
    }

    response = client.post(
        "/query", 
        json={"message": "My Aadhaar is 1234-5678-9012 and my PAN is ABCDE1234F. What is the exit load?"}
    )
    assert response.status_code == 200
    
    # Verify that classify_intent was invoked with redacted text, protecting PII
    mock_classify.assert_called_once()
    passed_query = mock_classify.call_args[0][0]
    assert "[REDACTED]" in passed_query
    assert "1234" not in passed_query
    assert "ABCDE" not in passed_query


# ── Refresh Endpoint Tests ──────────────────────────────────────────────────

def test_refresh_unauthorized():
    """Test that calling GET/POST /refresh without or with an invalid token returns 401."""
    # No auth credentials
    response = client.post("/refresh")
    assert response.status_code == 401

    # Incorrect token query parameter
    response = client.post("/refresh?token=wrong-secret-key")
    assert response.status_code == 401

    # Incorrect token header
    response = client.post("/refresh", headers={"X-Admin-Token": "wrong-secret-key"})
    assert response.status_code == 401


@patch("api.main.run_background_indexing")
def test_refresh_authorized(mock_bg_indexing):
    """Test that calling POST /refresh with valid credentials triggers the indexing job and returns 202."""
    expected_token = os.getenv("ADMIN_TOKEN", "admin-secret")
    
    # Test via query parameter
    response = client.post(f"/refresh?token={expected_token}")
    assert response.status_code == 202
    data = response.json()
    assert data["status"] == "accepted"
    assert "triggered successfully" in data["message"]

    # Test via HTTP header
    response = client.post("/refresh", headers={"X-Admin-Token": expected_token})
    assert response.status_code == 202


# ── Lifespan & Scheduler Integration Tests ──────────────────────────────────

# @patch("api.main.run_background_indexing")
# @patch("ingestion.scheduler.start_scheduler")
# @patch("ingestion.scheduler.stop_scheduler")
# def test_lifespan_scheduler_wiring(mock_stop, mock_start, mock_bg_indexing):
#     """Test that the lifespan manager initializes and shuts down the daily scheduler."""
#     with TestClient(app) as tc:
#         # Verify startup started the scheduler
#         mock_start.assert_called_once()
#         mock_stop.assert_not_called()
#     
#     # Verify shutdown stopped the scheduler
#     mock_stop.assert_called_once()


def test_scheduler_lifecycle():
    """Test that the scheduler starts and stops cleanly via public functions."""
    import asyncio
    
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        from ingestion.scheduler import start_scheduler, stop_scheduler
        
        mock_job = MagicMock()
        
        # Verify starting the scheduler
        start_scheduler(mock_job)
        from ingestion.scheduler import _scheduler as active_sched
        assert active_sched is not None
        assert active_sched.running
        
        # Verify stopping the scheduler
        stop_scheduler()
        from ingestion.scheduler import _scheduler as stopped_sched
        assert stopped_sched is None
    finally:
        loop.close()
        asyncio.set_event_loop(None)


