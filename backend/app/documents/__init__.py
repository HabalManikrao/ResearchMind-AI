"""Document RAG (#3): PDF/DOCX ingestion → chunk → embed → Qdrant → retrieval.

Retrieved passages become the same `Source`/`ClaimSource` evidence a web passage
produces, so document evidence flows through the existing P0 evidence engine.
"""
