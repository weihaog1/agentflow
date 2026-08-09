CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS schema_migrations (
    version text PRIMARY KEY,
    checksum_sha256 text NOT NULL,
    applied_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS corpus_state (
    workspace_id text PRIMARY KEY,
    revision bigint NOT NULL DEFAULT 0 CHECK (revision >= 0),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS documents (
    id uuid PRIMARY KEY,
    workspace_id text NOT NULL,
    title text NOT NULL,
    filename text NOT NULL,
    media_type text NOT NULL,
    status text NOT NULL CHECK (status IN ('pending', 'processing', 'ready', 'failed')),
    latest_version_id uuid,
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL
);

CREATE INDEX IF NOT EXISTS documents_workspace_created_idx
    ON documents (workspace_id, created_at DESC);

CREATE TABLE IF NOT EXISTS document_versions (
    id uuid PRIMARY KEY,
    document_id uuid NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    workspace_id text NOT NULL,
    version_number integer NOT NULL CHECK (version_number > 0),
    content_sha256 text NOT NULL CHECK (length(content_sha256) = 64),
    object_key text NOT NULL,
    object_version_id text CHECK (
        object_version_id IS NULL OR length(btrim(object_version_id)) > 0
    ),
    size_bytes bigint NOT NULL CHECK (size_bytes >= 0),
    media_type text NOT NULL,
    status text NOT NULL CHECK (status IN ('pending', 'processing', 'ready', 'failed')),
    created_at timestamptz NOT NULL,
    UNIQUE (document_id, version_number)
);

ALTER TABLE documents
    DROP CONSTRAINT IF EXISTS documents_latest_version_id_fkey;
ALTER TABLE documents
    ADD CONSTRAINT documents_latest_version_id_fkey
    FOREIGN KEY (latest_version_id) REFERENCES document_versions(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS document_versions_workspace_hash_idx
    ON document_versions (workspace_id, content_sha256);
CREATE UNIQUE INDEX IF NOT EXISTS document_versions_versioned_object_idx
    ON document_versions (object_key, object_version_id)
    WHERE object_version_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS document_versions_unversioned_object_idx
    ON document_versions (object_key)
    WHERE object_version_id IS NULL;

CREATE TABLE IF NOT EXISTS ingestion_jobs (
    id uuid PRIMARY KEY,
    workspace_id text NOT NULL,
    document_id uuid NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    document_version_id uuid NOT NULL REFERENCES document_versions(id) ON DELETE CASCADE,
    idempotency_key text NOT NULL UNIQUE,
    status text NOT NULL CHECK (status IN ('pending', 'running', 'retrying', 'completed', 'failed')),
    stage text NOT NULL CHECK (stage IN ('pending', 'downloading', 'parsing', 'chunking', 'embedding', 'indexing', 'ready', 'failed')),
    attempt integer NOT NULL DEFAULT 0 CHECK (attempt >= 0),
    max_attempts integer NOT NULL CHECK (max_attempts > 0),
    lease_owner text,
    lease_until timestamptz,
    next_attempt_at timestamptz NOT NULL,
    error_code text,
    error_message text,
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    completed_at timestamptz
);

CREATE INDEX IF NOT EXISTS ingestion_jobs_claim_idx
    ON ingestion_jobs (next_attempt_at, created_at)
    WHERE status IN ('pending', 'retrying', 'running');

CREATE TABLE IF NOT EXISTS chunks (
    id uuid PRIMARY KEY,
    workspace_id text NOT NULL,
    document_id uuid NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    document_version_id uuid NOT NULL REFERENCES document_versions(id) ON DELETE CASCADE,
    ordinal integer NOT NULL CHECK (ordinal >= 0),
    text text NOT NULL,
    token_count integer NOT NULL CHECK (token_count >= 0),
    embedding vector(384) NOT NULL,
    locator jsonb NOT NULL DEFAULT '{}'::jsonb,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    search_vector tsvector GENERATED ALWAYS AS (to_tsvector('english', text)) STORED,
    created_at timestamptz NOT NULL,
    UNIQUE (document_version_id, ordinal)
);

CREATE INDEX IF NOT EXISTS chunks_workspace_document_idx
    ON chunks (workspace_id, document_id);
CREATE INDEX IF NOT EXISTS chunks_search_vector_idx
    ON chunks USING gin (search_vector);
CREATE INDEX IF NOT EXISTS chunks_embedding_hnsw_idx
    ON chunks USING hnsw (embedding vector_cosine_ops);

CREATE TABLE IF NOT EXISTS workflow_runs (
    id uuid PRIMARY KEY,
    workspace_id text NOT NULL,
    workflow text NOT NULL CHECK (workflow IN ('question', 'compare', 'brief')),
    status text NOT NULL CHECK (status IN ('running', 'completed', 'evidence_gap', 'failed')),
    corpus_revision bigint NOT NULL CHECK (corpus_revision >= 0),
    normalized_input jsonb NOT NULL,
    document_ids uuid[] NOT NULL DEFAULT '{}',
    model_id text NOT NULL,
    prompt_version text NOT NULL,
    graph_version text NOT NULL,
    cached boolean NOT NULL DEFAULT false,
    result jsonb,
    evidence_gap text,
    steps jsonb NOT NULL DEFAULT '[]'::jsonb,
    metrics jsonb NOT NULL DEFAULT '{}'::jsonb,
    error_code text,
    error_message text,
    created_at timestamptz NOT NULL,
    completed_at timestamptz
);

CREATE INDEX IF NOT EXISTS workflow_runs_workspace_created_idx
    ON workflow_runs (workspace_id, created_at DESC);

CREATE TABLE IF NOT EXISTS citations (
    id uuid PRIMARY KEY,
    run_id uuid NOT NULL REFERENCES workflow_runs(id) ON DELETE CASCADE,
    chunk_id uuid NOT NULL REFERENCES chunks(id) ON DELETE RESTRICT,
    document_id uuid NOT NULL REFERENCES documents(id) ON DELETE RESTRICT,
    document_version_id uuid NOT NULL REFERENCES document_versions(id) ON DELETE RESTRICT,
    document_title text NOT NULL,
    chunk_ordinal integer NOT NULL CHECK (chunk_ordinal >= 0),
    quote text NOT NULL,
    locator jsonb NOT NULL DEFAULT '{}'::jsonb,
    score double precision NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (run_id, chunk_id)
);

CREATE INDEX IF NOT EXISTS citations_run_idx ON citations (run_id);
