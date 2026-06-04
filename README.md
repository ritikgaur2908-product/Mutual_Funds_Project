# HDFC Mutual Fund FAQ Assistant

> ⚠️ **Disclaimer: Facts-only. No investment advice.**

A lightweight **Retrieval-Augmented Generation (RAG)** FAQ assistant that answers objective, verifiable questions about HDFC Mutual Fund schemes using information retrieved exclusively from official public sources (Groww scheme pages, HDFC AMC, AMFI, SEBI).

---

## Project Purpose

This assistant allows retail investors and customer support teams to quickly look up factual mutual fund information — such as expense ratios, exit loads, minimum SIP amounts, lock-in periods, benchmark indices, riskometer classifications, and fund house details — without any investment advice or recommendations.

**The system strictly refuses:**
- Investment recommendations (*"Should I invest?"*)
- Performance comparisons (*"Which fund is better?"*)
- Return forecasts or calculations

---

## Selected AMC & Schemes in Scope

**AMC**: HDFC Mutual Fund

| Scheme | Groww URL |
|---|---|
| HDFC Silver ETF Fund of Fund | https://groww.in/mutual-funds/hdfc-silver-etf-fof-direct-growth |
| HDFC Mid-Cap Opportunities Fund | https://groww.in/mutual-funds/hdfc-mid-cap-fund-direct-growth |
| HDFC Equity Fund | https://groww.in/mutual-funds/hdfc-equity-fund-direct-growth |
| HDFC Small Cap Fund | https://groww.in/mutual-funds/hdfc-small-cap-fund-direct-growth |
| HDFC Defence Fund | https://groww.in/mutual-funds/hdfc-defence-fund-direct-growth |
| HDFC Gold ETF Fund of Fund | https://groww.in/mutual-funds/hdfc-gold-etf-fund-of-fund-direct-plan-growth |
| HDFC Nifty 50 Index Fund | https://groww.in/mutual-funds/hdfc-nifty-50-index-fund-direct-growth |

---

## Architecture Overview

The system is a modular RAG pipeline:

```
Daily Scheduler (00:00 UTC)
        |
        v
  Source Scraper (7 Groww URLs)
        |
        v
  Data Cleaner & Normaliser
        |
        v
  Semantic Chunker
        |
        v
  Embedding Model (Gemini Embedding API)
        |
        v
  Vector Store (Pure-Python NumPy Store)
        |
  [User Query]
        |
        v
  PII Filter → Intent Classifier
        |               |
   [Advisory]      [Factual]
        |               |
  Refusal Handler   Hybrid Retriever (BM25 + Semantic)
        |               |
        |          Prompt Builder
        |               |
        |          Groq Llama 3.1 LLM
        |               |
        +----→  Response Formatter → User Interface
```

For detailed architecture diagrams, see [Docs/architecture.md](Docs/architecture.md).

---

## Setup Instructions

### Prerequisites

- Python 3.11+
- A Google Gemini API key ([Get one here](https://aistudio.google.com/app/apikey))

### 1. Clone / Download the Project

```bash
cd path/to/project
```

### 2. Create a Virtual Environment

```bash
python -m venv venv

# Windows
venv\Scripts\activate

# macOS / Linux
source venv/bin/activate
```

### 3. Install Dependencies

```bash
pip install -r requirements.txt
```

### 4. Configure Environment Variables

Copy the `.env.example` file and fill in your credentials:

```bash
cp .env.example .env
```

Edit `.env`:

```env
GEMINI_API_KEY=your_gemini_api_key_here
CHROMA_PERSIST_DIR=./chroma_db
```

### 5. Run the Initial Data Ingestion

```bash
python -m ingestion.scraper
```

This will scrape all 7 Groww URLs, clean the content, chunk it, embed it, and store it in the pure-Python vector store.

### 6. Start the API Server

```bash
uvicorn api.main:app --reload --port 8000
```

### 7. Open the Frontend

Open `frontend/index.html` in your browser, or serve it locally:

```bash
python -m http.server 3000 --directory frontend
```

Navigate to `http://localhost:3000`.

---

## Project Structure

```
grow/
├── Docs/                        # Project documentation
│   ├── problemStatement.md
│   ├── architecture.md
│   ├── implementation-plan.md
│   └── edge-cases.md
├── ingestion/                   # Data ingestion pipeline
│   ├── scraper.py
│   ├── cleaner.py
│   ├── chunker.py
│   └── scheduler.py
├── embeddings/                  # Embedding & vector storage
│   ├── embedder.py
│   └── vector_store.py
├── retrieval/                   # Retrieval module
│   ├── retriever.py
│   └── reranker.py
├── query/                       # Query guardrails
│   ├── pii_filter.py
│   ├── intent_classifier.py
│   └── refusal_handler.py
├── llm/                         # LLM prompt & response
│   ├── prompt_builder.py
│   └── response_formatter.py
├── api/                         # FastAPI backend
│   └── main.py
├── frontend/                    # Minimal chat UI
│   ├── index.html
│   ├── style.css
│   └── app.js
├── tests/                       # Test suite
│   ├── test_scraper.py
│   ├── test_cleaner.py
│   ├── test_retrieval.py
│   ├── test_query_pipeline.py
│   └── test_refusal.py
├── .env                         # Environment variables (not committed)
├── .env.example                 # Template for environment variables
├── requirements.txt
└── README.md
```

---

## Running Tests

```bash
pytest tests/ -v
```

---

## API Reference

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/health` | Health check |
| `POST` | `/query` | Submit a question |
| `POST` | `/refresh` | Manually trigger data re-ingestion (admin) |

**Example query:**

```bash
curl -X POST http://localhost:8000/query \
  -H "Content-Type: application/json" \
  -d '{"message": "What is the exit load for HDFC Small Cap Fund?"}'
```

**Example response:**

```json
{
  "answer": "The HDFC Small Cap Fund has an exit load of 1% if redeemed within 1 year from the date of allotment.",
  "source_url": "https://groww.in/mutual-funds/hdfc-small-cap-fund-direct-growth",
  "last_updated": "2026-06-03",
  "query_type": "factual"
}
```

---

## Known Limitations

1. **7 schemes only**: The assistant covers only the 7 HDFC schemes listed above. Queries about other funds will return an out-of-scope message.
2. **Daily data refresh**: Data is updated once per day at 00:00 UTC. Intraday NAV/price changes are not reflected in real time.
3. **No investment advice**: By design, the system refuses all advisory, comparative, or speculative queries.
4. **Performance data**: Past returns and NAV history are intentionally excluded from responses. For performance data, users are directed to the official factsheet link.
5. **Language**: Responses are always in English regardless of the query language.
6. **Source dependency**: If Groww or HDFC AMC changes their page structure significantly, the scraper may need to be updated.

---

## Compliance & Disclaimer

This tool is built strictly for **informational and educational purposes**. It does not provide, and must not be interpreted as, financial advice, investment recommendations, or personalised financial planning guidance.

All information is retrieved from publicly available official sources and is subject to change. Always verify information directly with the AMC or a SEBI-registered financial advisor.

> **Facts-only. No investment advice.**
