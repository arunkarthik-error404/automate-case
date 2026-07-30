-- Enable pgvector extension
CREATE EXTENSION IF NOT EXISTS vector;

-- Documents Table
CREATE TABLE IF NOT EXISTS documents (
    id SERIAL PRIMARY KEY,
    file_name VARCHAR(512) NOT NULL,
    file_path TEXT NOT NULL UNIQUE,
    category VARCHAR(100),
    entity_name VARCHAR(256),
    total_pages INTEGER DEFAULT 0,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Document Chunks Table with vector embeddings and rich metadata JSONB
CREATE TABLE IF NOT EXISTS document_chunks (
    id SERIAL PRIMARY KEY,
    document_id INTEGER REFERENCES documents(id) ON DELETE CASCADE,
    chunk_index INTEGER NOT NULL,
    page_number INTEGER NOT NULL,
    chunk_text TEXT NOT NULL,
    metadata JSONB DEFAULT '{}'::jsonb,
    embedding vector(384),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Create HNSW index for fast vector cosine similarity search
CREATE INDEX IF NOT EXISTS idx_document_chunks_embedding_hnsw 
ON document_chunks USING hnsw (embedding vector_cosine_ops);

-- Create GIN index on metadata JSONB for fast exact/substring filter queries
CREATE INDEX IF NOT EXISTS idx_document_chunks_metadata_gin 
ON document_chunks USING gin (metadata);

-- Index on document_id for rapid joins
CREATE INDEX IF NOT EXISTS idx_document_chunks_document_id 
ON document_chunks (document_id);
