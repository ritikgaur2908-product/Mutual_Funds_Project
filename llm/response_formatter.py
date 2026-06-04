"""
response_formatter.py
---------------------
Parses and validates LLM generation outputs.
Enforces compliance rules:
- Max 3 sentences.
- Validates the citation URL against retrieved chunk sources (no hallucinations).
- Restructures outputs into standard JSON payload.
"""

import logging
import re
from llm.client import call_groq_api
from llm.prompt_builder import build_messages

logger = logging.getLogger("response_formatter")


def _truncate_to_sentences(text: str, max_sentences: int = 3) -> str:
    """
    Truncates a block of text to at most max_sentences at the nearest full stop.
    Handles standard sentence boundaries (. ! ?).
    """
    if not text:
        return ""
        
    # Split text by sentence-ending punctuation followed by whitespace (keeping the punctuation)
    sentences = re.split(r"(?<=[.!?])\s+", text.strip())
    
    if len(sentences) <= max_sentences:
        return text.strip()
        
    truncated = " ".join(sentences[:max_sentences])
    logger.warning(
        f"LLM response exceeded sentence limit. "
        f"Truncated from {len(sentences)} to {max_sentences} sentences."
    )
    return truncated


def format_response(raw_response: str, retrieved_chunks: list[dict]) -> dict:
    """
    Parses, cleans, and validates the raw LLM response.

    Rules applied:
    - Extracts Answer, Source, and Date fields.
    - Truncates Answer to max 3 sentences.
    - Validates Source URL against retrieved chunks to prevent hallucination.
    - Fallbacks to top chunk if LLM citation is missing or invalid.
    - Extracts the most recent date from chunks if LLM date is missing or invalid.

    Args:
        raw_response: Raw response string from Groq.
        retrieved_chunks: List of candidate context chunks.

    Returns:
        Structured JSON dictionary.
    """
    # 1. Extract valid fields from chunks for validation/fallback
    valid_urls = []
    chunk_dates = []
    
    for chunk in retrieved_chunks:
        meta = chunk.get("metadata", {})
        if "source_url" in meta:
            valid_urls.append(meta["source_url"])
        if "last_updated" in meta:
            # Normalize ISO timestamp to date
            date_str = meta["last_updated"]
            clean_date = date_str.split("T")[0] if "T" in date_str else date_str
            chunk_dates.append(clean_date)
            
    # Default fallbacks
    fallback_url = valid_urls[0] if valid_urls else "N/A"
    fallback_date = sorted(chunk_dates, reverse=True)[0] if chunk_dates else "N/A"

    # 2. Parse LLM response fields using Regex
    answer = ""
    source_url = ""
    last_updated = ""

    # Answer pattern: matches text between 'Answer:' and next block headers
    answer_match = re.search(
        r"Answer:\s*(.*?)(?=\nSource:|\nLast updated from sources:|$)",
        raw_response,
        re.DOTALL | re.IGNORECASE
    )
    if answer_match:
        answer = answer_match.group(1).strip()
    else:
        # If LLM didn't use the prefix, treat entire text as answer
        # Strip trailing headers if present
        cleaned = re.sub(r"Source:.*$", "", raw_response, flags=re.IGNORECASE | re.DOTALL)
        cleaned = re.sub(r"Last updated:.*$", "", cleaned, flags=re.IGNORECASE | re.DOTALL)
        answer = cleaned.strip()

    # Source pattern: matches first URL on the Source line
    source_match = re.search(r"Source:\s*([^\n]+)", raw_response, re.IGNORECASE)
    if source_match:
        raw_source = source_match.group(1).strip()
        # Find first URL-like substring (strip markdown links if LLM formats them)
        url_extracted = re.search(r"https?://[^\s\)\],]+", raw_source)
        if url_extracted:
            source_url = url_extracted.group(0)

    # Date pattern: matches content after header
    date_match = re.search(r"Last updated from sources:\s*([^\n]+)", raw_response, re.IGNORECASE)
    if date_match:
        last_updated = date_match.group(1).strip()

    # 3. Post-Processing & Guardrails
    # Rule 1: Truncate to maximum 3 sentences
    answer = _truncate_to_sentences(answer, max_sentences=3)

    # Check if the answer indicates information is not available in current sources
    is_not_available = "This information is not available in my current sources" in answer

    # Rule 2: Validate Source URL (LLM-06, LLM-04)
    if is_not_available:
        source_url = "N/A"
    elif not source_url or source_url not in valid_urls:
        if source_url:
            logger.warning(
                f"LLM hallucinated citation URL: '{source_url}'. "
                f"Replacing with valid chunk fallback: '{fallback_url}'"
            )
        source_url = fallback_url

    # Rule 3: Validate Date
    # Date must be YYYY-MM-DD format (4 digits, dash, 2 digits, dash, 2 digits)
    if is_not_available:
        last_updated = "N/A"
    elif not last_updated or not re.match(r"^\d{4}-\d{2}-\d{2}$", last_updated):
        last_updated = fallback_date

    return {
        "answer": answer,
        "source_url": source_url,
        "last_updated": last_updated,
        "query_type": "factual"
    }


def execute_rag(query: str, retrieved_chunks: list[dict]) -> dict:
    """
    Executes the end-to-end LLM RAG completion.
    Builds the prompt, calls Groq, and formats/validates the response.

    Args:
        query: Sanitized user query.
        retrieved_chunks: List of retrieved context chunks.

    Returns:
        JSON response payload.
    """
    if not retrieved_chunks:
        # Fast response if context is empty (RET-01)
        return {
            "answer": "This information is not available in my current sources.",
            "source_url": "N/A",
            "last_updated": "N/A",
            "query_type": "factual"
        }

    # Build prompt messages
    messages = build_messages(query, retrieved_chunks)

    try:
        # Call Groq API
        raw_response = call_groq_api(
            messages=messages,
            temperature=0.0,
            max_tokens=512
        )
        
        # Format and validate
        return format_response(raw_response, retrieved_chunks)

    except Exception as e:
        logger.error(f"Failed to execute RAG LLM query: {e}")
        return {
            "answer": "The assistant is temporarily unavailable. Please try again shortly.",
            "source_url": "N/A",
            "last_updated": "N/A",
            "query_type": "factual"
        }


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding='utf-8')
    
    # Test formatting and sentence boundary logic
    sample_llm_response = (
        "Answer: HDFC Defence Fund has an exit load of 1%. This is applied if redeemed within 1 year. "
        "Redemptions after 1 year have 0% exit load. This is a fourth sentence to trigger truncation.\n"
        "Source: https://groww.in/mutual-funds/hdfc-defence-fund-direct-growth\n"
        "Last updated from sources: 2026-06-04"
    )
    
    test_chunks = [
        {
            "page_content": "Defence Fund details...",
            "metadata": {
                "source_url": "https://groww.in/mutual-funds/hdfc-defence-fund-direct-growth",
                "last_updated": "2026-06-04"
            }
        }
    ]
    
    formatted = format_response(sample_llm_response, test_chunks)
    print("Formatted Result:")
    import json
    print(json.dumps(formatted, indent=2))
