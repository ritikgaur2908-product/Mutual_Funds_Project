"""
retriever.py
------------
Hybrid retrieval module.
Combines BM25 keyword search (rank-bm25) and semantic vector search (custom NumPy store)
using Reciprocal Rank Fusion (RRF) to return the top-3 most relevant chunks.
Includes metadata pre-filtering (query routing) to prevent cross-scheme context bleeding.
"""

import logging
import os
import re
import sys
from typing import Optional

from dotenv import load_dotenv
from rank_bm25 import BM25Okapi

# Protobuf compatibility workaround
sys.modules['google._upb._message'] = None

from embeddings.embedder import embed_query  # noqa: E402
from embeddings.vector_store import get_or_create_collection, query_collection  # noqa: E402

logger = logging.getLogger("retriever")

# ── Configuration ───────────────────────────────────────────────────────────
RRF_K: int = 60                          # RRF smoothing constant
MIN_SIMILARITY_THRESHOLD: float = 0.3    # Minimum cosine similarity (1.0 - distance)
MAX_RETRIEVED_CHUNKS: int = 3            # Number of chunks returned to prompt builder

# Query-routing scheme mapping
SCHEME_MAPPING = {
    "silver": "HDFC Silver ETF FoF Direct Growth - NAV, Mutual Fund Performance &amp; Portfolio",
    "mid cap": "HDFC Mid Cap Fund Direct Growth - NAV, Mutual Fund Performance &amp; Portfolio",
    "mid-cap": "HDFC Mid Cap Fund Direct Growth - NAV, Mutual Fund Performance &amp; Portfolio",
    "midcap": "HDFC Mid Cap Fund Direct Growth - NAV, Mutual Fund Performance &amp; Portfolio",
    "flexi": "HDFC Flexi Cap Direct Plan Growth - NAV, Mutual Fund Performance &amp; Portfolio",
    "flexicap": "HDFC Flexi Cap Direct Plan Growth - NAV, Mutual Fund Performance &amp; Portfolio",
    "flexi-cap": "HDFC Flexi Cap Direct Plan Growth - NAV, Mutual Fund Performance &amp; Portfolio",
    "equity": "HDFC Flexi Cap Direct Plan Growth - NAV, Mutual Fund Performance &amp; Portfolio",
    "small cap": "HDFC Small Cap Fund Direct Growth - NAV, Mutual Fund Performance &amp; Portfolio",
    "small-cap": "HDFC Small Cap Fund Direct Growth - NAV, Mutual Fund Performance &amp; Portfolio",
    "smallcap": "HDFC Small Cap Fund Direct Growth - NAV, Mutual Fund Performance &amp; Portfolio",
    "defence": "HDFC Defence Fund Direct Growth - NAV, Mutual Fund Performance &amp; Portfolio",
    "defense": "HDFC Defence Fund Direct Growth - NAV, Mutual Fund Performance &amp; Portfolio",
    "gold": "HDFC Gold ETF Fund of Fund Direct Plan Growth - NAV, Mutual Fund Performance &amp; Portfolio",
    "nifty": "HDFC NIFTY 50 Index Fund Direct Growth - NAV, Mutual Fund Performance &amp; Portfolio",
    "index": "HDFC NIFTY 50 Index Fund Direct Growth - NAV, Mutual Fund Performance &amp; Portfolio",
    "amc": "HDFC Mutual Fund - Latest MF Schemes, NAV, Performance &amp; Returns 2026 - Groww",
    "fund house": "HDFC Mutual Fund - Latest MF Schemes, NAV, Performance &amp; Returns 2026 - Groww",
    "fundhouse": "HDFC Mutual Fund - Latest MF Schemes, NAV, Performance &amp; Returns 2026 - Groww",
    "mutual fund": "HDFC Mutual Fund - Latest MF Schemes, NAV, Performance &amp; Returns 2026 - Groww",
}


class HybridRetriever:
    """
    Combines dense semantic vector search (Gemini embeddings) and sparse keyword search (BM25)
    with query-routing metadata pre-filtering and Reciprocal Rank Fusion (RRF).
    """

    def __init__(self):
        self.collection = None
        self.bm25 = None
        self.doc_ids = []
        self._initialized = False

    def _initialize(self) -> None:
        """Initialize the collection and build the BM25 index on first query."""
        if self._initialized:
            return

        self.collection = get_or_create_collection()
        self.doc_ids = self.collection._ids

        if self.collection.count() == 0:
            logger.warning(
                "Vector store is empty. BM25 keyword search index will be uninitialized. "
                "Ingest data first!"
            )
            # We don't mark as initialized if empty so we can retry on next query
            return

        # Tokenize documents for BM25
        tokenized_docs = [self._tokenize(doc) for doc in self.collection._documents]
        self.bm25 = BM25Okapi(tokenized_docs)
        self._initialized = True
        logger.info(f"Hybrid Retriever initialized with {len(self.doc_ids)} documents.")

    def _tokenize(self, text: str) -> list[str]:
        """Convert text into lowercase word tokens."""
        return re.findall(r"\w+", text.lower())

    def _route_query(self, query: str) -> Optional[dict]:
        """
        Determine if the query is targeted to a specific scheme and return
        the corresponding metadata filter.
        """
        query_lower = query.lower()
        for key, scheme_name in SCHEME_MAPPING.items():
            if key in query_lower:
                logger.info(f"Query routed specifically to: '{scheme_name}' (matched keyword: '{key}')")
                return {"scheme_name": scheme_name}
        return None

    def retrieve(self, query: str, n_results: int = 10) -> list[dict]:
        """
        Retrieve the top documents relevant to the query using hybrid search.

        Args:
            query: Sanitized user query string.
            n_results: Max results from each search method before fusion.

        Returns:
            List of fused document chunks, each represented as a dictionary:
              {
                "id": str,
                "page_content": str,
                "metadata": dict,
                "rrf_score": float
              }
        """
        self._initialize()

        # If still not initialized (empty db), return empty list
        if not self._initialized or len(self.doc_ids) == 0:
            logger.warning("Retrieval failed: Vector store / BM25 index is uninitialized or empty.")
            return []

        # 1. Query Routing (Metadata Pre-filtering)
        where_filter = self._route_query(query)

        # 2. Dense Semantic Search
        dense_candidates = []
        try:
            query_embedding = embed_query(query)
            # Run search with optional metadata filter
            vector_results = query_collection(
                query_embedding=query_embedding,
                n_results=n_results,
                where_filter=where_filter
            )

            # Restructure results and filter out low-confidence semantic matches
            if vector_results.get("ids") and vector_results["ids"][0]:
                for idx in range(len(vector_results["ids"][0])):
                    doc_id = vector_results["ids"][0][idx]
                    doc_text = vector_results["documents"][0][idx]
                    metadata = vector_results["metadatas"][0][idx]
                    distance = vector_results["distances"][0][idx]
                    
                    similarity = 1.0 - distance
                    if similarity < MIN_SIMILARITY_THRESHOLD:
                        # Exclude weak semantic matches (RET-05)
                        logger.debug(f"Excluding low-similarity semantic chunk {doc_id} (sim: {similarity:.4f} < {MIN_SIMILARITY_THRESHOLD})")
                        continue

                    dense_candidates.append({
                        "id": doc_id,
                        "document": doc_text,
                        "metadata": metadata,
                        "similarity": similarity
                    })
        except Exception as e:
            logger.error(f"Dense semantic search failed: {e}. Falling back to keyword search only.")

        # 3. Sparse BM25 Search
        sparse_candidates = []
        try:
            tokenized_query = self._tokenize(query)
            scores = self.bm25.get_scores(tokenized_query)

            # Apply metadata filter to candidates and pair them with scores
            bm25_scored_docs = []
            for idx, doc_id in enumerate(self.doc_ids):
                meta = self.collection._metadatas[idx]

                # Filter condition check
                if where_filter:
                    match = all(meta.get(k) == v for k, v in where_filter.items())
                    if not match:
                        continue

                # Add to candidate list if score is above 0
                if scores[idx] > 0:
                    bm25_scored_docs.append((idx, scores[idx]))

            # Rank by BM25 score descending
            bm25_scored_docs.sort(key=lambda x: x[1], reverse=True)

            # Gather top-n sparse results
            top_sparse_n = min(n_results, len(bm25_scored_docs))
            for rank in range(top_sparse_n):
                idx, score = bm25_scored_docs[rank]
                sparse_candidates.append({
                    "id": self.doc_ids[idx],
                    "document": self.collection._documents[idx],
                    "metadata": self.collection._metadatas[idx],
                    "score": float(score)
                })
        except Exception as e:
            logger.error(f"Sparse BM25 search failed: {e}. Falling back to semantic search only.")

        # If both failed or returned zero results
        if not dense_candidates and not sparse_candidates:
            logger.info("Hybrid retrieval returned 0 matches.")
            return []

        # 4. Reciprocal Rank Fusion (RRF)
        rrf_scores = {}
        doc_lookup = {}

        # Fuse dense results
        for rank, doc in enumerate(dense_candidates):
            doc_id = doc["id"]
            doc_lookup[doc_id] = doc
            rrf_scores[doc_id] = rrf_scores.get(doc_id, 0.0) + (1.0 / (RRF_K + rank + 1))

        # Fuse sparse results
        for rank, doc in enumerate(sparse_candidates):
            doc_id = doc["id"]
            doc_lookup[doc_id] = doc
            rrf_scores[doc_id] = rrf_scores.get(doc_id, 0.0) + (1.0 / (RRF_K + rank + 1))

        # Sort by final RRF score descending
        sorted_doc_ids = sorted(rrf_scores.keys(), key=lambda x: rrf_scores[x], reverse=True)

        # 5. Extract top-3 formatted chunks
        final_results = []
        for doc_id in sorted_doc_ids[:MAX_RETRIEVED_CHUNKS]:
            candidate = doc_lookup[doc_id]
            final_results.append({
                "id": doc_id,
                "page_content": candidate["document"],
                "metadata": candidate["metadata"],
                "rrf_score": rrf_scores[doc_id]
            })

        logger.info(
            f"Hybrid retrieval complete. Retrieved {len(final_results)} chunks "
            f"(where_filter={where_filter})."
        )
        return final_results


# Global retriever instance
_retriever = None


def get_retriever() -> HybridRetriever:
    """Get the global HybridRetriever instance."""
    global _retriever
    if _retriever is None:
        _retriever = HybridRetriever()
    return _retriever


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding='utf-8')
    logging.basicConfig(level=logging.INFO, format="%(name)s | %(levelname)s | %(message)s")

    retriever = get_retriever()
    
    test_queries = [
        "What is the exit load for HDFC Defence Fund?",
        "minimum SIP investment of Silver ETF",
        "Who is the fund manager of HDFC Gold ETF?",
        "Out of scope query that should fail threshold check",
    ]

    for q in test_queries:
        print(f"\n[*] Query: \"{q}\"")
        results = retriever.retrieve(q)
        print(f"[*] Retrieved {len(results)} chunks:")
        for idx, res in enumerate(results):
            print(f"  [{idx + 1}] ID: {res['id']}")
            print(f"      Score: {res['rrf_score']:.6f}")
            print(f"      Scheme: {res['metadata'].get('scheme_name')}")
            print(f"      Preview: {res['page_content'][:120].strip().replace('\n', ' ')}...")
        print("-" * 60)
