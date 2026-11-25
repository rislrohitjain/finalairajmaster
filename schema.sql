-- ==============================================================================
-- RAJASTHAN ADMINISTRATIVE & GEOGRAPHIC MASTER (finalairajmaster)
-- SINGLE-TABLE RAG SUPPORT & PGVECTOR SCHEMA
-- ==============================================================================

-- 1. Enable pgvector extension
CREATE EXTENSION IF NOT EXISTS vector;

-- 2. Create single-table RAG support for knowledge base chunks ('doc') and conversation history ('chat')
CREATE TABLE IF NOT EXISTS rag_support (
    id SERIAL PRIMARY KEY,
    record_type VARCHAR(10) NOT NULL, -- 'doc' for knowledge chunks, 'chat' for session history
    session_id VARCHAR(100),
    role VARCHAR(20),                 -- 'user' or 'assistant'
    content TEXT NOT NULL,
    embedding VECTOR(384),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 3. HNSW Cosine Distance Index for high-speed nearest-neighbor vector search
CREATE INDEX IF NOT EXISTS idx_rag_support_embedding 
ON rag_support USING hnsw (embedding vector_cosine_ops);

-- 4. B-Tree Indexes for rapid filtering on session and record type
CREATE INDEX IF NOT EXISTS idx_rag_support_type 
ON rag_support (record_type);

CREATE INDEX IF NOT EXISTS idx_rag_support_session_id 
ON rag_support (session_id, created_at DESC);
