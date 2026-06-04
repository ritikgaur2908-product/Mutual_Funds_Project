"""
test_cleaner.py
---------------
Unit tests for ingestion/cleaner.py

Tests cover:
  - Boilerplate removal
  - Table → Markdown conversion
  - Text normalisation (dates, currency, whitespace)
  - Junk line filter
  - Full clean() pipeline on valid and invalid inputs
"""

import pytest
from bs4 import BeautifulSoup

from ingestion.cleaner import (
    MIN_LINE_LENGTH,
    _normalise_currency,
    _normalise_dates,
    _table_to_markdown,
    clean,
    clean_all,
    filter_junk_lines,
    normalise_text,
    remove_boilerplate,
)


# ─────────────────────────────────────────────
# Boilerplate removal
# ─────────────────────────────────────────────

class TestRemoveBoilerplate:
    def _soup(self, html: str) -> BeautifulSoup:
        return BeautifulSoup(html, "lxml")

    def test_removes_nav(self):
        soup = self._soup("<html><body><nav>Menu</nav><p>Content</p></body></html>")
        result = remove_boilerplate(soup)
        assert result.find("nav") is None
        assert result.find("p") is not None

    def test_removes_header_and_footer(self):
        soup = self._soup("<html><body><header>Top</header><main>Body</main><footer>Bottom</footer></body></html>")
        result = remove_boilerplate(soup)
        assert result.find("header") is None
        assert result.find("footer") is None
        assert result.find("main") is not None

    def test_removes_script_and_style(self):
        soup = self._soup("<html><head><style>.a{}</style></head><body><script>alert(1)</script><p>OK</p></body></html>")
        result = remove_boilerplate(soup)
        assert result.find("script") is None
        assert result.find("style") is None

    def test_removes_cookie_banner_by_class(self):
        soup = self._soup('<html><body><div class="cookie-banner">Accept cookies</div><p>Content</p></body></html>')
        result = remove_boilerplate(soup)
        text = result.get_text()
        assert "Accept cookies" not in text

    def test_removes_advertisement_by_class(self):
        soup = self._soup('<html><body><div class="advertisement">Ad here</div><p>Real content</p></body></html>')
        result = remove_boilerplate(soup)
        text = result.get_text()
        assert "Ad here" not in text

    def test_preserves_main_content(self):
        soup = self._soup('<html><body><nav>Nav</nav><div class="main-content"><p>Fund details here.</p></div></body></html>')
        result = remove_boilerplate(soup)
        assert "Fund details here." in result.get_text()


# ─────────────────────────────────────────────
# Table → Markdown
# ─────────────────────────────────────────────

class TestTableToMarkdown:
    def _table(self, html: str):
        soup = BeautifulSoup(html, "lxml")
        return soup.find("table")

    def test_simple_table(self):
        html = """
        <table>
          <tr><th>Metric</th><th>Value</th></tr>
          <tr><td>Expense Ratio</td><td>0.75%</td></tr>
        </table>
        """
        tag = self._table(html)
        md = _table_to_markdown(tag)
        assert "Metric" in md
        assert "Expense Ratio" in md
        assert "0.75%" in md
        assert "---" in md  # separator row

    def test_empty_table_returns_empty_string(self):
        tag = self._table("<table></table>")
        assert _table_to_markdown(tag) == ""

    def test_table_with_no_header(self):
        html = """
        <table>
          <tr><td>Exit Load</td><td>1%</td></tr>
          <tr><td>Min SIP</td><td>₹500</td></tr>
        </table>
        """
        tag = self._table(html)
        md = _table_to_markdown(tag)
        assert "Exit Load" in md
        assert "Min SIP" in md

    def test_table_row_count(self):
        html = """
        <table>
          <tr><th>A</th><th>B</th></tr>
          <tr><td>1</td><td>2</td></tr>
          <tr><td>3</td><td>4</td></tr>
        </table>
        """
        tag = self._table(html)
        lines = _table_to_markdown(tag).splitlines()
        # header + separator + 2 data rows = 4 lines
        assert len(lines) == 4


# ─────────────────────────────────────────────
# Date normalisation
# ─────────────────────────────────────────────

class TestNormaliseDates:
    def test_dd_mon_yyyy(self):
        assert "2025-06-01" in _normalise_dates("01 Jun 2025")

    def test_dd_full_month_yyyy(self):
        assert "2025-06-01" in _normalise_dates("01 June 2025")

    def test_d_mon_yyyy_no_leading_zero(self):
        assert "2025-03-05" in _normalise_dates("5 Mar 2025")

    def test_mon_dd_yyyy(self):
        assert "2025-06-01" in _normalise_dates("June 01, 2025")

    def test_non_date_strings_unchanged(self):
        text = "The expense ratio is 0.75%"
        assert _normalise_dates(text) == text

    def test_multiple_dates_in_text(self):
        text = "Launched 01 Jan 2020 and updated 15 Dec 2024."
        result = _normalise_dates(text)
        assert "2020-01-01" in result
        assert "2024-12-15" in result


# ─────────────────────────────────────────────
# Currency normalisation
# ─────────────────────────────────────────────

class TestNormaliseCurrency:
    def test_rs_dot(self):
        assert "₹500" in _normalise_currency("Rs.500")

    def test_rs_space(self):
        assert "₹" in _normalise_currency("Rs 5,000")

    def test_inr_label(self):
        result = _normalise_currency("INR 10,000")
        assert "₹" in result
        assert "INR" not in result

    def test_already_rupee_symbol(self):
        text = "₹500 minimum SIP"
        assert _normalise_currency(text) == text

    def test_does_not_alter_unrelated_text(self):
        text = "The fund invests in equities."
        assert _normalise_currency(text) == text


# ─────────────────────────────────────────────
# Junk line filter
# ─────────────────────────────────────────────

class TestFilterJunkLines:
    def test_removes_short_lines(self):
        text = "OK\nThis is a sufficiently long line that provides real information here.\nNo"
        result = filter_junk_lines(text)
        assert "This is a sufficiently long line" in result
        assert "\nOK\n" not in result
        assert "\nNo\n" not in result

    def test_preserves_markdown_table_rows(self):
        text = "| Metric | Value |\n| --- | --- |\n| Exit Load | 1% |"
        result = filter_junk_lines(text)
        assert "| Metric | Value |" in result
        assert "| Exit Load | 1% |" in result

    def test_preserves_blank_lines(self):
        text = f"{'A' * MIN_LINE_LENGTH}\n\n{'B' * MIN_LINE_LENGTH}"
        result = filter_junk_lines(text)
        assert "\n\n" in result

    def test_all_junk_returns_empty(self):
        text = "Hi\nOK\nYes"
        result = filter_junk_lines(text)
        assert result.strip() == ""


# ─────────────────────────────────────────────
# Full clean() pipeline
# ─────────────────────────────────────────────

class TestClean:
    def _make_result(self, html: str, success: bool = True) -> dict:
        return {
            "source_url": "https://groww.in/mutual-funds/hdfc-equity-fund-direct-growth",
            "scheme_name": "HDFC Equity Fund",
            "scraped_at": "2026-06-01T00:00:00+00:00",
            "html": html,
            "success": success,
            "error": None,
        }

    def test_clean_extracts_text(self):
        html = """
        <html><head><title>HDFC Equity Fund | Groww</title></head>
        <body>
          <nav>Nav menu that should be stripped out completely</nav>
          <main>
            <h1>HDFC Equity Fund Direct Growth</h1>
            <p>This fund has an expense ratio of 0.75% per annum, making it competitive in the equity category.</p>
            <p>The minimum SIP amount is Rs.500 per month and the exit load is 1% for redemptions within one year of investment.</p>
          </main>
          <footer>Footer text that should be removed</footer>
        </body></html>
        """
        result = clean(self._make_result(html))
        assert result["cleaning_error"] is None
        assert len(result["text"]) > 0
        # Nav and footer should be gone
        assert "Nav menu" not in result["text"]
        assert "Footer text" not in result["text"]
        # Main content should be present
        assert "expense ratio" in result["text"].lower() or "HDFC Equity" in result["text"]

    def test_clean_handles_failed_scrape(self):
        result = clean({
            "source_url": "https://example.com",
            "scheme_name": "Test",
            "scraped_at": "2026-01-01T00:00:00+00:00",
            "html": "",
            "success": False,
            "error": "HTTP 404",
        })
        assert result["text"] == ""
        assert result["cleaning_error"] is not None

    def test_clean_normalises_currency(self):
        html = """
        <html><body>
          <p>The minimum SIP amount for this fund is Rs.500 per month and the expense ratio is Rs.750 per lakh annually.</p>
          <p>Investors should note that exit loads apply to early redemptions within the lock-in period.</p>
        </body></html>
        """
        result = clean(self._make_result(html))
        assert "Rs." not in result["text"]
        assert "₹" in result["text"]

    def test_clean_normalises_dates(self):
        html = """
        <html><body>
          <p>The fund was launched on 01 Jan 2013 and the last factsheet was updated on 15 May 2026.</p>
          <p>The expense ratio of this fund is 0.75% per annum as reported in the latest factsheet document.</p>
        </body></html>
        """
        result = clean(self._make_result(html))
        assert "2013-01-01" in result["text"]
        assert "2026-05-15" in result["text"]

    def test_clean_preserves_table_content(self):
        html = """
        <html><body>
          <p>Key scheme details are summarised in the table below for reference purposes.</p>
          <table>
            <tr><th>Metric</th><th>Value</th></tr>
            <tr><td>Expense Ratio</td><td>0.75%</td></tr>
            <tr><td>Exit Load</td><td>1% within 1 year</td></tr>
          </table>
        </body></html>
        """
        result = clean(self._make_result(html))
        assert "Expense Ratio" in result["text"]
        assert "0.75%" in result["text"]
        assert "Exit Load" in result["text"]

    def test_clean_all_processes_list(self):
        html = "<html><body><p>This is a sufficiently long paragraph about HDFC mutual fund schemes and their expense ratios.</p></body></html>"
        inputs = [self._make_result(html) for _ in range(3)]
        results = clean_all(inputs)
        assert len(results) == 3
        assert all("text" in r for r in results)
