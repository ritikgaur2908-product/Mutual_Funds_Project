"""
reranker.py
-----------
Optional cross-encoder reranking module.
Uses BAAI/bge-reranker-base to rerank the top-5 fused retrieval results
and return the final top-3 chunks for the LLM.

Phase 3 implementation goes here.
"""
