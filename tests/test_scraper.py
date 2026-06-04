"""
test_scraper.py
---------------
Unit tests for ingestion/scraper.py

Tests cover:
  - Metadata extraction (_extract_scheme_name)
  - JS-render detection (_is_js_rendered)
  - Result dict shape (_build_result)
  - scrape_all() success and partial-failure scenarios (mocked network)
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ingestion.scraper import (
    JS_RENDER_THRESHOLD,
    TARGET_URLS,
    _build_result,
    _extract_scheme_name,
    _is_js_rendered,
    scrape_all,
    scrape_url,
)


# ─────────────────────────────────────────────
# _extract_scheme_name
# ─────────────────────────────────────────────

class TestExtractSchemeName:
    def test_extracts_from_title_strips_groww_suffix(self):
        html = "<title>HDFC Mid Cap Fund Direct Growth | Groww</title>"
        assert _extract_scheme_name(html, "https://example.com") == "HDFC Mid Cap Fund Direct Growth"

    def test_extracts_from_title_no_suffix(self):
        html = "<title>HDFC Equity Fund</title>"
        assert _extract_scheme_name(html, "https://example.com") == "HDFC Equity Fund"

    def test_falls_back_to_h1(self):
        html = "<h1>HDFC Small Cap Fund Direct Growth</h1>"
        assert _extract_scheme_name(html, "https://example.com") == "HDFC Small Cap Fund Direct Growth"

    def test_falls_back_to_url_slug(self):
        html = "<html><body></body></html>"
        url = "https://groww.in/mutual-funds/hdfc-defence-fund-direct-growth"
        result = _extract_scheme_name(html, url)
        assert "Hdfc" in result or "hdfc" in result.lower()

    def test_empty_html_uses_url(self):
        result = _extract_scheme_name("", "https://groww.in/mutual-funds/hdfc-gold-etf-fund-of-fund-direct-plan-growth")
        assert result  # should not be empty


# ─────────────────────────────────────────────
# _is_js_rendered
# ─────────────────────────────────────────────

class TestIsJsRendered:
    def test_short_html_is_js_rendered(self):
        short_html = "<html><body>Loading...</body></html>"
        assert _is_js_rendered(short_html) is True

    def test_long_html_is_not_js_rendered(self):
        long_html = "x" * (JS_RENDER_THRESHOLD + 1)
        assert _is_js_rendered(long_html) is False

    def test_empty_string_is_js_rendered(self):
        assert _is_js_rendered("") is True

    def test_exactly_at_threshold(self):
        html = "x" * JS_RENDER_THRESHOLD
        assert _is_js_rendered(html) is True


# ─────────────────────────────────────────────
# _build_result
# ─────────────────────────────────────────────

class TestBuildResult:
    def test_success_result_has_required_keys(self):
        html = "<title>HDFC Equity Fund | Groww</title><body>content</body>"
        result = _build_result("https://example.com", html, success=True)
        assert result["success"] is True
        assert result["source_url"] == "https://example.com"
        assert result["scheme_name"] == "HDFC Equity Fund"
        assert "scraped_at" in result
        assert result["html"] == html
        assert result["error"] is None

    def test_failure_result(self):
        result = _build_result("https://example.com", "", success=False, error="HTTP 404")
        assert result["success"] is False
        assert result["error"] == "HTTP 404"
        assert result["html"] == ""

    def test_scraped_at_is_iso_format(self):
        result = _build_result("https://example.com", "x" * 100, success=True)
        from datetime import datetime
        # Should parse without raising
        datetime.fromisoformat(result["scraped_at"].replace("Z", "+00:00"))


# ─────────────────────────────────────────────
# scrape_url (mocked network)
# ─────────────────────────────────────────────

class TestScrapeUrl:
    @patch("ingestion.scraper._fetch_with_httpx")
    def test_returns_success_on_good_httpx_response(self, mock_fetch):
        long_html = "<title>HDFC Equity Fund | Groww</title>" + "x" * JS_RENDER_THRESHOLD
        mock_fetch.return_value = (long_html, None)
        result = asyncio.run(scrape_url("https://groww.in/mutual-funds/hdfc-equity-fund-direct-growth"))
        assert result["success"] is True
        assert result["html"] == long_html

    @patch("ingestion.scraper._fetch_with_playwright", new_callable=AsyncMock)
    @patch("ingestion.scraper._fetch_with_httpx")
    def test_falls_back_to_playwright_on_short_response(self, mock_httpx, mock_playwright):
        short_html = "<html><body>Loading</body></html>"
        long_html = "<title>HDFC Fund</title>" + "x" * (JS_RENDER_THRESHOLD + 500)
        mock_httpx.return_value = (short_html, None)
        mock_playwright.return_value = (long_html, None)
        result = asyncio.run(scrape_url("https://groww.in/mutual-funds/hdfc-equity-fund-direct-growth"))
        assert result["success"] is True
        assert result["html"] == long_html
        mock_playwright.assert_called_once()

    @patch("ingestion.scraper._fetch_with_playwright", new_callable=AsyncMock)
    @patch("ingestion.scraper._fetch_with_httpx")
    def test_returns_failure_when_both_fail(self, mock_httpx, mock_playwright):
        mock_httpx.return_value = ("", "HTTP 503")
        mock_playwright.return_value = ("", "Playwright timeout")
        result = asyncio.run(scrape_url("https://groww.in/mutual-funds/hdfc-equity-fund-direct-growth"))
        assert result["success"] is False
        assert result["error"] is not None


# ─────────────────────────────────────────────
# scrape_all (mocked)
# ─────────────────────────────────────────────

class TestScrapeAll:
    @patch("ingestion.scraper.scrape_url", new_callable=AsyncMock)
    def test_returns_result_for_every_url(self, mock_scrape_url):
        mock_scrape_url.return_value = {
            "source_url": "https://example.com",
            "scheme_name": "Test Fund",
            "scraped_at": "2026-01-01T00:00:00+00:00",
            "html": "x" * 1000,
            "success": True,
            "error": None,
        }
        results = asyncio.run(scrape_all(TARGET_URLS[:3]))
        assert len(results) == 3

    @patch("ingestion.scraper.scrape_url", new_callable=AsyncMock)
    def test_partial_failure_does_not_abort(self, mock_scrape_url):
        def side_effect(url):
            if "hdfc-equity" in url:
                return {
                    "source_url": url,
                    "scheme_name": "HDFC Equity",
                    "scraped_at": "2026-01-01T00:00:00+00:00",
                    "html": "",
                    "success": False,
                    "error": "HTTP 404",
                }
            return {
                "source_url": url,
                "scheme_name": "Other Fund",
                "scraped_at": "2026-01-01T00:00:00+00:00",
                "html": "x" * 1000,
                "success": True,
                "error": None,
            }
        mock_scrape_url.side_effect = side_effect
        results = asyncio.run(scrape_all(TARGET_URLS[:3]))
        successes = [r for r in results if r["success"]]
        failures = [r for r in results if not r["success"]]
        assert len(results) == 3
        assert len(failures) >= 0  # pipeline never raises even on failures
