"""
prompt_builder.py
-----------------
Constructs structured chat messages for the RAG LLM pipeline.
Combines system-level compliance guardrails, retrieved document context chunks,
and the sanitized user query.
"""

import logging

logger = logging.getLogger("prompt_builder")

SYSTEM_INSTRUCTIONS = (
    "You are a facts-only mutual fund information assistant for Groww users.\n"
    "You MUST answer the user's question using ONLY the provided context below.\n"
    "Do NOT use any external knowledge, make assumptions, or speculate.\n"
    "Do NOT under any circumstances provide investment advice, recommendations, suggestions, "
    "or comparison opinions (e.g., do not say a fund is 'better' or 'suitable').\n"
    "If the answer to the user's question is not explicitly present in the provided context, "
    "you MUST say exactly: \"This information is not available in my current sources.\"\n"
    "Limit your answer to a maximum of 3 sentences.\n"
    "You MUST format your output EXACTLY as follows:\n\n"
    "Answer: <your factual answer in at most 3 sentences>\n"
    "Source: <single source URL of the chunk most relevant to the answer>\n"
    "Last updated from sources: <date of the most recent chunk used, formatted as YYYY-MM-DD or ISO timestamp>\n"
)

USER_PROMPT_TEMPLATE = (
    "CONTEXT:\n"
    "{context_block}\n\n"
    "USER QUESTION:\n"
    "{query}\n\n"
    "RESPONSE FORMAT:\n"
    "Answer: <factual answer>\n"
    "Source: <source url>\n"
    "Last updated from sources: <date>"
)


def build_messages(query: str, retrieved_chunks: list[dict]) -> list[dict]:
    """
    Constructs the list of message dicts (role/content) to pass to the Groq API.

    Args:
        query: Sanitized user query string.
        retrieved_chunks: List of retrieved chunks from the retriever, each like:
                          {
                            "page_content": str,
                            "metadata": dict
                          }

    Returns:
        List of message dicts ready for chat completions.
    """
    context_lines = []
    
    for i, chunk in enumerate(retrieved_chunks):
        content = chunk["page_content"]
        meta = chunk.get("metadata", {})
        source_url = meta.get("source_url", "N/A")
        # Extract date from scraped_at timestamp (e.g. 2026-06-04T05:58:09... -> 2026-06-04)
        last_updated_raw = meta.get("last_updated", "N/A")
        last_updated = last_updated_raw.split("T")[0] if "T" in last_updated_raw else last_updated_raw
        
        context_lines.append(
            f"[Chunk {i+1}] Content:\n{content}\n"
            f"Source URL: {source_url}\n"
            f"Last Updated: {last_updated}\n"
            f"---"
        )
        
    context_block = "\n".join(context_lines) if context_lines else "No relevant context found."
    
    user_content = USER_PROMPT_TEMPLATE.format(
        context_block=context_block,
        query=query
    )
    
    logger.info(f"Built prompt messages containing {len(retrieved_chunks)} context chunks.")
    
    return [
        {"role": "system", "content": SYSTEM_INSTRUCTIONS},
        {"role": "user", "content": user_content}
    ]


if __name__ == "__main__":
    # Test builder output
    import json
    dummy_chunks = [
        {
            "page_content": "HDFC Defence Fund has an exit load of 1% if redeemed within 1 year.",
            "metadata": {
                "source_url": "https://groww.in/mutual-funds/hdfc-defence-fund-direct-growth",
                "last_updated": "2026-06-04T12:00:00Z"
            }
        }
    ]
    messages = build_messages("What is the exit load of HDFC Defence Fund?", dummy_chunks)
    print(json.dumps(messages, indent=2))
