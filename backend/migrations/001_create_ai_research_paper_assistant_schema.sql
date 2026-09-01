-- SUPERSEDED: schema management moved to Alembic (see backend/alembic/versions/).
-- The tables below (plus users/revoked_tokens, not covered here) are now created by
-- the Alembic baseline migration. Kept for historical reference only — do not run
-- this file against a database that Alembic already manages.

CREATE TABLE IF NOT EXISTS uploaded_papers (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title VARCHAR(255) NOT NULL,
    original_filename VARCHAR(255) NOT NULL,
    storage_path TEXT NOT NULL,
    mime_type VARCHAR(120),
    file_size_bytes INTEGER,
    checksum_sha256 VARCHAR(64) UNIQUE,
    processing_status VARCHAR(50) NOT NULL DEFAULT 'uploaded',
    page_count INTEGER,
    paper_metadata JSONB,
    uploaded_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    processed_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS ix_uploaded_papers_user_id ON uploaded_papers(user_id);

CREATE TABLE IF NOT EXISTS document_chunks (
    id BIGSERIAL PRIMARY KEY,
    paper_id BIGINT NOT NULL REFERENCES uploaded_papers(id) ON DELETE CASCADE,
    chunk_index INTEGER NOT NULL,
    content TEXT NOT NULL,
    token_count INTEGER,
    character_start INTEGER,
    character_end INTEGER,
    page_start INTEGER,
    page_end INTEGER,
    chunk_hash VARCHAR(64) UNIQUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_document_chunks_paper_chunk_index UNIQUE (paper_id, chunk_index)
);

CREATE INDEX IF NOT EXISTS ix_document_chunks_paper_id ON document_chunks(paper_id);

CREATE TABLE IF NOT EXISTS document_embeddings (
    id BIGSERIAL PRIMARY KEY,
    chunk_id BIGINT NOT NULL UNIQUE REFERENCES document_chunks(id) ON DELETE CASCADE,
    embedding_model VARCHAR(255) NOT NULL,
    embedding_provider VARCHAR(100),
    embedding_dimensions INTEGER NOT NULL,
    embedding_vector JSONB,
    vector_metadata JSONB,
    embedding_status VARCHAR(50) NOT NULL DEFAULT 'pending',
    embedded_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_document_embeddings_chunk_id ON document_embeddings(chunk_id);

CREATE TABLE IF NOT EXISTS chat_sessions (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    paper_id BIGINT REFERENCES uploaded_papers(id) ON DELETE SET NULL,
    title VARCHAR(255) NOT NULL,
    status VARCHAR(50) NOT NULL DEFAULT 'active',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_message_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS ix_chat_sessions_user_id ON chat_sessions(user_id);
CREATE INDEX IF NOT EXISTS ix_chat_sessions_paper_id ON chat_sessions(paper_id);

CREATE TABLE IF NOT EXISTS chat_messages (
    id BIGSERIAL PRIMARY KEY,
    session_id BIGINT NOT NULL REFERENCES chat_sessions(id) ON DELETE CASCADE,
    message_index INTEGER NOT NULL,
    role VARCHAR(20) NOT NULL,
    content TEXT NOT NULL,
    token_count INTEGER,
    citations JSONB,
    message_metadata JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_chat_messages_session_message_index UNIQUE (session_id, message_index)
);

CREATE INDEX IF NOT EXISTS ix_chat_messages_session_id ON chat_messages(session_id);