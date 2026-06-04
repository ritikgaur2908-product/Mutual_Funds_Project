"""
chunker.py
----------
Semantic/recursive text chunker.
Splits cleaned documents into logical chunks of ~1200 characters with 150-char overlap.
Preserves Markdown tables and logical headings as coherent units.
Prefixes each chunk with context information for robust RAG retrieval.
Pure Python implementation (no PyTorch/transformers/langchain dependencies).
"""

import logging
import re

logger = logging.getLogger("chunker")

# Target chunk parameters
CHUNK_SIZE: int = 1200
CHUNK_OVERLAP: int = 150


def recursive_character_split(text: str, separators: list[str], chunk_size: int, chunk_overlap: int) -> list[str]:
    """
    Pure Python implementation of LangChain's RecursiveCharacterTextSplitter.
    Recursively splits text by separators, combining them into chunks of size <= chunk_size.
    Supports chunk overlap.
    """
    if len(text) <= chunk_size:
        return [text]
        
    if not separators:
        # Fallback if no separators are left (split by raw characters)
        chunks = []
        i = 0
        while i < len(text):
            chunks.append(text[i:i + chunk_size])
            i += max(1, chunk_size - chunk_overlap)
        return chunks

    separator = separators[0]
    next_separators = separators[1:]
    
    # Split text by current separator
    parts = text.split(separator)
    
    chunks = []
    current_chunk = []
    current_len = 0
    
    for part in parts:
        part_len = len(part)
        
        # If a single part is larger than chunk_size, recursively split it using next separators
        if part_len > chunk_size:
            # First, flush whatever is in the current chunk
            if current_chunk:
                chunks.append(separator.join(current_chunk))
                current_chunk = []
                current_len = 0
            # Recursively split the large sub-part
            sub_chunks = recursive_character_split(part, next_separators, chunk_size, chunk_overlap)
            chunks.extend(sub_chunks)
            continue
            
        sep_len = len(separator) if current_chunk else 0
        if current_len + sep_len + part_len <= chunk_size:
            current_chunk.append(part)
            current_len += sep_len + part_len
        else:
            # Flush current chunk
            if current_chunk:
                chunks.append(separator.join(current_chunk))
            
            # Start new chunk with overlap backtrack
            overlap_chunk = []
            overlap_len = 0
            for prev_part in reversed(current_chunk):
                prev_sep_len = len(separator) if overlap_chunk else 0
                if overlap_len + prev_sep_len + len(prev_part) <= chunk_overlap:
                    overlap_chunk.insert(0, prev_part)
                    overlap_len += prev_sep_len + len(prev_part)
                else:
                    break
            
            current_chunk = overlap_chunk + [part]
            current_len = overlap_len + (len(separator) if overlap_chunk else 0) + part_len
            
    if current_chunk:
        chunks.append(separator.join(current_chunk))
        
    return chunks


def split_into_chunks(text: str) -> list[str]:
    """
    Split document text semantically.
    1. Splits using markdown headings as logical section boundaries (using lookahead).
    2. Keeps sections intact if they fit within CHUNK_SIZE (preserves tables as atomic units).
    3. Recursively splits large sections on newline boundaries (\n) to keep table rows intact.
    """
    # Split text right before headings (lookahead splits before newlines followed by markdown headers)
    sections = re.split(r'(?=\n### |\n#### |\n## |\n# )', "\n" + text)
    sections = [s.strip() for s in sections if s.strip()]
    
    chunks = []
    separators = ["\n\n", "\n", " ", ""]
    
    for section in sections:
        if len(section) <= CHUNK_SIZE:
            chunks.append(section)
        else:
            # Fallback to recursive character splitter for sections exceeding threshold.
            # Splitting by separators like \n preserves markdown table rows from being broken in half.
            sub_chunks = recursive_character_split(section, separators, CHUNK_SIZE, CHUNK_OVERLAP)
            chunks.extend(sub_chunks)
            
    return chunks


def chunk_document(doc: dict) -> list[dict]:
    """
    Chunk a single cleaned document.
    
    Args:
        doc: dict from cleaner.py (containing scheme_name, text, structured_data, etc.)
        
    Returns:
        List of dicts representing chunks:
          [
            {
              "page_content": str,   # prefixed text chunk
              "metadata": dict       # full enrichment metadata
            },
            ...
          ]
    """
    if not doc.get("success") or not doc.get("text"):
        logger.warning(f"Skipping chunking for failed/empty document: {doc.get('source_url')}")
        return []
        
    text = doc["text"]
    scheme_name = doc["scheme_name"]
    source_url = doc["source_url"]
    scraped_at = doc["scraped_at"]
    structured = doc.get("structured_data") or {}
    
    # Extract structured fields for context prefixing and metadata
    expense_ratio = structured.get("expense_ratio", "N/A")
    exit_load = structured.get("exit_load", "N/A")
    minimum_sip = structured.get("minimum_sip", "N/A")
    minimum_lumpsum = structured.get("minimum_lumpsum", "N/A")
    risk_rating = structured.get("risk_rating", "N/A")
    benchmark = structured.get("benchmark", "N/A")
    aum = structured.get("aum", "N/A")
    nav = structured.get("nav", "N/A")
    
    # Split text into raw chunks
    raw_chunks = split_into_chunks(text)
    
    chunks = []
    for idx, raw_text in enumerate(raw_chunks):
        # 1. Construct context prefix to give the LLM full retrieval context
        prefix = (
            f"Document: {scheme_name} "
            f"(AUM: {aum} | Expense Ratio: {expense_ratio} | Risk: {risk_rating})\n"
            f"---\n"
        )
        page_content = prefix + raw_text
        
        # 2. Enrich metadata dict for database filtering
        metadata = {
            "source_url": source_url,
            "scheme_name": scheme_name,
            "last_updated": scraped_at,
            "chunk_index": idx,
            "expense_ratio": expense_ratio,
            "exit_load": exit_load,
            "minimum_sip": minimum_sip,
            "minimum_lumpsum": minimum_lumpsum,
            "risk_rating": risk_rating,
            "benchmark": benchmark,
            "aum": aum,
            "nav": nav
        }
        
        chunks.append({
            "page_content": page_content,
            "metadata": metadata
        })
        
    logger.info(f"Chunked document '{scheme_name}' into {len(chunks)} chunks.")
    return chunks


def chunk_all(docs: list[dict]) -> list[dict]:
    """
    Run chunk_document on a list of cleaned documents and flatten the results.
    """
    all_chunks = []
    for doc in docs:
        all_chunks.extend(chunk_document(doc))
    logger.info(f"Total chunks created: {len(all_chunks)}")
    return all_chunks


if __name__ == "__main__":
    import json
    import sys
    from pathlib import Path
    
    # Reconfigure stdout to use utf-8 to avoid Windows encoding crashes
    sys.stdout.reconfigure(encoding='utf-8')
    
    cleaned_file = Path("data/cleaned_text.json")
    if not cleaned_file.exists():
        print(f"[-] Processed data file {cleaned_file} not found. Run inspect_data.py first.")
    else:
        with open(cleaned_file, "r", encoding="utf-8") as f:
            docs = json.load(f)
        
        print(f"[*] Loading processed documents from {cleaned_file} ...")
        chunks = chunk_all(docs)
        
        # Save chunks to data/chunked_text.json for easy user inspection
        output_file = Path("data/chunked_text.json")
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(chunks, f, indent=2, ensure_ascii=False)
        print(f"[+] Saved {len(chunks)} chunks to {output_file}")
        
        # Print a sample chunk to inspect
        if chunks:
            print("\n" + "=" * 60)
            print("SAMPLE CHUNK PREVIEW:")
            print("=" * 60)
            sample = chunks[0]
            print(f"Metadata:\n{json.dumps(sample['metadata'], indent=2)}")
            print("-" * 60)
            print(f"Content:\n{sample['page_content']}")
            print("=" * 60 + "\n")
