"""
client.py
---------
Groq API client wrapper.
Provides connection capabilities for chat completions with standard Llama models on Groq.
Supports mock mode fallback for offline testing and development.
"""

import logging
import os
from dotenv import load_dotenv
import httpx

logger = logging.getLogger("llm_client")


def _is_mock_mode() -> bool:
    """Check if the LLM should run in mock mode (no key, or requested)."""
    load_dotenv()
    api_key = os.getenv("GROQ_API_KEY")
    return (
        not api_key
        or api_key == "your_groq_api_key_here"
        or os.getenv("MOCK_LLM", "false").lower() == "true"
    )


def call_groq_api(
    messages: list[dict],
    temperature: float = 0.0,
    max_tokens: int = 1024,
    model: Optional[str] = None
) -> str:
    """
    Submit a prompt/messages sequence to Groq's completions endpoint.

    Args:
        messages: List of message dicts (e.g. [{"role": "user", "content": "..."}]).
        temperature: Sampling temperature (default 0.0 for deterministic).
        max_tokens: Maximum completion tokens limit.
        model: Optional Groq model string override.

    Returns:
        The generated text completion response.

    Raises:
        ValueError: If Groq API key is missing and mock mode is off.
    """
    load_dotenv()
    
    if _is_mock_mode():
        logger.warning(
            "GROQ_API_KEY is not configured or mock mode is enabled. "
            "RUNNING IN MOCK COMPLETION MODE."
        )
        # Identify if this is a classification call (e.g. intent_classifier prompt)
        last_content = messages[-1]["content"] if messages else ""
        if "intent classifier" in last_content.lower() or "factual" in last_content.lower():
            # Heuristic response for intent classification mock
            query_lower = last_content.lower()
            advisory_indicators = ["good", "best", "worst", "growth forecast", "profit", "earn", "rich"]
            if any(term in query_lower for term in advisory_indicators):
                return "advisory"
            return "factual"
            
        # Default mock response for RAG question answering
        return (
            "Answer: This is a mock response from the Groq Llama model. HDFC mutual funds "
            "allow systematic investment plans (SIP) starting from a minimum of ₹100.\n"
            "Source: https://groww.in/mutual-funds/hdfc-mid-cap-fund-direct-growth\n"
            "Last updated from sources: 2026-06-04"
        )

    api_key = os.getenv("GROQ_API_KEY")
    selected_model = model or os.getenv("GROQ_LLM_MODEL", "llama-3.1-8b-instant")

    # Try standard Groq SDK first
    try:
        from groq import Groq
        client = Groq(api_key=api_key)
        completion = client.chat.completions.create(
            messages=messages,
            model=selected_model,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        content = completion.choices[0].message.content
        if content:
            return content.strip()
        return ""
    except ImportError:
        # Fallback to direct HTTP request using httpx
        logger.info("groq package not imported. Falling back to direct REST request via httpx.")
        url = "https://api.groq.com/openai/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        data = {
            "model": selected_model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens
        }
        with httpx.Client(timeout=30.0) as client:
            response = client.post(url, headers=headers, json=data)
            response.raise_for_status()
            res_json = response.json()
            return res_json["choices"][0]["message"]["content"].strip()


# Workaround typing import if needed
from typing import Optional  # noqa: E402
