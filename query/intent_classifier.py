"""
intent_classifier.py
--------------------
Classifies a user query as 'factual' or 'advisory'.
Uses a keyword-based fast filter followed by a Groq LLM fallback
for ambiguous queries.
"""

import logging
import re
from llm.client import call_groq_api, _is_mock_mode

logger = logging.getLogger("intent_classifier")

# ── Configuration ───────────────────────────────────────────────────────────
CLASSIFIER_MODEL: str = "llama-3.1-8b-instant"

# Primary keyword triggers for advisory/speculative queries (instant match)
ADVISORY_PATTERNS: list[str] = [
    r"\bshould\s+i\b",
    r"\brecommend\b",
    r"\bbetter\b",
    r"\bwhich\s+is\s+better\b",
    r"\bbetter\s+fund\b",
    r"\bwhich\s+is\s+best\b",
    r"\bbest\b",
    r"\breturn\s+forecast\b",
    r"\bforecast\b",
    r"\bcompare\b",
    r"\badvise\b",
    r"\badvice\b",
    r"\bsuggest\b",
    r"\bwhere\s+should\s+i\b",
    r"\bwhich\s+one\s+should\s+i\b",
    r"\bperformance\s+comparison\b",
    r"\bexpected\s+returns\b",
    r"\bwill\s+i\s+get\b",
    r"\bdouble\b",
]

CLASSIFICATION_PROMPT = """You are an intent classifier for a Mutual Fund Q&A assistant.
Your task is to classify the user query into one of two categories:
1. "factual": The query asks for objective, verifiable information (e.g., NAV, AUM, exit load, expense ratio, benchmark, minimum investment amounts, how-to instructions, fund house details).
2. "advisory": The query asks for opinions, advice, recommendations, comparison rankings, return forecasts, or suggestions on what to do (e.g., "should I invest", "is it good", "which fund is better", "how much return will I get in 5 years").

Respond with EXACTLY one word: either "factual" or "advisory" (lowercase, no punctuation).

User Query: "{query}"
Category:"""


def classify_intent(query: str) -> str:
    """
    Classifies the user query as 'factual' or 'advisory'.
    
    Uses a hybrid approach:
    1. Checks for fast keyword matches (instant).
    2. Falls back to Groq Llama LLM classifier for ambiguous cases.

    Args:
        query: The sanitized user query string.

    Returns:
        "factual" or "advisory" classification label.
    """
    if not query:
        return "factual"

    query_lower = query.lower().strip()

    # Step 1: Fast keyword check
    for pattern in ADVISORY_PATTERNS:
        if re.search(pattern, query_lower):
            logger.info(f"Fast-path classified as ADVISORY due to pattern match: '{pattern}'")
            return "advisory"

    # Step 2: LLM Fallback (or mock fallback if API key is not configured)
    if _is_mock_mode():
        logger.warning(
            "Running in mock mode. LLM intent classifier fallback returns 'factual' by default."
        )
        # Simple heuristic fallback for mock mode: check for advisory terms not caught by fast-path
        advisory_indicators = ["good", "best", "worst", "growth forecast", "profit", "earn", "rich"]
        if any(term in query_lower for term in advisory_indicators):
            return "advisory"
        return "factual"

    try:
        prompt = CLASSIFICATION_PROMPT.format(query=query)
        messages = [{"role": "user", "content": prompt}]
        
        # Call Groq API
        response_text = call_groq_api(
            messages=messages,
            temperature=0.0,
            max_tokens=10,
            model=CLASSIFIER_MODEL
        )
        
        label = response_text.strip().lower()
        
        # Clean up any trailing periods or whitespace
        label = re.sub(r"[^a-z]", "", label)
        
        if label in ("factual", "advisory"):
            logger.info(f"Groq LLM classified query as: '{label}'")
            return label
        
        # Default fallback if the LLM output is unexpected
        logger.warning(f"Unexpected LLM classification output: '{response_text}'. Defaulting to 'factual'.")
        return "factual"

    except Exception as e:
        logger.error(f"Error calling LLM intent classifier: {e}. Defaulting to 'factual'.")
        return "factual"


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding='utf-8')
    logging.basicConfig(level=logging.INFO, format="%(name)s | %(levelname)s | %(message)s")

    test_queries = [
        "What is the exit load of HDFC Defence Fund?",
        "Should I invest in HDFC Mid-Cap Opportunities Fund?",
        "Which fund is better: HDFC Equity or HDFC Small Cap?",
        "How can I invest in HDFC Nifty 50 Index Fund via SIP?",
        "Can you recommend a good mutual fund for long term?",
        "What was the NAV of HDFC Silver ETF FoF yesterday?",
        "Will HDFC Equity Fund double my money in 5 years?",
        "Tell me about the fund manager of HDFC Gold ETF.",
    ]

    print("[*] Running Intent Classifier tests...")
    for q in test_queries:
        intent = classify_intent(q)
        print(f"Query:  {q}")
        print(f"Intent: {intent.upper()}")
        print("-" * 50)
