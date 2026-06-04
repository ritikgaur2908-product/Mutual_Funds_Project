"""
scraper.py
----------
Fetches HTML content from the 7 designated Groww HDFC mutual fund URLs
and the HDFC AMC fund house page.

Strategy:
  1. Try httpx (lightweight, fast) first.
  2. If the response body appears JS-rendered (minimal content), fall back
     to Playwright headless Chromium.
  3. Retry failed requests up to MAX_RETRIES times with exponential backoff.
  4. On per-URL failure, log and skip — never abort the full pipeline run.

Output per URL:
  {
    "source_url":   str,   # original URL
    "scheme_name":  str,   # extracted from <title> or <h1>
    "scraped_at":   str,   # ISO-8601 UTC timestamp
    "html":         str,   # raw HTML body
    "success":      bool,
    "error":        str | None
  }
"""

import asyncio
import logging
import re
import time
from datetime import datetime, timezone
from typing import Optional

import httpx
from playwright.async_api import async_playwright

# ─────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────

TARGET_URLS: list[str] = [
    "https://groww.in/mutual-funds/hdfc-silver-etf-fof-direct-growth",
    "https://groww.in/mutual-funds/hdfc-mid-cap-fund-direct-growth",
    "https://groww.in/mutual-funds/hdfc-equity-fund-direct-growth",
    "https://groww.in/mutual-funds/hdfc-small-cap-fund-direct-growth",
    "https://groww.in/mutual-funds/hdfc-defence-fund-direct-growth",
    "https://groww.in/mutual-funds/hdfc-gold-etf-fund-of-fund-direct-plan-growth",
    "https://groww.in/mutual-funds/hdfc-nifty-50-index-fund-direct-growth",
    # HDFC AMC fund house page for fund-house-level queries
    "https://groww.in/mutual-funds/amc/hdfc-mutual-funds",
]

# Minimum character count to consider httpx response as real content.
# Pages below this threshold are assumed to be JS-gated shells.
JS_RENDER_THRESHOLD: int = 5000

# HTTP request settings
REQUEST_TIMEOUT: float = 30.0       # seconds
MAX_RETRIES: int = 3
BACKOFF_BASE: float = 2.0           # exponential backoff multiplier

# Playwright wait time after page load (ms) to let JS hydrate
PLAYWRIGHT_WAIT_MS: int = 3000

HEADERS: dict[str, str] = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-IN,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
logger = logging.getLogger("scraper")


# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────

def _utc_now() -> str:
    """Return the current UTC time as an ISO-8601 string."""
    return datetime.now(timezone.utc).isoformat()


def _extract_scheme_name(html: str, url: str) -> str:
    """
    Extract the fund/scheme name from the HTML.
    Priority:
      1. <title> tag content (cleaned).
      2. First <h1> tag.
      3. Fallback to the last URL path segment.
    """
    # Attempt <title>
    title_match = re.search(r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
    if title_match:
        raw = title_match.group(1).strip()
        # Groww titles often end with " | Groww" — strip that suffix
        name = re.sub(r"\s*\|\s*Groww.*$", "", raw, flags=re.IGNORECASE).strip()
        if name:
            return name

    # Attempt first <h1>
    h1_match = re.search(r"<h1[^>]*>(.*?)</h1>", html, re.IGNORECASE | re.DOTALL)
    if h1_match:
        raw = re.sub(r"<[^>]+>", "", h1_match.group(1)).strip()
        if raw:
            return raw

    # Fallback: derive from URL path
    slug = url.rstrip("/").split("/")[-1]
    return slug.replace("-", " ").title()


def _is_js_rendered(html: str) -> bool:
    """
    Heuristic: if the raw HTML body is very short (below the threshold),
    the page is likely a JS shell that needs Playwright to hydrate.
    """
    return len(html.strip()) <= JS_RENDER_THRESHOLD


def _build_result(
    url: str,
    html: str,
    success: bool,
    error: Optional[str] = None,
) -> dict:
    return {
        "source_url": url,
        "scheme_name": _extract_scheme_name(html, url) if html else "",
        "scraped_at": _utc_now(),
        "html": html,
        "success": success,
        "error": error,
    }


# ─────────────────────────────────────────────
# httpx scraper (fast path)
# ─────────────────────────────────────────────

def _fetch_with_httpx(url: str) -> tuple[str, Optional[str]]:
    """
    Fetch URL using httpx (synchronous).
    Returns (html, error_message).
    error_message is None on success.

    Retries up to MAX_RETRIES times with exponential backoff.
    Follows up to 5 redirects.
    """
    last_error: str = ""

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            with httpx.Client(
                headers=HEADERS,
                timeout=REQUEST_TIMEOUT,
                follow_redirects=True,
                max_redirects=5,
            ) as client:
                response = client.get(url)

            response.raise_for_status()
            logger.info(f"[httpx] ✓ {url} (attempt {attempt})")
            return response.text, None

        except httpx.HTTPStatusError as exc:
            last_error = f"HTTP {exc.response.status_code} for {url}"
            logger.warning(f"[httpx] {last_error} (attempt {attempt})")
            # 4xx errors are terminal — no point retrying
            if 400 <= exc.response.status_code < 500:
                break

        except httpx.TimeoutException:
            last_error = f"Timeout fetching {url}"
            logger.warning(f"[httpx] {last_error} (attempt {attempt})")

        except httpx.RequestError as exc:
            last_error = f"Request error for {url}: {exc}"
            logger.warning(f"[httpx] {last_error} (attempt {attempt})")

        # Exponential backoff before next retry
        if attempt < MAX_RETRIES:
            sleep_time = BACKOFF_BASE ** attempt
            logger.info(f"[httpx] Retrying in {sleep_time:.1f}s …")
            time.sleep(sleep_time)

    return "", last_error


# ─────────────────────────────────────────────
# Playwright scraper (fallback for JS-rendered pages)
# ─────────────────────────────────────────────

async def _fetch_with_playwright(url: str) -> tuple[str, Optional[str]]:
    """
    Fetch URL using Playwright headless Chromium.
    Waits PLAYWRIGHT_WAIT_MS ms after DOMContentLoaded to allow JS hydration.
    Returns (html, error_message).
    """
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(
                user_agent=HEADERS["User-Agent"],
                locale="en-IN",
            )
            page = await context.new_page()

            response = await page.goto(
                url,
                wait_until="domcontentloaded",
                timeout=REQUEST_TIMEOUT * 1000,  # Playwright uses ms
            )

            if response is None or not response.ok:
                status = response.status if response else "unknown"
                await browser.close()
                return "", f"Playwright received HTTP {status} for {url}"

            # Wait for JS to hydrate
            await page.wait_for_timeout(PLAYWRIGHT_WAIT_MS)
            html = await page.content()
            await browser.close()

            logger.info(f"[playwright] ✓ {url}")
            return html, None

    except Exception as exc:
        error = f"Playwright error for {url}: {exc}"
        logger.warning(f"[playwright] {error}")
        return "", error


# ─────────────────────────────────────────────
# Core scraping logic per URL
# ─────────────────────────────────────────────

async def scrape_url(url: str) -> dict:
    """
    Scrape a single URL.
    1. Try httpx.
    2. If response is too short (JS-rendered), fall back to Playwright.
    3. On failure, return a result with success=False.
    """
    logger.info(f"Scraping: {url}")

    # --- Step 1: fast httpx fetch ---
    html, error = _fetch_with_httpx(url)

    if error:
        # httpx failed entirely — try Playwright as rescue attempt
        logger.info(f"httpx failed for {url}. Trying Playwright …")
        html, error = await _fetch_with_playwright(url)
        if error:
            logger.error(f"Both httpx and Playwright failed for {url}: {error}")
            return _build_result(url, "", success=False, error=error)
        return _build_result(url, html, success=True)

    # --- Step 2: check if JS-rendered ---
    if _is_js_rendered(html):
        logger.info(
            f"Page appears JS-rendered ({len(html)} chars). "
            f"Falling back to Playwright for {url} …"
        )
        pw_html, pw_error = await _fetch_with_playwright(url)
        if pw_error:
            logger.warning(
                f"Playwright fallback failed. Using short httpx response for {url}."
            )
            # Use the partial httpx content rather than nothing
            return _build_result(url, html, success=True, error=pw_error)
        return _build_result(url, pw_html, success=True)

    return _build_result(url, html, success=True)


# ─────────────────────────────────────────────
# Batch scraper
# ─────────────────────────────────────────────

async def scrape_all(urls: list[str] = TARGET_URLS) -> list[dict]:
    """
    Scrape all URLs concurrently.
    Returns a list of result dicts.
    Failed URLs are included with success=False — the pipeline never aborts.
    """
    logger.info(f"Starting scrape for {len(urls)} URLs …")
    tasks = [scrape_url(url) for url in urls]
    results = await asyncio.gather(*tasks, return_exceptions=False)

    succeeded = sum(1 for r in results if r["success"])
    failed = len(results) - succeeded
    logger.info(f"Scrape complete: {succeeded} succeeded, {failed} failed.")

    if failed > 0:
        failed_urls = [r["source_url"] for r in results if not r["success"]]
        logger.warning(f"Failed URLs: {failed_urls}")

    return list(results)


# ─────────────────────────────────────────────
# Entry point (run standalone for testing)
# ─────────────────────────────────────────────

if __name__ == "__main__":
    import json

    results = asyncio.run(scrape_all())
    for r in results:
        status = "✓" if r["success"] else "✗"
        html_len = len(r["html"])
        print(f"  [{status}] {r['scheme_name']} ({html_len} chars) — {r['source_url']}")
        if r["error"]:
            print(f"       Error: {r['error']}")
