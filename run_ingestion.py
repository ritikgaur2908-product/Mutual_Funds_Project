"""
run_ingestion.py
----------------
Standalone entry point script to run the full mutual fund ingestion pipeline.
Designed to be executed locally or inside a GitHub Actions workflow.

Performs:
  1. Concurrent HTML scraping of the 7 Groww fund URLs and AMC master page.
  2. Plain-text cleaning, table extraction, and structured metadata mapping.
  3. Semantic document chunking with metadata enrichment.
  4. Core embedding generation (via Gemini API or Mock) and NumPy database indexing.
"""

import asyncio
import logging
import sys

# Configure UTF-8 output to prevent Windows console encoding crashes
sys.stdout.reconfigure(encoding='utf-8')

# Configure Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("run_ingestion")

# Import pipeline components
from ingestion.scraper import scrape_all
from ingestion.cleaner import clean_all
from ingestion.chunker import chunk_all
from embeddings.vector_store import run_full_indexing


async def main():
    logger.info("[*] Starting end-to-end ingestion pipeline ...")
    
    try:
        # Step 1: Scrape HTML content from targets
        logger.info("Step 1: Scraping Groww mutual fund URLs ...")
        scraped = await scrape_all()
        
        # Step 2: Clean HTML and parse AMC scheme details
        logger.info("Step 2: Cleaning HTML content and extracting table data ...")
        cleaned = clean_all(scraped)
        
        # Step 3: Split cleaned texts into metadata-enriched chunks
        logger.info("Step 3: Generating semantic chunks with metadata enrichment ...")
        chunks = chunk_all(cleaned)
        
        # Step 4: Index chunks with Gemini embeddings into the vector database
        if chunks:
            logger.info(f"Step 4: Indexing {len(chunks)} chunks into vector store database ...")
            count = run_full_indexing(chunks)
            logger.info(f"[SUCCESS] Ingestion completed. {count} chunks successfully indexed into the vector store database.")
        else:
            logger.warning("[WARNING] No chunks found. Skipping vector indexing.")
            
    except Exception as e:
        logger.error(f"[ERROR] Ingestion pipeline failed: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
