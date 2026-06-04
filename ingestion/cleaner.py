"""
cleaner.py
----------
Data cleaning and normalisation pipeline.

Input:  A result dict from scraper.py  {html, source_url, scheme_name, scraped_at, ...}
Output: The same dict with two new keys added:
          "text"           — cleaned plain-text content
          "cleaning_error" — error message string, or None

Pipeline (in order):
  1. Boilerplate removal   — strip nav, header, footer, aside, script, style, banners
  2. Table extraction      — convert <table> elements to Markdown before stripping HTML
  3. HTML → plain text     — html2text conversion
  4. Text normalisation    — whitespace, HTML entities, dates, currency symbols
  5. Junk filter           — drop lines shorter than MIN_LINE_LENGTH characters
"""

import html as html_lib
import json
import logging
import re
from typing import Optional

from bs4 import BeautifulSoup, Comment, Tag
import html2text

logger = logging.getLogger("cleaner")

# ─────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────

# HTML tags whose entire subtree should be removed (boilerplate / noise)
STRIP_TAGS: list[str] = [
    "nav", "header", "footer", "aside",
    "script", "style", "noscript",
    "iframe", "svg", "canvas",
    "form", "button", "input", "select", "textarea",
]

# CSS class/id patterns that indicate cookie banners, ads, social widgets, etc.
# Any tag whose class or id matches one of these patterns is removed.
STRIP_CLASS_PATTERNS: list[str] = [
    r"cookie", r"gdpr", r"consent",
    r"advertisement", r"ad-", r"\bad\b", r"ads-",
    r"social", r"share-", r"sharing",
    r"popup", r"modal",
    r"breadcrumb",
    r"sidebar",
    r"promo", r"banner",
    r"newsletter",
    r"sticky",
]

# Minimum line length to keep after cleaning (shorter lines are junk)
MIN_LINE_LENGTH: int = 30

# Date normalisation: maps month abbreviations to zero-padded numbers
MONTH_MAP: dict[str, str] = {
    "jan": "01", "feb": "02", "mar": "03", "apr": "04",
    "may": "05", "jun": "06", "jul": "07", "aug": "08",
    "sep": "09", "oct": "10", "nov": "11", "dec": "12",
}

# html2text configuration
_H2T = html2text.HTML2Text()
_H2T.ignore_links = False          # keep hyperlinks as [text](url)
_H2T.ignore_images = True          # skip image alt text clutter
_H2T.body_width = 0                # no line wrapping
_H2T.unicode_snob = True           # prefer unicode over ASCII approximations
_H2T.skip_internal_links = True    # skip in-page anchor links


# ─────────────────────────────────────────────
# Step 1: Boilerplate Removal
# ─────────────────────────────────────────────

def _is_noisy_tag(tag) -> bool:
    """
    Return True if a tag should be removed based on its class or id attributes.
    Matches against STRIP_CLASS_PATTERNS.
    """
    if not isinstance(tag, Tag):
        return False
    attrs_parts = []
    for attr in ("class", "id"):
        val = tag.get(attr)
        if val is None:
            continue
        if isinstance(val, str):
            attrs_parts.append(val)
        elif isinstance(val, list):
            attrs_parts.extend(str(v) for v in val if v)
    attrs = " ".join(attrs_parts).lower()
    return any(re.search(pattern, attrs) for pattern in STRIP_CLASS_PATTERNS)


def remove_boilerplate(soup: BeautifulSoup) -> BeautifulSoup:
    """
    Mutates and returns the soup with all boilerplate elements removed.
    Removes:
      - Structural noise tags (nav, header, footer, etc.)
      - HTML comments
      - Tags whose class/id matches noise patterns (cookie banners, ads, etc.)
    """
    # Remove structural noise tags entirely
    for tag_name in STRIP_TAGS:
        for tag in soup.find_all(tag_name):
            tag.decompose()

    # Remove HTML comments
    for comment in soup.find_all(string=lambda text: isinstance(text, Comment)):
        comment.extract()

    # Remove tags matching noise class/id patterns
    # Use list() to snapshot before any decompositions modify the tree
    for tag in list(soup.find_all(True)):
        # Skip if this tag was already removed as a descendant of a decomposed parent
        if not isinstance(tag, Tag) or tag.parent is None:
            continue
        if _is_noisy_tag(tag):
            tag.decompose()

    return soup


# ─────────────────────────────────────────────
# Step 2: Table → Markdown conversion
# ─────────────────────────────────────────────

def _table_to_markdown(table_tag) -> str:
    """
    Convert a BeautifulSoup <table> element to a Markdown table string.
    Handles basic colspan/rowspan by flattening to best-effort text.
    Tables with no extractable rows return an empty string.
    """
    rows = table_tag.find_all("tr")
    if not rows:
        return ""

    md_rows: list[list[str]] = []
    for row in rows:
        cells = row.find_all(["th", "td"])
        md_rows.append([cell.get_text(separator=" ", strip=True) for cell in cells])

    if not md_rows:
        return ""

    # Determine column count from the widest row
    col_count = max(len(r) for r in md_rows)
    if col_count == 0:
        return ""

    # Pad rows to uniform width
    md_rows = [r + [""] * (col_count - len(r)) for r in md_rows]

    lines: list[str] = []

    # First row as header
    header = md_rows[0]
    lines.append("| " + " | ".join(header) + " |")
    lines.append("| " + " | ".join(["---"] * col_count) + " |")

    # Remaining rows as data
    for row in md_rows[1:]:
        lines.append("| " + " | ".join(row) + " |")

    return "\n".join(lines)


def extract_tables_as_markdown(soup: BeautifulSoup) -> BeautifulSoup:
    """
    Replace every <table> element in the soup with a <pre> block containing
    the Markdown-formatted table. This ensures table content survives the
    HTML-to-text conversion without losing its structure.
    """
    for table in soup.find_all("table"):
        md = _table_to_markdown(table)
        if md:
            pre_tag = soup.new_tag("pre")
            pre_tag.string = "\n" + md + "\n"
            table.replace_with(pre_tag)
        else:
            table.decompose()

    return soup


# ─────────────────────────────────────────────
# Step 3: HTML → Plain Text
# ─────────────────────────────────────────────

def html_to_text(soup: BeautifulSoup) -> str:
    """
    Convert the processed BeautifulSoup tree to clean plain text
    using html2text, which preserves Markdown-style links and
    the <pre> blocks we inserted for tables.
    """
    return _H2T.handle(str(soup))


# ─────────────────────────────────────────────
# Step 4: Text Normalisation
# ─────────────────────────────────────────────

def _normalise_dates(text: str) -> str:
    """
    Convert human-readable dates to ISO-8601 format (YYYY-MM-DD).
    Handles patterns like: "01 Jun 2025", "1-June-2025", "June 01, 2025"
    """
    # Pattern: DD Mon YYYY  or  DD-Mon-YYYY
    pattern_dmy = re.compile(
        r"\b(\d{1,2})[\s\-/]"
        r"(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|"
        r"Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|"
        r"Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
        r"[\s\-/,]?\s*(\d{4})\b",
        re.IGNORECASE,
    )

    def _replace_dmy(m: re.Match) -> str:
        day = m.group(1).zfill(2)
        month = MONTH_MAP[m.group(2)[:3].lower()]
        year = m.group(3)
        return f"{year}-{month}-{day}"

    text = pattern_dmy.sub(_replace_dmy, text)

    # Pattern: Mon DD, YYYY  (e.g., "June 01, 2025")
    pattern_mdy = re.compile(
        r"\b(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|"
        r"Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|"
        r"Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
        r"[\s\-/,]?\s*(\d{1,2})[\s\-/,]?\s*(\d{4})\b",
        re.IGNORECASE,
    )

    def _replace_mdy(m: re.Match) -> str:
        month = MONTH_MAP[m.group(1)[:3].lower()]
        day = m.group(2).zfill(2)
        year = m.group(3)
        return f"{year}-{month}-{day}"

    return pattern_mdy.sub(_replace_mdy, text)


def _normalise_currency(text: str) -> str:
    """
    Standardise currency representations to the ₹ symbol.
    Handles: Rs., Rs , INR (standalone), ₹ (already correct).
    """
    # Rs. or Rs (with optional trailing dot/space)
    text = re.sub(r"\bRs\.?\s*", "₹", text)
    # INR as standalone currency label (e.g., "INR 5,000" → "₹5,000")
    text = re.sub(r"\bINR\s+", "₹", text)
    return text


def normalise_text(text: str) -> str:
    """
    Full text normalisation pipeline:
      1. Decode remaining HTML entities (&amp; → &, etc.)
      2. Collapse multiple blank lines to a single blank line.
      3. Strip leading/trailing whitespace per line.
      4. Normalise date formats.
      5. Normalise currency symbols.
    """
    # 1. Decode HTML entities
    text = html_lib.unescape(text)

    # 2. Collapse runs of 3+ newlines into exactly 2 (one blank line)
    text = re.sub(r"\n{3,}", "\n\n", text)

    # 3. Strip each line
    lines = [line.strip() for line in text.splitlines()]
    text = "\n".join(lines)

    # 4. Dates
    text = _normalise_dates(text)

    # 5. Currency
    text = _normalise_currency(text)

    return text.strip()


# ─────────────────────────────────────────────
# Step 5: Junk / Empty Line Filter
# ─────────────────────────────────────────────

def filter_junk_lines(text: str) -> str:
    """
    Remove lines shorter than MIN_LINE_LENGTH characters.
    These are typically residual navigation labels, stray symbols,
    or single-word artifacts that survived HTML stripping.

    Exception: preserve blank lines (they delimit paragraphs)
    and lines that are part of a Markdown table (start with '|').
    """
    result_lines: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        # Always keep blank lines (paragraph separators)
        if stripped == "":
            result_lines.append("")
            continue
        # Always keep Markdown table rows
        if stripped.startswith("|"):
            result_lines.append(line)
            continue
        # Keep lines that meet the minimum length
        if len(stripped) >= MIN_LINE_LENGTH:
            result_lines.append(line)

    # Collapse any resulting runs of multiple blank lines again
    text = "\n".join(result_lines)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


# ─────────────────────────────────────────────
# Main cleaner entry point
# ─────────────────────────────────────────────

def clean(scraped_result: dict) -> dict:
    """
    Run the full cleaning pipeline on a single scraper result dict.

    Args:
        scraped_result: dict from scraper.scrape_url() or scrape_all()

    Returns:
        The same dict with two new keys:
          "text"           — cleaned plain-text string (empty string on failure)
          "cleaning_error" — error message or None
    """
    result = dict(scraped_result)  # shallow copy — don't mutate caller's dict

    if not result.get("success") or not result.get("html"):
        result["text"] = ""
        result["cleaning_error"] = result.get("error") or "No HTML content to clean."
        return result

    raw_html: str = result["html"]

    try:
        # Parse
        soup = BeautifulSoup(raw_html, "lxml")

        # Step 1: Remove boilerplate
        soup = remove_boilerplate(soup)

        # Step 2: Convert tables to Markdown before stripping HTML
        soup = extract_tables_as_markdown(soup)

        # Step 3: HTML → plain text
        text = html_to_text(soup)

        # Step 4: Normalise
        text = normalise_text(text)

        # Step 5: Filter junk lines
        text = filter_junk_lines(text)

        if not text:
            result["text"] = ""
            result["cleaning_error"] = "Cleaning produced empty text."
            logger.warning(f"Cleaning produced empty text for: {result['source_url']}")
        else:
            result["text"] = text
            result["cleaning_error"] = None
            logger.info(
                f"[cleaner] ✓ {result['scheme_name']} "
                f"— {len(text)} chars after cleaning."
            )

    except Exception as exc:
        error_msg = f"Cleaning error for {result.get('source_url', '?')}: {exc}"
        logger.error(error_msg)
        result["text"] = ""
        result["cleaning_error"] = error_msg

    return result


# ─────────────────────────────────────────────
# Step 6: Structured Data Extraction
# ─────────────────────────────────────────────

def normalize_name(name: str) -> str:
    """
    Normalise scheme names to enable robust cross-page matching.
    Converts to lowercase, strips punctuation, and removes common terms.
    """
    name = name.lower()
    name = re.sub(r'[^a-z0-9]', '', name)
    for term in ["direct", "growth", "fund", "plan", "nav", "mutual", "performance", "portfolio", "etf", "fof"]:
        name = name.replace(term, "")
    return name


def extract_amc_scheme_details(amc_soup: BeautifulSoup) -> dict[str, dict[str, str]]:
    """
    Parse the AMC page's master table to dynamically extract scheme details
    (expense ratios and fund sizes / AUM) mapped to normalised scheme names.
    """
    scheme_map = {}
    for table in amc_soup.find_all("table"):
        rows = table.find_all("tr")
        if not rows:
            continue
            
        header_cells = rows[0].find_all(["th", "td"])
        headers = [c.get_text(strip=True).lower() for c in header_cells]
        
        name_idx = -1
        expense_idx = -1
        size_idx = -1
        for idx, h in enumerate(headers):
            if "fund name" in h or "name" in h:
                name_idx = idx
            elif "expense ratio" in h or "expense" in h:
                expense_idx = idx
            elif "fund size" in h or "size" in h:
                size_idx = idx
                
        if name_idx == -1:
            continue
            
        for row in rows[1:]:
            cells = row.find_all(["th", "td"])
            max_idx = max(name_idx, expense_idx, size_idx)
            if len(cells) > max_idx:
                name = cells[name_idx].get_text(strip=True)
                if not name:
                    continue
                norm_name = normalize_name(name)
                
                details = {}
                if expense_idx != -1:
                    expense = cells[expense_idx].get_text(strip=True)
                    if expense:
                        details["expense_ratio"] = expense
                if size_idx != -1:
                    size = cells[size_idx].get_text(strip=True)
                    if size:
                        # Normalize AUM value: ensure it has ₹ prefix and " Cr" suffix
                        size_clean = size.replace("₹", "").replace("Cr", "").strip()
                        if size_clean:
                            details["aum"] = f"₹{size_clean} Cr"
                            
                if details:
                    if norm_name not in scheme_map:
                        scheme_map[norm_name] = {}
                    scheme_map[norm_name].update(details)
    return scheme_map


def extract_structured_data(text: str, scheme_name: str, amc_scheme_map: dict) -> dict:
    """
    Extract key-value pairs (expense_ratio, exit_load, minimum_sip, etc.)
    from the cleaned text of a scheme using regular expressions and
    the AMC scheme details lookup map.
    """
    structured = {
        "expense_ratio": "N/A",
        "exit_load": "N/A",
        "minimum_sip": "N/A",
        "minimum_lumpsum": "N/A",
        "risk_rating": "N/A",
        "benchmark": "N/A",
        "aum": "N/A",
        "nav": "N/A"
    }
    
    # 1. Match Expense Ratio & AUM from the AMC lookup table
    norm_name = normalize_name(scheme_name)
    matched_details = None
    if norm_name in amc_scheme_map:
        matched_details = amc_scheme_map[norm_name]
    else:
        # Try finding a partial match in normalised names
        for k, v in amc_scheme_map.items():
            if k in norm_name or norm_name in k:
                matched_details = v
                break
                
    if matched_details:
        if "expense_ratio" in matched_details:
            structured["expense_ratio"] = matched_details["expense_ratio"]
        if "aum" in matched_details:
            structured["aum"] = matched_details["aum"]
            
    # Format number as percentage if it is numeric and lacks the symbol
    if structured["expense_ratio"] != "N/A" and not structured["expense_ratio"].endswith("%"):
        try:
            float(structured["expense_ratio"])
            structured["expense_ratio"] = f"{structured['expense_ratio']}%"
        except ValueError:
            pass

    # 2. Extract Exit Load
    exit_load_match = re.search(r"Exit load of ([^.;\n]+)", text, re.IGNORECASE)
    if exit_load_match:
        structured["exit_load"] = exit_load_match.group(1).strip()
        
    # 3. Extract Minimum SIP
    sip_match = re.search(r"Minimum SIP Investment is (?:set to )?(₹\s*\d[\d,]*)", text, re.IGNORECASE)
    if sip_match:
        structured["minimum_sip"] = sip_match.group(1).strip()
        
    # 4. Extract Minimum Lumpsum
    lumpsum_match = re.search(r"Minimum Lumpsum Investment is (₹\s*\d[\d,]*)", text, re.IGNORECASE)
    if lumpsum_match:
        structured["minimum_lumpsum"] = lumpsum_match.group(1).strip()
        
    # 5. Extract Risk Rating
    risk_match = re.search(r"is rated ([\w\s]+) risk", text, re.IGNORECASE)
    if risk_match:
        structured["risk_rating"] = f"{risk_match.group(1).strip()} Risk"
        
    # 6. Extract Benchmark
    benchmark_match = re.search(r"Fund benchmark\s*([^\n]+)", text, re.IGNORECASE)
    if benchmark_match:
        structured["benchmark"] = benchmark_match.group(1).strip()
        
    # 7. Extract AUM (fallback to regex if not found in AMC table, ignoring AMC total AUM)
    if structured["aum"] == "N/A":
        aum_match = re.search(r"Asset Under Management\(AUM\) of (₹\s*[\d,]+(?:\s*Cr)?)", text, re.IGNORECASE)
        if aum_match:
            val = aum_match.group(1).strip()
            # Guard: ignore the AMC total AUM (₹9,37,048 Cr or similar)
            if "9,37,04" not in val.replace(" ", ""):
                structured["aum"] = val
        
    # 8. Extract NAV
    nav_match = re.search(r"Latest NAV as of [\d-]+ is (₹\s*[\d,.]+)", text, re.IGNORECASE)
    if nav_match:
        structured["nav"] = nav_match.group(1).strip()
        
    return structured


# ─────────────────────────────────────────────
# Main cleaner entry points
# ─────────────────────────────────────────────

def clean_all(scraped_results: list[dict]) -> list[dict]:
    """
    Run clean() on a list of scraper results, building a scheme details map
    from the AMC page and populating a structured_data key for each fund.
    """
    logger.info(f"Cleaning {len(scraped_results)} scraped documents …")
    
    # Pass 1: Parse the HDFC AMC page to build the scheme details lookup map
    amc_scheme_map = {}
    for r in scraped_results:
        if r.get("success") and r.get("html") and "amc/hdfc-mutual-funds" in r["source_url"]:
            try:
                soup = BeautifulSoup(r["html"], "lxml")
                amc_scheme_map = extract_amc_scheme_details(soup)
                logger.info(f"Extracted details for {len(amc_scheme_map)} schemes from AMC page lookup.")
            except Exception as e:
                logger.error(f"Failed to extract scheme details from AMC page: {e}")
                
    # Pass 2: Run standard HTML cleaning and populate structured data keys
    cleaned = []
    for r in scraped_results:
        doc = clean(r)
        if doc.get("success") and doc.get("text"):
            # Extract structured data
            structured = extract_structured_data(doc["text"], doc["scheme_name"], amc_scheme_map)
            
            # Post-process text: replace incorrect total AMC AUM (₹9,37,048 Cr) in the fund's specific description
            correct_aum = structured.get("aum", "N/A")
            if correct_aum != "N/A" and correct_aum != "₹9,37,048 Cr":
                # Clean up spacing differences, replace AMC AUM with scheme AUM in the boilerplate description sentence
                doc["text"] = re.sub(
                    r"Asset Under Management\(AUM\) of ₹\s*9,37,04[78]\s*Cr",
                    f"Asset Under Management(AUM) of {correct_aum}",
                    doc["text"],
                    flags=re.IGNORECASE
                )
                
            doc["structured_data"] = structured
        else:
            doc["structured_data"] = None
        cleaned.append(doc)

    succeeded = sum(1 for r in cleaned if not r.get("cleaning_error"))
    failed = len(cleaned) - succeeded
    logger.info(f"Cleaning complete: {succeeded} succeeded, {failed} failed.")
    return cleaned


# ─────────────────────────────────────────────
# Entry point (run standalone for testing)
# ─────────────────────────────────────────────

if __name__ == "__main__":
    import asyncio
    from ingestion.scraper import scrape_all

    scraped = asyncio.run(scrape_all())
    cleaned = clean_all(scraped)

    for doc in cleaned:
        status = "✓" if not doc.get("cleaning_error") else "✗"
        text_len = len(doc.get("text", ""))
        print(f"  [{status}] {doc['scheme_name']} — {text_len} chars cleaned")
        if doc.get("structured_data"):
            print(f"       Structured: {json.dumps(doc['structured_data'], indent=2)}")
        if doc.get("cleaning_error"):
            print(f"       Error: {doc['cleaning_error']}")
        elif text_len > 0:
            preview = doc["text"][:100].replace("\n", " ")
            print(f"       Preview: {preview} …")
