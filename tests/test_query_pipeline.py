"""
test_query_pipeline.py
----------------------
Unit tests for the query pipeline components:
- pii_filter.py (PII redaction)
- intent_classifier.py (Intent classification)
- prompt_builder.py (RAG Prompt construction)
- response_formatter.py (LLM Response parsing, sentence truncation, citation validation)
"""

import os
from unittest.mock import MagicMock, patch
import pytest

# Protobuf compatibility workaround
import sys
sys.modules['google._upb._message'] = None

from query.pii_filter import redact_pii
from query.intent_classifier import classify_intent
from llm.prompt_builder import build_messages
from llm.response_formatter import format_response, execute_rag


# ═══════════════════════════════════════════════════════════════════════════
# PII Filter Tests
# ═══════════════════════════════════════════════════════════════════════════

def test_pii_no_redaction():
    """Test that safe queries with no PII are returned unchanged."""
    query = "What is the exit load for HDFC Defence Fund direct plan?"
    assert redact_pii(query) == query


def test_pii_pan_redaction():
    """Test that PAN numbers (case-insensitive) are redacted."""
    assert redact_pii("My PAN is ABCDE1234F.") == "My PAN is [REDACTED]."
    assert redact_pii("pan number: abcde1234f") == "pan number: [REDACTED]"


def test_pii_aadhaar_redaction():
    """Test that Aadhaar numbers (with or without spaces/dashes) are redacted."""
    assert redact_pii("My Aadhaar is 1234-5678-9012.") == "My Aadhaar is [REDACTED]."
    assert redact_pii("Aadhaar: 1234 5678 9012") == "Aadhaar: [REDACTED]"
    assert redact_pii("Aadhaar: 123456789012") == "Aadhaar: [REDACTED]"


def test_pii_email_redaction():
    """Test that email addresses are redacted."""
    assert redact_pii("My email is invest.user@domain.com") == "My email is [REDACTED]"
    assert redact_pii("Email test@sub.domain.co.in here") == "Email [REDACTED] here"


def test_pii_phone_redaction():
    """Test that Indian phone numbers are redacted."""
    assert redact_pii("My phone is 9876543210.") == "My phone is [REDACTED]."
    assert redact_pii("Contact me at +91 9876543210") == "Contact me at [REDACTED]"
    assert redact_pii("Phone +91-8765432109") == "Phone [REDACTED]"


def test_pii_account_number_redaction():
    """Test that bank account numbers (10 to 18 digits) are redacted."""
    assert redact_pii("Account number 123456789012345") == "Account number [REDACTED]"
    assert redact_pii("Acc: 987654321098") == "Acc: [REDACTED]"


def test_pii_otp_redaction():
    """Test that OTPs (4 to 8 digits) are redacted, while years/round amounts are preserved."""
    assert redact_pii("My OTP is 9821") == "My OTP is [REDACTED]"
    # Legitimate numbers should be preserved
    assert redact_pii("The year is 2026.") == "The year is 2026."
    assert redact_pii("I want to invest ₹10000.") == "I want to invest ₹10000."
    assert redact_pii("Fund AUM is ₹50000 Cr.") == "Fund AUM is ₹50000 Cr."


# ═══════════════════════════════════════════════════════════════════════════
# Intent Classifier Tests
# ═══════════════════════════════════════════════════════════════════════════

def test_intent_fast_path_advisory():
    """Test that queries containing advisory keywords match the fast-path instantly."""
    advisory_queries = [
        "Should I invest in HDFC Mid Cap Fund?",
        "Can you recommend a good fund?",
        "Which fund is better: Equity or Gold?",
        "What is the return forecast for Defence Fund?",
        "Will HDFC Equity Fund double my money?",
    ]
    for q in advisory_queries:
        assert classify_intent(q) == "advisory"


def test_intent_empty_query():
    """Test that empty queries default to factual."""
    assert classify_intent("") == "factual"
    assert classify_intent(None) == "factual"


@patch("query.intent_classifier._is_mock_mode")
@patch("query.intent_classifier.call_groq_api")
def test_intent_llm_fallback_factual(mock_call_groq, mock_is_mock):
    """Test that LLM fallback correctly returns factual when the LLM says so."""
    mock_is_mock.return_value = False
    mock_call_groq.return_value = "factual"
    assert classify_intent("What is the expense ratio of HDFC Defence Fund?") == "factual"


@patch("query.intent_classifier._is_mock_mode")
@patch("query.intent_classifier.call_groq_api")
def test_intent_llm_fallback_advisory(mock_call_groq, mock_is_mock):
    """Test that LLM fallback correctly returns advisory when the LLM says so."""
    mock_is_mock.return_value = False
    mock_call_groq.return_value = "advisory"

    # Use a query that doesn't trigger fast-path keywords but is advisory
    assert classify_intent("Is it a good idea to put money into HDFC Gold?") == "advisory"


@patch("query.intent_classifier._is_mock_mode")
@patch("query.intent_classifier.call_groq_api")
def test_intent_llm_error_fallback(mock_call_groq, mock_is_mock):
    """Test that if the LLM call fails, the intent classifier defaults to factual."""
    mock_is_mock.return_value = False
    mock_call_groq.side_effect = Exception("API limit exceeded")

    # Should gracefully catch the error and default to factual
    assert classify_intent("Tell me about fund house inception year.") == "factual"


# ═══════════════════════════════════════════════════════════════════════════
# Prompt Builder Tests
# ═══════════════════════════════════════════════════════════════════════════

def test_prompt_builder_structure():
    """Test that RAG messages are built correctly with system prompt and formatted context."""
    chunks = [
        {
            "page_content": "This is chunk 1 details.",
            "metadata": {
                "source_url": "https://example.com/source1",
                "last_updated": "2026-06-04T12:00:00Z"
            }
        },
        {
            "page_content": "This is chunk 2 details.",
            "metadata": {
                "source_url": "https://example.com/source2",
                "last_updated": "2026-06-03"
            }
        }
    ]
    query = "Where is my money?"
    messages = build_messages(query, chunks)

    assert len(messages) == 2
    assert messages[0]["role"] == "system"
    assert "facts-only" in messages[0]["content"]

    user_content = messages[1]["content"]
    assert "CONTEXT:" in user_content
    assert "USER QUESTION:" in user_content
    assert "Where is my money?" in user_content
    assert "https://example.com/source1" in user_content
    assert "2026-06-03" in user_content


# ═══════════════════════════════════════════════════════════════════════════
# Response Formatter Tests
# ═══════════════════════════════════════════════════════════════════════════

def test_response_formatter_correct_parsing():
    """Test parsing a well-formed LLM response."""
    raw_response = (
        "Answer: The minimum investment is ₹100.\n"
        "Source: https://example.com/source1\n"
        "Last updated from sources: 2026-06-04"
    )
    chunks = [
        {
            "page_content": "Sample content",
            "metadata": {
                "source_url": "https://example.com/source1",
                "last_updated": "2026-06-04"
            }
        }
    ]
    formatted = format_response(raw_response, chunks)
    
    assert formatted["answer"] == "The minimum investment is ₹100."
    assert formatted["source_url"] == "https://example.com/source1"
    assert formatted["last_updated"] == "2026-06-04"
    assert formatted["query_type"] == "factual"


def test_response_formatter_sentence_truncation():
    """Test that the response formatter truncates answers exceeding 3 sentences."""
    raw_response = (
        "Answer: Sentence one. Sentence two. Sentence three. Sentence four. Sentence five.\n"
        "Source: https://example.com/source1\n"
        "Last updated from sources: 2026-06-04"
    )
    chunks = [
        {
            "page_content": "Sample content",
            "metadata": {
                "source_url": "https://example.com/source1",
                "last_updated": "2026-06-04"
            }
        }
    ]
    formatted = format_response(raw_response, chunks)
    
    assert formatted["answer"] == "Sentence one. Sentence two. Sentence three."


def test_response_formatter_url_validation_fallback():
    """Test that hallucinated URLs are replaced with the top retrieved chunk URL."""
    raw_response = (
        "Answer: The expense ratio is 0.5%.\n"
        "Source: https://hallucinated-url.com/fake\n"
        "Last updated from sources: 2026-06-04"
    )
    chunks = [
        {
            "page_content": "Sample content",
            "metadata": {
                "source_url": "https://example.com/actual-source",
                "last_updated": "2026-06-04"
            }
        }
    ]
    formatted = format_response(raw_response, chunks)
    
    # Hallucinated URL must be replaced with the fallback from chunk list
    assert formatted["source_url"] == "https://example.com/actual-source"


def test_response_formatter_date_validation_fallback():
    """Test that missing or malformed date is replaced with the latest date from chunks."""
    raw_response = (
        "Answer: The expense ratio is 0.5%.\n"
        "Source: https://example.com/source\n"
        "Last updated from sources: invalid-date-string"
    )
    chunks = [
        {
            "page_content": "Sample content",
            "metadata": {
                "source_url": "https://example.com/source",
                "last_updated": "2026-06-04T12:00:00Z"
            }
        }
    ]
    formatted = format_response(raw_response, chunks)
    
    assert formatted["last_updated"] == "2026-06-04"


@patch("llm.response_formatter.call_groq_api")
def test_execute_rag_empty_context(mock_call):
    """Test executing RAG with empty context returns immediate out-of-scope response."""
    result = execute_rag("How do I make money?", [])
    assert "not available in my current sources" in result["answer"]
    mock_call.assert_not_called()
