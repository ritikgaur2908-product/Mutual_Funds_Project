"""
refusal_handler.py
------------------
Generates a polite, compliant refusal response for advisory or
non-factual queries, with links to AMFI and SEBI investor education.
"""

import logging

logger = logging.getLogger("refusal_handler")

REFUSAL_RESPONSE = (
    "I can only provide factual information about mutual fund schemes and "
    "cannot offer investment advice or recommendations.\n\n"
    "For investor education, please visit:\n"
    "→ AMFI Investor Education: https://www.amfiindia.com/investor-corner\n"
    "→ SEBI Investor Education: https://investor.sebi.gov.in"
)


def get_refusal_response() -> str:
    """
    Return the standard compliance refusal response.

    Returns:
        The refusal response string.
    """
    logger.info("Generated standard refusal response for advisory query.")
    return REFUSAL_RESPONSE


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding='utf-8')
    
    print("[*] Testing refusal handler output:")
    print("=" * 60)
    print(get_refusal_response())
    print("=" * 60)
