"""
test_refusal.py
----------------
Unit tests for query/refusal_handler.py.
"""

from query.refusal_handler import get_refusal_response


def test_refusal_response_content():
    """Test that the refusal handler returns the correct compliance message and links."""
    response = get_refusal_response()
    
    # Check compliance message text elements
    assert "factual information" in response
    assert "cannot offer investment advice" in response
    
    # Check investor education links are present
    assert "https://www.amfiindia.com/investor-corner" in response
    assert "https://investor.sebi.gov.in" in response
    assert "AMFI Investor Education" in response
    assert "SEBI Investor Education" in response
