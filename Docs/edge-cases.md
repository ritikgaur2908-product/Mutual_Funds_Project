# Edge Cases & Corner Scenarios: Mutual Fund FAQ Assistant

**Project**: HDFC Mutual Fund FAQ Assistant (Facts-Only RAG)  
**Coverage**: Ingestion Pipeline · Query Pipeline · LLM · API · Scheduler · Frontend

This document catalogues all identified edge cases and corner scenarios across every system component, along with their expected behaviour and recommended handling strategy.

---

## 1. Data Ingestion & Scraping

### 1.1 URL / Network Failures

| ID | Scenario | Expected Behaviour |
|---|---|---|
| `ING-01` | A Groww URL returns HTTP 4xx (e.g., 404 — page removed) | Log error, skip that URL, continue with remaining 6 URLs. Do NOT abort the pipeline. |
| `ING-02` | A Groww URL returns HTTP 5xx (server error) | Retry up to 3 times with exponential backoff. If still failing, skip and log. |
| `ING-03` | Network timeout during scrape (no response within 30s) | Timeout the request, log the failure, skip URL and proceed. |
| `ING-04` | SSL/TLS certificate error for a URL | Log warning, skip URL. Do not bypass certificate validation. |
| `ING-05` | All 7 URLs fail in a single daily scheduler run | Log critical failure, keep the existing vector DB data intact (do NOT wipe old data). Alert via console/log. |
| `ING-06` | Groww blocks the scraper with a CAPTCHA or bot-detection wall | Detect empty/minimal response body, log as blocked, skip. Consider rotating User-Agent headers. |
| `ING-07` | Redirect chain (URL redirects to a different scheme page) | Follow up to 5 redirects. If the final destination URL is unrecognised, log a warning but still process the content. |

---

### 1.2 Page Content Issues

| ID | Scenario | Expected Behaviour |
|---|---|---|
| `ING-08` | Scraper retrieves empty page body (0 bytes or only whitespace) | Detect empty content after cleaning, skip chunking, log warning. |
| `ING-09` | Page is JavaScript-rendered and `httpx` returns a blank content area | Automatically fall back to Playwright headless browser for that URL. |
| `ING-10` | Page structure changes (Groww redesigns — key data fields move) | Cleaner extracts whatever text is available. Downstream retrieval may return poor results. Log content length to detect degradation. |
| `ING-11` | Scheme data is temporarily unavailable (e.g., NAV suspended, fund closed) | Scrape and store the available static content. Absence of NAV/returns data will cause "not available in current sources" responses for those specific queries. |
| `ING-12` | Page contains only images (e.g., scanned documents with no selectable text) | Text extraction yields empty content. Log as image-only page, skip indexing for that URL. |
| `ING-13` | Non-English content on the page (Gujarati, Hindi sections) | Include as-is in the cleaned text. Embedding models handle multi-lingual content. Responses may still be in English if the LLM translates internally. |

---

### 1.3 Cleaning & Chunking Edge Cases

| ID | Scenario | Expected Behaviour |
|---|---|---|
| `ING-14` | An HTML table has merged cells (`colspan` / `rowspan`) | Flatten to the best Markdown approximation, note in chunk metadata that table may be imprecise. |
| `ING-15` | A table has no header row | Use row index as column label (e.g., `Col_1`, `Col_2`). Store as-is. |
| `ING-16` | Chunk size exceeds maximum token limit of the embedding model | Further split the chunk at the nearest sentence boundary. Always respect the model's token limit. |
| `ING-17` | A single piece of content is shorter than the minimum meaningful length (< 30 chars) | Drop the chunk. These are typically navigation artifacts or stray labels. |
| `ING-18` | Duplicate content across two URLs (e.g., same section appears on two scheme pages) | Both chunks are stored independently with their respective `source_url` metadata. Deduplication is NOT applied at ingestion — retrieval will naturally surface the most relevant one. |
| `ING-19` | Chunker produces zero chunks for a cleaned document | Log warning, skip embedding step for that document. |

---

## 2. Embedding & Vector Store

| ID | Scenario | Expected Behaviour |
|---|---|---|
| `EMB-01` | Gemini Embedding API is unavailable or rate-limited | Retry with exponential backoff. If still failing, log error and fail query/ingestion gracefully (no local model fallback due to Python 3.14 Windows library constraints). |
| `EMB-02` | Embedding API returns a null or malformed vector | Retry once. If still failing, skip that chunk and log. Do not store a null vector. |
| `EMB-03` | Vector store persistence directory does not exist on first run | Auto-create the directory defined in `CHROMA_PERSIST_DIR`. |
| `EMB-04` | Vector store data files are corrupted or unreadable at startup | Log warning and start with a fresh empty collection. API `/health` endpoint should return `503` if no data is available. |
| `EMB-05` | Daily re-index runs while a user query is in flight | The pure-Python vector store operates in-memory; re-indexing replaces the full collection atomically after embedding completes. Queries during embedding generation may use stale data. |
| `EMB-06` | Vector store grows very large over time (though unlikely given fixed 7 URLs) | Daily run clears and re-inserts all documents — collection size stays bounded. |
| `EMB-07` | Embedding dimensionality mismatch (e.g., switching embedding models mid-project) | Delete the vector store persistence files (JSON + .npy) and re-embed everything with the new model. Document this as a breaking migration step. |

---

## 3. Query Pipeline — PII Filter

| ID | Scenario | Expected Behaviour |
|---|---|---|
| `PII-01` | User sends a PAN number in the query (e.g., "ABCDE1234F") | PAN is replaced with `[REDACTED]`. Sanitised query is processed normally. |
| `PII-02` | User sends an Aadhaar number | Replaced with `[REDACTED]`. |
| `PII-03` | User sends their email address or phone number | Replaced with `[REDACTED]`. |
| `PII-04` | User sends an OTP within the query | Replaced with `[REDACTED]`. |
| `PII-05` | Redacting PII leaves the query semantically meaningless (e.g., query was only a PAN number) | After redaction, query is too short/meaningless to process. Return a generic message: *"Please provide a question about mutual fund schemes."* |
| `PII-06` | A legitimate financial number (e.g., "₹5000 SIP") is misidentified as a PAN/account number | Use precise, anchored regex patterns to minimise false positives. Test regex thoroughly against real query samples. |
| `PII-07` | User query contains PII mixed with the actual question | Only the PII token is redacted; the rest of the query passes through normally. |

---

## 4. Query Pipeline — Intent Classifier

| ID | Scenario | Expected Behaviour |
|---|---|---|
| `INT-01` | Query is clearly factual (e.g., *"What is the exit load?"*) | Classified as `factual`, routed to retriever. |
| `INT-02` | Query is clearly advisory (e.g., *"Should I invest in HDFC Mid Cap?"*) | Classified as `advisory`, routed to Refusal Handler. |
| `INT-03` | Ambiguous query (e.g., *"Is HDFC Mid Cap a good fund?"*) | Keyword filter may not catch it. LLM fallback classifier is invoked. LLM should classify as `advisory` (contains evaluative language). |
| `INT-04` | Mixed query — factual + advisory in one message (e.g., *"What is the expense ratio and should I buy it?"*) | Classify the entire message as `advisory` (conservative approach — safety takes priority). Refusal Handler responds with the educational link. |
| `INT-05` | LLM classifier API is down/rate-limited | Fall back to `factual` classification if no advisory keywords are detected by the keyword filter. Log the fallback. |
| `INT-06` | Extremely short query (e.g., *"SIP?"* or *"?"*) | Classified as `factual` (no advisory signal). Retrieval likely returns poor matches. Response will state information is unavailable. |
| `INT-07` | Query in a language other than English | Process as-is. Embedding model handles multilingual queries. Response will be in English (LLM default). |
| `INT-08` | Query is purely gibberish or random characters | No advisory keywords detected. Routes to retriever. Retrieval will return low-confidence matches, resulting in *"information not available"* response. |

---

## 5. Retrieval Module

| ID | Scenario | Expected Behaviour |
|---|---|---|
| `RET-01` | Query returns zero matching chunks from the vector store (similarity score below threshold) | Return a *"This information is not available in my current sources."* response. Do NOT pass empty context to the LLM. |
| `RET-02` | Query returns chunks from multiple scheme pages (e.g., a generic question like *"What is an exit load?"*) | Return top-3 chunks by RRF score. Prompt builder attaches all three with their respective source URLs. LLM selects the most relevant single citation. |
| `RET-03` | BM25 index is empty (e.g., on first run before ingestion completes) | Fall back to semantic-only retrieval. Log warning. |
| `RET-04` | Retrieved chunks are stale (daily scheduler hasn't run yet and source page updated) | Chunks will reflect the previous day's data. The `last_updated` footer will display the correct scrape date, making staleness transparent to the user. |
| `RET-05` | All retrieved chunks have very low cosine similarity scores (< 0.3) | Apply a minimum similarity threshold. If all results fall below it, treat as zero-match scenario (`RET-01`). |
| `RET-06` | User asks about a fund not in the corpus (e.g., *"What is the expense ratio of HDFC Flexi Cap Fund?"*) | Retrieval finds no matching chunks. Response: *"This information is not available in my current sources. The assistant covers only the following 7 schemes: [list]."* |
| `RET-07` | Reranker model is unavailable | Skip reranking step, use RRF-fused top-3 chunks directly. Log the fallback. |

---

## 6. LLM Response Generation

| ID | Scenario | Expected Behaviour |
|---|---|---|
| `LLM-01` | Gemini API is unavailable or returns a 5xx error | Retry once. If still failing, return a friendly error: *"The assistant is temporarily unavailable. Please try again shortly."* |
| `LLM-02` | Gemini API returns a rate-limit error (429) | Implement exponential backoff with jitter. Retry up to 3 times. If all retries exhausted, return the unavailability message. |
| `LLM-03` | LLM response exceeds 3 sentences | Post-processing formatter truncates to 3 sentences at the nearest full stop. |
| `LLM-04` | LLM includes more than one source URL in the response | Formatter strips all URLs except the first valid one. |
| `LLM-05` | LLM ignores the system prompt and provides investment advice | Formatter applies a regex check for advisory keywords in the output. If detected, discard the response and return the refusal message instead. |
| `LLM-06` | LLM hallucinates a source URL not present in the retrieved chunks | Formatter validates the citation URL against the list of `source_url` values in the retrieved chunks. Replace with the most relevant actual chunk URL if mismatched. |
| `LLM-07` | LLM says "I don't know" or equivalent | Acceptable. Formatter ensures the footer is still appended: *"Last updated from sources: <date>."* |
| `LLM-08` | LLM response is empty or null | Treat as `LLM-01` scenario — return the unavailability message. |
| `LLM-09` | Context chunks passed to LLM exceed its context window limit | Trim chunks to fit within the model's maximum context window (prioritise highest-ranked chunks). |
| `LLM-10` | The answer exists in the corpus but LLM fails to extract it from context | The response will be suboptimal but factually grounded. Log for future prompt tuning. |

---

## 7. API Backend

| ID | Scenario | Expected Behaviour |
|---|---|---|
| `API-01` | `/query` request has an empty `message` field | Return `422 Unprocessable Entity` with message: *"Query cannot be empty."* |
| `API-02` | `/query` request body is malformed JSON | Return `400 Bad Request`. |
| `API-03` | `/query` message is excessively long (e.g., > 2000 characters) | Truncate to 2000 characters before processing, or return `413 Payload Too Large` with a maximum length advisory. |
| `API-04` | `/health` called when the vector store files are missing or unreadable | Return `503 Service Unavailable` with `{"status": "unhealthy", "vector_db": "unreachable"}`. |
| `API-05` | `/refresh` endpoint is called while a daily scheduler run is already in progress | Queue the refresh request to run after the active run completes, or reject with `409 Conflict`. |
| `API-06` | Simultaneous burst of user requests (high concurrency) | FastAPI with `uvicorn` handles async requests natively. Add a request queue or rate-limiter if concurrency causes API latency to spike. |
| `API-07` | `GEMINI_API_KEY` environment variable is missing at startup | App should fail fast with a clear error message: *"GEMINI_API_KEY is not configured. Set it in .env."* Do not start the server. |

---

## 8. Daily Scheduler

| ID | Scenario | Expected Behaviour |
|---|---|---|
| `SCH-01` | Scheduler fails to trigger (GitHub Actions runner/trigger failure) | Log the missed trigger. The vector DB retains the previous day's data and continues serving queries. |
| `SCH-02` | Scheduler runs successfully but all 7 URLs return empty content | Old vector DB data is preserved (do not wipe before confirming new data was successfully embedded). |
| `SCH-03` | Scraping partially succeeds (4 of 7 URLs succeed) | Update vector DB for the 4 successful URLs only. The remaining 3 retain previous data. Log which URLs succeeded and which failed. |
| `SCH-04` | Machine restarts mid-scheduler run | If a run is aborted or the runner shuts down, GitHub Actions will trigger on the next scheduled cron or a manual trigger. |
| `SCH-05` | Scheduler triggers while the server is processing a burst of user queries | Scraping and embedding run asynchronously in a background thread/task. Live queries continue uninterrupted. |
| `SCH-06` | Groww updates scheme data multiple times in a single day | The scheduler runs once daily; intraday updates are not captured. This is a known limitation and should be documented in the README. |
| `SCH-07` | Timezone mismatch (scheduler set to UTC but machine is IST) | Ensure the GitHub Actions cron expression runs at the desired time (which is always in UTC). |

---

## 9. Frontend UI

| ID | Scenario | Expected Behaviour |
|---|---|---|
| `UI-01` | User submits an empty input | Disable the Send button or show inline validation: *"Please enter a question."* |
| `UI-02` | User rapidly clicks Send multiple times | Disable Send button after first click until the response is received. |
| `UI-03` | API call times out from the frontend (no response in > 15 seconds) | Show a timeout message: *"The assistant is taking too long. Please try again."* |
| `UI-04` | API returns a 5xx error | Show user-friendly error card: *"Something went wrong. Please try again shortly."* |
| `UI-05` | Long response text overflows the card layout | Use CSS `word-break: break-word` and scrollable card containers. |
| `UI-06` | Source URL in the response is broken or returns 404 when clicked | The link is rendered as-is. The system does not validate citation URLs at render time. Log broken links separately. |
| `UI-07` | User pastes a very long query (e.g., copy-pastes a full article) | Frontend enforces a character limit (e.g., 2000 chars) on the input field. Remaining characters are truncated client-side. |
| `UI-08` | User uses the app on mobile (small screen) | UI must be responsive. All elements should stack vertically. Tested at 375px viewport. |
| `UI-09` | User clicks an example question while a previous query is still loading | Disable example question buttons while a query is in flight. |

---

## 10. Compliance & Content Edge Cases

| ID | Scenario | Expected Behaviour |
|---|---|---|
| `COM-01` | User asks for a performance comparison between two schemes | Classified as `advisory` (comparative/evaluative). Refusal Handler responds with AMFI educational link. |
| `COM-02` | User asks about a return forecast or expected NAV | Classified as `advisory`. Refusal Handler responds. |
| `COM-03` | User asks about tax implications (e.g., *"How much tax will I pay?"*) | Borderline. Classify as `advisory` (personalised financial calculation). Provide an AMFI/SEBI educational link instead. |
| `COM-04` | User asks a legitimate factual question about ELSS tax benefits (e.g., *"What is the ELSS lock-in period?"*) | Classified as `factual`. Retrieve and return the 3-year lock-in fact with citation. Not advisory. |
| `COM-05` | A retrieved chunk inadvertently contains performance data (e.g., past 1-year returns in a table) | The LLM system prompt explicitly forbids performance comparisons. The LLM should avoid surfacing return data even if present in context. |
| `COM-06` | User asks *"Is HDFC Mutual Fund SEBI registered?"* — fund house factual data | Classified as `factual`. Retriever looks for HDFC AMC fund house page chunk. Answer with SEBI registration fact + citation. |
| `COM-07` | User asks a question about a scheme not covered by the 7 URLs | Response states the out-of-scope limitation and lists the 7 covered schemes. |

---

## Summary Checklist

All edge cases should be validated during Phase 3 (Query Pipeline) and Phase 4 (API) testing before moving to Phase 5 (Frontend):

- `[ ]` All `ING-` cases covered in scraper and cleaner unit tests.
- `[ ]` All `EMB-` cases covered in embedder integration tests.
- `[ ]` All `PII-` cases covered with a regex test suite.
- `[ ]` All `INT-` cases covered in intent classifier tests with labelled query samples.
- `[ ]` All `RET-` cases covered in retrieval integration tests against the live vector DB.
- `[ ]` All `LLM-` cases covered in prompt/response formatter unit tests with mocked LLM responses.
- `[ ]` All `API-` cases verified with `pytest` + `httpx` against the FastAPI test client.
- `[ ]` All `SCH-` cases documented in README as known limitations or tested with mock scheduler triggers.
- `[ ]` All `UI-` cases manually tested in Chrome, Firefox, and Safari at desktop and mobile viewports.
- `[ ]` All `COM-` compliance cases included in the integration test matrix (Phase 5.2).
