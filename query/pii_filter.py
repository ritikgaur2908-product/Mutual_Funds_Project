"""
pii_filter.py
-------------
PII detection and redaction module.
Strips PAN numbers, Aadhaar numbers, account numbers, email addresses,
phone numbers, and OTPs from user queries before processing.
"""

import logging
import re

logger = logging.getLogger("pii_filter")

# Compile PII Regex Patterns
# PAN: 5 letters, 4 digits, 1 letter (e.g. ABCDE1234F)
PAN_PATTERN = re.compile(r"\b[A-Z]{5}[0-9]{4}[A-Z]\b", re.IGNORECASE)

# Aadhaar: 12 digits, formatted as XXXX XXXX XXXX or XXXX-XXXX-XXXX or XXXXXXXXXXXX
AADHAAR_PATTERN = re.compile(r"\b\d{4}[\s-]?\d{4}[\s-]?\d{4}\b")

# Email
EMAIL_PATTERN = re.compile(r"\b[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}\b", re.IGNORECASE)

# Phone: Indian phone numbers (e.g. +91 9876543210, +91-9876543210, 09876543210, 9876543210)
PHONE_PATTERN = re.compile(r"(?:\+91[\s\-]?)?\b[6789]\d{9}\b")

# Bank Account Number: 10 to 18 digits (needs to be run after phone and Aadhaar to avoid overlap)
ACCOUNT_PATTERN = re.compile(r"\b\d{10,18}\b")

# OTP: 4 to 8 consecutive digits
OTP_PATTERN = re.compile(r"\b\d{4,8}\b")

# Common round numbers or years to exclude from OTP redacting to prevent false positives in financial queries
EXCLUDED_OTP_VALS = {
    # Years
    *range(1900, 2100),
    # Common round amounts
    1000, 2000, 3000, 4000, 5000, 10000, 15000, 20000, 25000, 50000, 100000
}
EXCLUDED_OTP_STRS = {str(val) for val in EXCLUDED_OTP_VALS}


def redact_pii(query: str) -> str:
    """
    Scan the query for PII (PAN, Aadhaar, Account numbers, email, phone, OTP)
    and replace matching sequences with [REDACTED].

    Args:
        query: The raw user query string.

    Returns:
        The sanitized query string.
    """
    if not query:
        return ""

    sanitized = query
    detected = False

    # 1. PAN check
    if PAN_PATTERN.search(sanitized):
        sanitized = PAN_PATTERN.sub("[REDACTED]", sanitized)
        detected = True

    # 2. Aadhaar check
    if AADHAAR_PATTERN.search(sanitized):
        sanitized = AADHAAR_PATTERN.sub("[REDACTED]", sanitized)
        detected = True

    # 3. Email check
    if EMAIL_PATTERN.search(sanitized):
        sanitized = EMAIL_PATTERN.sub("[REDACTED]", sanitized)
        detected = True

    # 4. Phone check
    if PHONE_PATTERN.search(sanitized):
        sanitized = PHONE_PATTERN.sub("[REDACTED]", sanitized)
        detected = True

    # 5. Account number check (10 to 18 digits)
    # We check if there's any remaining matching sequence that is NOT already redacted
    if ACCOUNT_PATTERN.search(sanitized):
        sanitized = ACCOUNT_PATTERN.sub("[REDACTED]", sanitized)
        detected = True

    # 6. OTP check (4 to 8 digits)
    # Exclude common years and round numbers from redaction
    def otp_replacer(match: re.Match) -> str:
        val = match.group(0)
        if val in EXCLUDED_OTP_STRS:
            return val
        return "[REDACTED]"

    pre_otp = sanitized
    sanitized = OTP_PATTERN.sub(otp_replacer, sanitized)
    if sanitized != pre_otp:
        detected = True

    if detected:
        logger.warning(f"PII detected and redacted from query: '{query}' -> '{sanitized}'")

    return sanitized


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding='utf-8')
    # Simple manual tests
    logging.basicConfig(level=logging.WARNING)
    
    test_queries = [
        "What is the exit load for HDFC Defence Fund?",
        "My Aadhaar is 1234-5678-9012, tell me about Mid Cap Fund.",
        "My PAN is ABCDE1234F, can I check my investment?",
        "Send my statement to test.user@gmail.com please.",
        "My phone number is 9876543210.",
        "My account number is 123456789012345.",
        "My OTP is 9821.",
        "What is the expense ratio for HDFC Nifty 50 Index Fund in 2026?",
        "Can I invest ₹10000 in HDFC Small Cap Fund?",
    ]

    print("[*] Running PII filter tests...")
    for q in test_queries:
        res = redact_pii(q)
        print(f"Original:  {q}")
        print(f"Sanitized: {res}")
        print("-" * 50)
