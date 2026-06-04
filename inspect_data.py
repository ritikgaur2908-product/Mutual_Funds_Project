"""
inspect_data.py
---------------
Quick inspection script — runs the scraper + cleaner pipeline
and saves the output to data/scraped_raw.json and data/cleaned_text.json
so you can inspect the data before it goes into the vector store.

Usage:
    python inspect_data.py
"""

import asyncio
import json
import os
from pathlib import Path

from ingestion.scraper import scrape_all
from ingestion.cleaner import clean_all


OUTPUT_DIR = Path("data")
RAW_FILE = OUTPUT_DIR / "scraped_raw.json"
CLEANED_FILE = OUTPUT_DIR / "cleaned_text.json"


async def main():
    OUTPUT_DIR.mkdir(exist_ok=True)

    # ── Step 1: Scrape ──────────────────────────────────────
    print("\n[*] Scraping URLs ...\n")
    scraped = await scrape_all()

    # Save raw output (exclude full HTML to keep file readable — save length instead)
    raw_summary = []
    for r in scraped:
        raw_summary.append({
            "scheme_name": r["scheme_name"],
            "source_url":  r["source_url"],
            "scraped_at":  r["scraped_at"],
            "success":     r["success"],
            "html_length": len(r.get("html", "")),
            "error":       r.get("error"),
        })

    with open(RAW_FILE, "w", encoding="utf-8") as f:
        json.dump(raw_summary, f, indent=2, ensure_ascii=False)
    print(f"  [OK] Raw scrape summary saved -> {RAW_FILE}")

    # ── Step 2: Clean ──────────────────────────────────────
    print("\n[*] Cleaning scraped content ...\n")
    cleaned = clean_all(scraped)

    # Save cleaned text output
    cleaned_output = []
    for doc in cleaned:
        text = doc.get("text", "")
        cleaned_output.append({
            "scheme_name":    doc["scheme_name"],
            "source_url":     doc["source_url"],
            "scraped_at":     doc["scraped_at"],
            "success":        doc["success"],
            "cleaning_error": doc.get("cleaning_error"),
            "structured_data": doc.get("structured_data"),   # newly added structured data
            "text_length":    len(text),
            "text_preview":   text[:500] if text else "",   # first 500 chars
            "text":           text,                          # full cleaned text
        })

    with open(CLEANED_FILE, "w", encoding="utf-8") as f:
        json.dump(cleaned_output, f, indent=2, ensure_ascii=False)
    print(f"  [OK] Cleaned text saved -> {CLEANED_FILE}")

    # ── Summary ────────────────────────────────────────────
    print("\n" + "-" * 55)
    print(f"{'Scheme':<45} {'Chars':>8}")
    print("-" * 55)
    for doc in cleaned_output:
        status = "OK" if not doc["cleaning_error"] else "FAIL"
        name = doc["scheme_name"][:42]
        chars = doc["text_length"]
        print(f"  [{status}] {name:<42} {chars:>8}")
    print("-" * 55)
    print(f"\n[*] Open these files to inspect the data:")
    print(f"   {RAW_FILE.resolve()}")
    print(f"   {CLEANED_FILE.resolve()}\n")


if __name__ == "__main__":
    asyncio.run(main())
