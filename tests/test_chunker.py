import pytest
from ingestion.chunker import (
    recursive_character_split,
    split_into_chunks,
    chunk_document,
    chunk_all,
    CHUNK_SIZE,
    CHUNK_OVERLAP,
)

def test_recursive_character_split_basic():
    # Test with string shorter than chunk_size
    text = "Hello world"
    chunks = recursive_character_split(text, ["\n", " "], chunk_size=20, chunk_overlap=5)
    assert chunks == ["Hello world"]

    # Test with string longer than chunk_size, splitting by space
    text = "one two three four five six"
    # chunk_size = 10, overlap = 3
    # "one two" is 7. "one two three" is 13 > 10. So split at space. First chunk: "one two".
    # Overlap backtrack: "two" is 3 chars, which is <= 3. So start next chunk with "two" + " " + "three" -> "two three" (9 chars).
    # Overlap backtrack for next: "three" is 5 chars > 3. So start next chunk with "four" + " " + "five" -> "four five" (9 chars).
    # Overlap backtrack for next: "five" is 4 chars > 3. So start next chunk with "six" -> "six" (3 chars).
    chunks = recursive_character_split(text, [" "], chunk_size=10, chunk_overlap=3)
    assert len(chunks) > 1
    for chunk in chunks:
        assert len(chunk) <= 10

def test_recursive_character_split_large_fallback():
    # If a single word is larger than chunk_size and no separators work, it splits by character
    text = "abcdefghijklmnopqrstuvwxyz"
    chunks = recursive_character_split(text, [" "], chunk_size=5, chunk_overlap=1)
    assert len(chunks) > 1
    # Check that it splits by raw characters
    assert chunks[0] == "abcde"

def test_split_into_chunks_semantic_headers():
    text = (
        "# Heading 1\n"
        "This is paragraph one under heading 1. It is short.\n"
        "## Heading 2\n"
        "This is paragraph two under heading 2."
    )
    chunks = split_into_chunks(text)
    # It should split into 2 chunks because of the lookahead on Markdown headings
    assert len(chunks) == 2
    assert "# Heading 1" in chunks[0]
    assert "## Heading 2" in chunks[1]

def test_split_into_chunks_table_preservation():
    # Create a markdown table
    table_lines = [
        "| Header 1 | Header 2 |",
        "| --- | --- |",
        "| Row 1 Col 1 | Row 1 Col 2 |",
        "| Row 2 Col 1 | Row 2 Col 2 |",
    ]
    table_text = "\n".join(table_lines)
    
    # If table is under CHUNK_SIZE, it shouldn't be split
    chunks = split_into_chunks(table_text)
    assert len(chunks) == 1
    assert chunks[0] == table_text

    # If table is combined with other text such that the total exceeds CHUNK_SIZE,
    # the splitter should split at newlines, preserving rows
    long_prefix = "A" * (CHUNK_SIZE - 50)
    text = long_prefix + "\n" + table_text
    chunks = split_into_chunks(text)
    assert len(chunks) > 1
    # Ensure none of the table lines themselves are split in half (each line starts with | and ends with |)
    for chunk in chunks:
        lines = chunk.strip().split("\n")
        for line in lines:
            if line.startswith("|"):
                assert line.endswith("|")

def test_chunk_document_basic():
    doc = {
        "success": True,
        "scheme_name": "Test Scheme",
        "source_url": "https://example.com/test",
        "scraped_at": "2026-06-04T00:00:00Z",
        "text": "This is the body of the test document.",
        "structured_data": {
            "expense_ratio": "0.5%",
            "exit_load": "Nil",
            "minimum_sip": "500",
            "risk_rating": "Moderate",
            "aum": "1000 Cr",
        }
    }
    chunks = chunk_document(doc)
    assert len(chunks) == 1
    chunk = chunks[0]
    
    # Verify content formatting
    assert "Document: Test Scheme" in chunk["page_content"]
    assert "AUM: 1000 Cr" in chunk["page_content"]
    assert "Expense Ratio: 0.5%" in chunk["page_content"]
    assert "This is the body of the test document." in chunk["page_content"]
    
    # Verify metadata inheritance
    metadata = chunk["metadata"]
    assert metadata["scheme_name"] == "Test Scheme"
    assert metadata["source_url"] == "https://example.com/test"
    assert metadata["expense_ratio"] == "0.5%"
    assert metadata["risk_rating"] == "Moderate"
    assert metadata["chunk_index"] == 0

def test_chunk_document_failed_or_empty():
    # Failed scraping should yield no chunks
    doc_failed = {
        "success": False,
        "scheme_name": "Test",
        "source_url": "https://example.com/test",
        "scraped_at": "2026-06-04T00:00:00Z",
        "text": None
    }
    assert chunk_document(doc_failed) == []

    # Empty text should yield no chunks
    doc_empty = {
        "success": True,
        "scheme_name": "Test",
        "source_url": "https://example.com/test",
        "scraped_at": "2026-06-04T00:00:00Z",
        "text": ""
    }
    assert chunk_document(doc_empty) == []

def test_chunk_all():
    docs = [
        {
            "success": True,
            "scheme_name": "Doc 1",
            "source_url": "https://example.com/1",
            "scraped_at": "2026-06-04T00:00:00Z",
            "text": "Doc 1 content.",
            "structured_data": {"expense_ratio": "0.1%"}
        },
        {
            "success": True,
            "scheme_name": "Doc 2",
            "source_url": "https://example.com/2",
            "scraped_at": "2026-06-04T00:00:00Z",
            "text": "Doc 2 content.",
            "structured_data": {"expense_ratio": "0.2%"}
        }
    ]
    chunks = chunk_all(docs)
    assert len(chunks) == 2
    assert chunks[0]["metadata"]["scheme_name"] == "Doc 1"
    assert chunks[1]["metadata"]["scheme_name"] == "Doc 2"
