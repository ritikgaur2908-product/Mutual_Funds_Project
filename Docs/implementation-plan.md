# Implementation Plan: Mutual Fund FAQ Assistant (Facts-Only Q&A)

**Project**: HDFC Mutual Fund FAQ Assistant using RAG  
**Reference Product**: Groww  
**AMC in Scope**: HDFC Mutual Fund  
**Data Sources**: 7 Groww scheme URLs + official AMC/AMFI/SEBI pages  

---

## Overview

This implementation plan breaks the project into **5 sequential phases**, each building on the previous one. The plan covers environment setup, data ingestion and preprocessing, RAG pipeline construction, API backend, frontend UI, and scheduler setup — with clear deliverables and testing checkpoints at each stage.

---

## Phase 1: Project Setup & Environment Configuration

**Goal**: Establish the project skeleton, directory structure, tooling, and dependency management.

### 1.1 Directory Structure

```
grow/
├── Docs/
│   ├── problemStatement.md
│   ├── architecture.md
│   └── implementation-plan.md
├── ingestion/
│   ├── scraper.py              # URL scraper using BeautifulSoup4 / Playwright
│   ├── cleaner.py              # Data cleaning & normalization
│   └── chunker.py              # Semantic/recursive text chunker
├── .github/
│   └── workflows/
│       └── reindex.yml         # Daily re-indexing GitHub Actions workflow
├── embeddings/
│   ├── embedder.py             # Embedding model wrapper
│   └── vector_store.py         # ChromaDB / LanceDB interface
├── retrieval/
│   ├── retriever.py            # Hybrid retrieval (BM25 + semantic)
│   └── reranker.py             # Optional: cross-encoder reranking
├── query/
│   ├── pii_filter.py           # PII detection and stripping
│   ├── intent_classifier.py    # Factual vs advisory classification
│   └── refusal_handler.py      # Polite refusal with AMFI/SEBI links
├── llm/
│   ├── prompt_builder.py       # Context-aware prompt constructor
│   └── response_formatter.py   # Output formatter (3 sentences, citation, footer)
├── api/
│   └── main.py                 # FastAPI application entry point
├── frontend/
│   ├── index.html
│   ├── style.css
│   └── app.js
├── tests/
│   ├── test_scraper.py
│   ├── test_cleaner.py
│   ├── test_retrieval.py
│   ├── test_query_pipeline.py
│   └── test_refusal.py
├── .env                        # API keys (Gemini API, etc.)
├── requirements.txt
├── run_ingestion.py            # Standalone ingestion runner
└── README.md
```

### 1.2 Tech Stack

| Layer | Tool / Library |
|---|---|
| Language | Python 3.11+ |
| Web Scraping | `BeautifulSoup4`, `httpx`, `Playwright` (for JS-rendered pages) |
| Data Cleaning | `lxml`, `html2text`, custom regex pipeline |
| Chunking | `LlamaIndex` (`SentenceSplitter`) or LangChain `RecursiveCharacterTextSplitter` |
| Embedding | `google-generativeai` (Gemini embedding - `models/text-embedding-004`) |
| Vector Store | Pure-Python vector store (NumPy + JSON persistence) |
| Keyword Search | `rank-bm25` |
| LLM | Groq API (Llama 3.1 8B) |
| Backend | `FastAPI`, `uvicorn` |
| Scheduler | GitHub Actions scheduled workflow |
| Frontend | Vanilla HTML, CSS, JavaScript |
| Testing | `pytest` |

### 1.3 Steps

1. Create the project directory structure as outlined above.
2. Initialize `requirements.txt` with all dependencies.
3. Create `.env` file with placeholders for:
   - `GEMINI_API_KEY`
   - `CHROMA_PERSIST_DIR`
4. Write a base `README.md` with:
   - Project purpose and disclaimer
   - Setup instructions
   - Selected AMC and 7 scheme URLs
   - Architecture overview reference
   - Known limitations section

### 1.4 Deliverables

- `[ ]` Project directory structure created.
- `[ ]` `requirements.txt` populated.
- `[ ]` `.env` configured.
- `[ ]` Base `README.md` written.

---

## Phase 2: Data Ingestion, Cleaning & Indexing Pipeline

**Goal**: Build the full offline pipeline to scrape, clean, chunk, embed, and store data from the 7 designated Groww HDFC fund pages.

### 2.1 Scraper (`ingestion/scraper.py`)

**Inputs**: List of 7 target URLs.  
**Output**: Raw HTML / plain text + metadata per URL.

**Steps**:
1. For each of the 7 Groww URLs, use `httpx` to fetch the page HTML.
   - If the page is JS-rendered (check if content loads dynamically), fall back to `Playwright` headless browser.
2. Extract the full HTML body content.
3. Capture metadata:
   - `source_url`: original URL
   - `scheme_name`: extracted from page title or heading
   - `scraped_at`: UTC timestamp of scraping

**Target URLs**:
- `https://groww.in/mutual-funds/hdfc-silver-etf-fof-direct-growth`
- `https://groww.in/mutual-funds/hdfc-mid-cap-fund-direct-growth`
- `https://groww.in/mutual-funds/hdfc-equity-fund-direct-growth`
- `https://groww.in/mutual-funds/hdfc-small-cap-fund-direct-growth`
- `https://groww.in/mutual-funds/hdfc-defence-fund-direct-growth`
- `https://groww.in/mutual-funds/hdfc-gold-etf-fund-of-fund-direct-plan-growth`
- `https://groww.in/mutual-funds/hdfc-nifty-50-index-fund-direct-growth`

> **Note**: Also scrape HDFC AMC fund house data page for fund house-level queries (AUM, inception year, registrar info, etc.)

### 2.2 Data Cleaning (`ingestion/cleaner.py`)

**Input**: Raw HTML string + metadata.  
**Output**: Clean plain-text string + metadata.

**Steps**:
1. **Boilerplate Removal**: Use `BeautifulSoup4` to remove `<nav>`, `<header>`, `<footer>`, `<aside>`, `<script>`, `<style>`, cookie banners, ad placeholders, and social media buttons.
2. **Table Extraction**: Before stripping HTML, identify all `<table>` elements. Convert them into Markdown table strings using a helper function (or `markdownify`).
3. **HTML to Text**: Convert the cleaned HTML to plain text using `html2text` or `BeautifulSoup.get_text()` with a newline separator.
4. **Text Normalization**:
   - Collapse multiple whitespace/newlines to a single newline.
   - Decode HTML entities (e.g., `&amp;` → `&`, `₹` → `₹`).
   - Standardize date formats (e.g., `01 Jun 2025` → `2025-06-01`).
   - Standardize currency formats (e.g., `Rs.` → `₹`).
5. **Empty/Junk Filter**: Drop any text sections shorter than 30 characters (likely nav artifacts).
6. Attach the cleaned content back to the metadata dict.

### 2.3 Chunker (`ingestion/chunker.py`)

**Input**: Cleaned plain-text + metadata (including `structured_data`).  
**Output**: List of text chunks, each with metadata and a context prefix.

**Strategy**:
1. **Semantic Section Splitting**: Divide the text based on logical headers (e.g., `### Exit load...`, `### About [Fund Name]...`, `Mr. [Manager Name]...`).
2. **Atomic Table Preservation**: Keep Markdown tables (`| ... |` rows) intact. If a table exceeds size constraints, split it strictly by row boundary (`\n`), never splitting a row in half.
3. **Recursive Character Splitter (Fallback)**: For large blocks of text, use `RecursiveCharacterTextSplitter` with `chunk_size = 1200 characters` and `chunk_overlap = 150 characters`.
4. **Context Prefixing**: Prepends each chunk with the fund name and structured metadata (e.g., `Document: <scheme_name> (AUM: <aum> | Expense Ratio: <expense_ratio> | Risk: <risk_rating>)\n---\n`).
5. **Metadata Enrichment**: Each chunk carries inherited metadata:
   - `source_url`, `scheme_name`, `last_updated` (scraped_at)
   - `expense_ratio`, `exit_load`, `minimum_sip`, `risk_rating`, `benchmark`, `aum`, `nav` (from `structured_data`)
   - `chunk_index` (sequential position in the document)

### 2.4 Embedder & Vector Store (`embeddings/`)

**Steps**:
1. **Embedding Generation**: For each chunk, generate a dense vector embedding (768 dimensions) using the **Gemini Embedding API** with the model **`models/text-embedding-004`** (running under the generous free tier of up to 1,500 RPM).
   > [!IMPORTANT]
   > Due to binary library load failures on Windows with Python 3.14, local model libraries (like `sentence-transformers` or `onnxruntime`) are disabled. The RAG pipeline relies fully on the Gemini Embedding API.
2. **Python 3.14 Import Workaround**: Because the protobuf C-extension is incompatible with Python 3.14, include the following code block at the entry point of any files importing `google.generativeai`:
   ```python
   import sys
   sys.modules['google._upb._message'] = None
   ```
3. **Storage in Pure-Python Vector Store (NumPy + JSON)**:
   > [!NOTE]
   > ChromaDB's Rust backend (`chromadb_rust_bindings`) crashes with an access violation on Python 3.14 Windows. We use a lightweight pure-Python vector store instead, providing identical functionality with zero compiled dependencies.
   - Collection name: `hdfc_mutual_fund_docs`
   - Cosine similarity search using NumPy dot products
   - Metadata filtering support (e.g., filter by `scheme_name`)
   - Persistence via JSON (metadata) + `.npy` (embeddings) files in the `CHROMA_PERSIST_DIR` directory
   - Store the chunk text under `page_content` and include the full metadata dictionary (`source_url`, `scheme_name`, `last_updated`, `expense_ratio`, `exit_load`, `minimum_sip`, `minimum_lumpsum`, `risk_rating`, `benchmark`, `aum`, `nav`).
4. **Data Synchronization**: On re-runs (triggered by the scheduler or manual refresh), clear existing records and re-insert the newly chunked data to prevent duplicate or stale entries.

### 2.5 Deliverables

- `[x]` `scraper.py` — fetches all 7 URLs and HDFC AMC fund house page.
- `[x]` `cleaner.py` — full boilerplate removal, table preservation, text normalization.
- `[x]` `chunker.py` — splits text to chunks with metadata, preserves tables as atomic units.
- `[x]` `embedder.py` + `vector_store.py` — embeds chunks via Gemini API and persists into NumPy vector store.
- `[ ]` Manual run of full pipeline verified, vector store populated.
- `[ ]` Unit tests for scraper, cleaner, and chunker.

---

## Phase 3: Query Pipeline — Guardrails, Retrieval & LLM Response

**Goal**: Build the real-time query processing pipeline covering PII filtering, intent classification, hybrid retrieval, and LLM answer generation.

### 3.1 PII Filter (`query/pii_filter.py`)

**Input**: Raw user query string.  
**Output**: Sanitized query string (PII replaced with `[REDACTED]`).

**Patterns to detect and redact**:
- PAN: `[A-Z]{5}[0-9]{4}[A-Z]`
- Aadhaar: `\d{4}[\s-]?\d{4}[\s-]?\d{4}`
- Account numbers: sequences of 10–18 digits
- Email: standard email regex
- Phone: Indian phone number patterns
- OTP: 4–8 consecutive digit sequences

If any PII is detected, log a warning and return the sanitized query.

### 3.2 Intent Classifier (`query/intent_classifier.py`)

**Input**: Sanitized user query.  
**Output**: `"factual"` or `"advisory"` classification label.

**Approach — Keyword-Based + LLM Hybrid**:
1. **Fast keyword filter**: If the query contains advisory trigger words/phrases (`should I`, `better fund`, `recommend`, `invest in`, `which is best`, `compare`, `return forecast`), immediately classify as `"advisory"`.
2. **LLM fallback** (for ambiguous queries): Send a lightweight classification prompt to Gemini Flash asking it to classify the query as `"factual"` or `"advisory"`. This adds ~100ms latency but ensures accuracy for edge cases.

### 3.3 Refusal Handler (`query/refusal_handler.py`)

Triggered when intent = `"advisory"`.

**Response format**:
```
I can only provide factual information about mutual fund schemes and cannot offer investment advice or recommendations.

For investor education, please visit:
→ AMFI Investor Education: https://www.amfiindia.com/investor-corner
→ SEBI Investor Education: https://investor.sebi.gov.in
```

### 3.4 Hybrid Retrieval (`retrieval/retriever.py`)

Triggered when intent = `"factual"`.

**Steps**:
1. **Semantic Search**: Convert the user query to an embedding using the same embedding model. Query ChromaDB for the top-10 nearest chunks by cosine similarity.
2. **BM25 Keyword Search**: Using `rank-bm25`, run a keyword search over all stored document chunks to retrieve top-10 BM25 results.
3. **Result Fusion**: Merge both result sets using **Reciprocal Rank Fusion (RRF)** to produce a unified top-5 ranked list.
4. **Optional Reranking** (`retrieval/reranker.py`): Apply a cross-encoder (e.g., `BAAI/bge-reranker-base`) to re-score the fused top-5 and return the final top-3 chunks to pass to the LLM.

### 3.5 Prompt Builder (`llm/prompt_builder.py`)

Constructs the final LLM prompt by combining:

```
SYSTEM:
You are a facts-only mutual fund information assistant for Groww users.
You MUST answer using ONLY the provided context below.
Do NOT use any external knowledge, make assumptions, or provide investment advice.
If the answer is not present in the context, say: "This information is not available in my current sources."
Limit your response to a maximum of 3 sentences.
Always end with the citation and footer as instructed.

CONTEXT:
[Chunk 1 text] — Source: [source_url] — Last Updated: [last_updated]
[Chunk 2 text] — Source: [source_url] — Last Updated: [last_updated]
[Chunk 3 text] — Source: [source_url] — Last Updated: [last_updated]

USER QUESTION:
[sanitized user query]

RESPONSE FORMAT:
Answer: <your factual answer in max 3 sentences>
Source: <single source URL most relevant to the answer>
Last updated from sources: <date of most recent chunk used>
```

### 3.6 Response Formatter (`llm/response_formatter.py`)

**Steps**:
1. Parse the raw LLM response to extract `Answer`, `Source`, and `Last updated from sources` fields.
2. Validate:
   - Response is ≤ 3 sentences.
   - Exactly one source URL is present.
   - Footer with date is present.
3. If the LLM response does not conform, apply post-processing to enforce constraints.
4. Return a structured JSON response:

```json
{
  "answer": "...",
  "source_url": "https://...",
  "last_updated": "YYYY-MM-DD",
  "query_type": "factual"
}
```

### 3.7 Deliverables

- `[ ]` `pii_filter.py` with regex rules for PAN, Aadhaar, account numbers, email, phone, OTPs.
- `[ ]` `intent_classifier.py` with keyword rules + LLM fallback.
- `[ ]` `refusal_handler.py` with polite refusal + AMFI/SEBI links.
- `[ ]` `retriever.py` with hybrid BM25 + semantic search + RRF fusion.
- `[ ]` `prompt_builder.py` with strict system prompt template.
- `[ ]` `response_formatter.py` with validation and JSON output.
- `[ ]` End-to-end query test: factual query, advisory query, edge cases.

---

## Phase 4: API Backend

**Goal**: Expose the query pipeline via a REST API.

### 4.1 FastAPI Application (`api/main.py`)

**Endpoints**:

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/health` | Health check — confirms API and vector DB are live. |
| `POST` | `/query` | Main query endpoint. Accepts user message, returns structured answer. |
| `POST` | `/refresh` | Manually trigger the ingestion pipeline (admin-protected). |

**`POST /query` Request Schema**:
```json
{
  "message": "What is the expense ratio of HDFC Mid Cap Fund?"
}
```

**`POST /query` Response Schema**:
```json
{
  "answer": "The expense ratio of HDFC Mid-Cap Opportunities Fund (Direct Plan) is 0.73% per annum.",
  "source_url": "https://groww.in/mutual-funds/hdfc-mid-cap-fund-direct-growth",
  "last_updated": "2026-06-04",
  "query_type": "factual"
}
```

**Error Handling**:
- `422 Unprocessable Entity` for malformed requests.
- `503 Service Unavailable` if the vector DB is unreachable.
- All errors logged to `app.log`.

### 4.2 Deliverables

- `[x]` `api/main.py` with `/health`, `/query`, `/refresh` endpoints.
- `[x]` API unit tests in `tests/test_api.py`.
- `[x]` Error handling and logging verified.

---

## Phase 5: Frontend UI & Integration

**Goal**: Build the chat UI, connect it to the FastAPI backend, and perform end-to-end validation.

### 5.1 Frontend UI (`frontend/`)

**Design Requirements**:
- Welcome message at the top.
- Three pre-filled example questions clickable as quick starters:
  1. *"What is the exit load for HDFC Small Cap Fund?"*
  2. *"What is the minimum SIP amount for HDFC Nifty 50 Index Fund?"*
  3. *"Tell me about HDFC Mutual Fund as a fund house."*
- A persistent disclaimer banner at the top:
  > ⚠️ **Facts-only. No investment advice.**
- Chat input box at the bottom with a Send button.
- Response cards displaying:
  - Answer text.
  - Source citation link (clickable).
  - "Last updated from sources: `<date>`" footer.
- If a refusal is returned, display the response in a distinct styled card with educational links.

**File Plan**:

| File | Purpose |
|---|---|
| `index.html` | Page structure with chat window, disclaimer, example questions |
| `style.css` | Styling (clean, premium, accessible, responsive) |
| `app.js` | Fetch calls to `/query`, dynamic DOM rendering of response cards |

### 5.2 End-to-End Integration Testing

| Test Case | Expected Outcome |
|---|---|
| *"What is the expense ratio of HDFC Equity Fund?"* | Factual answer + source URL + last updated date |
| *"What is the ELSS lock-in period?"* | Factual answer noting 3-year lock-in + citation |
| *"What is the benchmark of HDFC Defence Fund?"* | Benchmark index name + source URL |
| *"Should I invest in HDFC Mid Cap Fund?"* | Polite refusal + AMFI/SEBI educational links |
| *"Which fund is better?"* | Polite refusal (advisory intent detected) |
| *"Tell me about HDFC Mutual Fund."* | Fund house facts (AUM, inception, etc.) + source |
| Query containing a PAN number | PII stripped, sanitized query processed |
| Query with no matching context | "Information not available in current sources" |

### 5.3 Deliverables

- `[ ]` `index.html` with welcome message, disclaimer, example questions, chat input.
- `[ ]` `style.css` with clean premium styling.
- `[ ]` `app.js` with fetch calls to backend and dynamic card rendering.
- `[ ]` All integration test cases verified manually.
- `[ ]` README updated with frontend setup and how to run locally.

---

## Phase 6: Daily Ingestion Scheduler

**Goal**: Automate daily data refresh using a scheduled GitHub Actions workflow instead of in-process application loops. This makes hosting on stateless and serverless environments (like Vercel and Railway Free Tier) possible.

### 6.1 GitHub Actions Workflow (`.github/workflows/reindex.yml`)

**Tool**: GitHub Actions scheduled cron runner + standalone `run_ingestion.py` script.

**Schedule**: Every day at **04:30 UTC** (10:00 AM IST), or via manual trigger (`workflow_dispatch`), run the full ingestion pipeline:

```
1. Run run_ingestion.py inside GitHub Actions runner.
   a. Run scraper.py for all 7 Groww URLs + HDFC AMC page.
   b. Run cleaner.py to parse AMC scheme details and clean HTML.
   c. Run chunker.py to split cleaned documents.
   d. Re-embed chunks and index into the vector store database (writing hdfc_mutual_fund_docs_meta.json and _embeddings.npy).
2. Configure git credentials.
3. Commit and push any changes in the chroma_db/ folder back to main.
4. Platforms like Vercel and Railway detect the new commit on main and trigger stateless redeployment of the API server.
```

### 6.2 Deliverables

- `[x]` Standalone `run_ingestion.py` script in the root directory.
- `[x]` GitHub Actions workflow `.github/workflows/reindex.yml` configured and tested.
- `[x]` `.gitignore` modified to track `chroma_db/` folder in git.

---

## Summary Table

| Phase | Focus | Key Output |
|---|---|---|
| **Phase 1** | Setup & Structure | Project skeleton, requirements, README |
| **Phase 2** | Ingestion Pipeline | Scraper → Cleaner → Chunker → Vector DB |
| **Phase 3** | Query Pipeline | PII Filter → Classifier → Retriever → LLM → Formatter |
| **Phase 4** | API Backend | FastAPI endpoints `/health`, `/query`, `/refresh` |
| **Phase 5** | UI & Integration | Chat frontend + end-to-end test suite |
| **Phase 6** | Daily Scheduler | GitHub Actions daily cron refresh & redeployment |

---

## Constraints Summary

- **Data Sources**: Only the 7 specified Groww HDFC URLs + official AMC/AMFI/SEBI pages.
- **No PII Storage**: User queries are never persisted; PII is stripped before processing.
- **No Investment Advice**: Enforced at both classifier level and LLM system prompt level.
- **Response Format**: Max 3 sentences, exactly one citation, last updated footer on every factual response.
- **Scheduler**: Runs daily at 04:30 UTC (10:00 AM IST) via GitHub Actions to refresh and commit database files.
