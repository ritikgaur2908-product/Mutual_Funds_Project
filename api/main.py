"""
main.py
-------
FastAPI application entry point.
Implements endpoints:
  GET  /health   — Confirms API and vector DB are live
  POST /query    — Processes user question through PII filter, intent classification, and hybrid retrieval
  POST /refresh  — Triggers background scraping and re-indexing (admin-protected)
"""

import asyncio
from contextlib import asynccontextmanager
import logging
import os
import sys
from fastapi import FastAPI, HTTPException, status, Depends, Header, Query, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from dotenv import load_dotenv

# Protobuf compatibility workaround
sys.modules['google._upb._message'] = None

# Configure Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler("app.log", encoding="utf-8"),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("api_main")

# Load environment variables
load_dotenv()

# Import pipeline components
from query.pii_filter import redact_pii
from query.intent_classifier import classify_intent
from query.refusal_handler import get_refusal_response
from retrieval.retriever import get_retriever
from llm.response_formatter import execute_rag
from embeddings.vector_store import get_or_create_collection, run_full_indexing

# Import scraper / ingestion workflow
from ingestion.scraper import scrape_all
from ingestion.cleaner import clean_all
from ingestion.chunker import chunk_all

@asynccontextmanager
async def lifespan(app: FastAPI):
    yield

app = FastAPI(
    title="HDFC Mutual Fund FAQ Assistant RAG API",
    description="A facts-locked RAG FAQ API assistant for HDFC mutual fund schemes.",
    version="1.0.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # Allow all origins during development
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global lock to prevent concurrent re-indexing runs
indexing_lock = asyncio.Lock()

# ── Pydantic Request/Response Models ───────────────────────────────────────

class QueryRequest(BaseModel):
    message: str = Field(..., min_length=1, description="The user's query question")

class QueryResponse(BaseModel):
    answer: str
    source_url: str
    last_updated: str
    query_type: str

class HealthResponse(BaseModel):
    status: str
    vector_db: dict

class RefreshResponse(BaseModel):
    status: str
    message: str


# ── Dependency Helpers ──────────────────────────────────────────────────────

def verify_admin_token(
    x_admin_token: str | None = Header(None, alias="X-Admin-Token"),
    token: str | None = Query(None)
) -> bool:
    """
    Dependency to verify the admin authorization token.
    Checks the 'X-Admin-Token' HTTP header or 'token' query parameter.
    """
    expected_token = os.getenv("ADMIN_TOKEN", "admin-secret")
    if x_admin_token == expected_token or token == expected_token:
        return True
    
    logger.warning("Unauthorized access attempt to administrative endpoints.")
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Unauthorized: Invalid admin token"
    )


# ── Background Worker Tasks ─────────────────────────────────────────────────

async def run_background_indexing():
    """
    Asynchronous task runner to execute the ingestion pipeline in the background.
    """
    if indexing_lock.locked():
        logger.warning("Indexing is already in progress, skipping background trigger.")
        return

    async with indexing_lock:
        logger.info("Background scraping and indexing process initiated.")
        try:
            # 1. Scrape all configured URLs
            scraped = await scrape_all()
            
            # 2. Clean HTML content and extract tables / structured data
            cleaned = clean_all(scraped)
            
            # 3. Partition text into metadata-enriched chunks
            chunks = chunk_all(cleaned)
            
            # 4. Generate embeddings and persist database collection
            if chunks:
                count = run_full_indexing(chunks)
                logger.info(f"Background indexing completed successfully. {count} chunks indexed.")
            else:
                logger.warning("No chunks found to index during background refresh.")
        except Exception as e:
            logger.error(f"Error during background ingestion/indexing: {e}", exc_info=True)


# ── REST API Router Endpoints ────────────────────────────────────────────────

@app.get("/health", response_model=HealthResponse)
def health_check():
    """
    Verifies that the API server is active and the vector database is reachable.
    """
    try:
        collection = get_or_create_collection()
        count = collection.count()
        return {
            "status": "healthy",
            "vector_db": {
                "collection": collection.name,
                "count": count
            }
        }
    except Exception as e:
        logger.error(f"Database health check failed: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Service Unavailable: Vector database is unreachable. Error: {str(e)}"
        )


@app.post("/query", response_model=QueryResponse)
def query_assistant(request: QueryRequest):
    """
    Process the user query through safety, routing, retrieval, and LLM synthesis.
    """
    try:
        # Step 1: PII Redaction
        sanitized_query = redact_pii(request.message)
        
        # Step 2: Intent Classification (Factual vs. Advisory)
        intent = classify_intent(sanitized_query)
        
        if intent == "advisory":
            refusal_msg = get_refusal_response()
            return {
                "answer": refusal_msg,
                "source_url": "N/A",
                "last_updated": "N/A",
                "query_type": "advisory"
            }
        
        # Step 3: Hybrid Retrieval (BM25 + Cosine Similarity Vector Search)
        retriever = get_retriever()
        chunks = retriever.retrieve(sanitized_query)
        
        # Step 4: RAG Prompt Assembly & Groq Inference Execution
        result = execute_rag(sanitized_query, chunks)
        
        return {
            "answer": result.get("answer", "This information is not available in my current sources."),
            "source_url": result.get("source_url", "N/A"),
            "last_updated": result.get("last_updated", "N/A"),
            "query_type": "factual"
        }
    except Exception as e:
        logger.error(f"Error handling query request: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Internal server error: {str(e)}"
        )


@app.post("/refresh", response_model=RefreshResponse, status_code=status.HTTP_202_ACCEPTED)
def refresh_data(background_tasks: BackgroundTasks, authorized: bool = Depends(verify_admin_token)):
    """
    Manually triggers full re-scraping and database indexing as a background task.
    """
    if indexing_lock.locked():
        return {
            "status": "in-progress",
            "message": "Data refresh is already in progress."
        }

    background_tasks.add_task(run_background_indexing)
    return {
        "status": "accepted",
        "message": "Data refresh triggered successfully in the background."
    }
