"""
Database schema for claim verification system.

This schema is designed to store manuscripts with their claims, results, and comparisons
based on the CLLM evaluation workflow.
"""

# SQL Schema for the claim verification database
SCHEMA_SQL = """
-- Core manuscript table
CREATE TABLE IF NOT EXISTS manuscript (
    id TEXT PRIMARY KEY,
    doi TEXT,
    title TEXT,
    abstract TEXT,
    pub_date TEXT,
    content TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Prompts table (stores prompts used for extraction/evaluation)
CREATE TABLE IF NOT EXISTS prompt (
    id TEXT PRIMARY KEY,
    prompt_text TEXT NOT NULL,
    model TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Claims table (atomic factual claims extracted from manuscript)
CREATE TABLE IF NOT EXISTS claim (
    id TEXT PRIMARY KEY,
    manuscript_id TEXT NOT NULL,
    claim_id TEXT,
    claim TEXT NOT NULL,
    claim_type TEXT NOT NULL,
    source_text TEXT NOT NULL,
    evidence_type TEXT NOT NULL,
    evidence_reasoning TEXT NOT NULL,
    prompt_id TEXT,
    embedding BLOB,
    embedding_model TEXT,
    embedding_created_at TIMESTAMP,
    FOREIGN KEY (manuscript_id) REFERENCES manuscript(id) ON DELETE CASCADE,
    FOREIGN KEY (prompt_id) REFERENCES prompt(id)
);

-- Peer review files table
CREATE TABLE IF NOT EXISTS peer (
    id TEXT PRIMARY KEY,
    manuscript_id TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (manuscript_id) REFERENCES manuscript(id) ON DELETE CASCADE
);

-- LLM evaluation results table
CREATE TABLE IF NOT EXISTS result_llm (
    id TEXT PRIMARY KEY,
    manuscript_id TEXT NOT NULL,
    result TEXT NOT NULL,
    reviewer_id TEXT,
    reviewer_name TEXT,
    result_status TEXT NOT NULL,
    result_reasoning TEXT NOT NULL,
    prompt_id TEXT,
    FOREIGN KEY (manuscript_id) REFERENCES manuscript(id) ON DELETE CASCADE,
    FOREIGN KEY (prompt_id) REFERENCES prompt(id)
);

-- Peer evaluation results table
CREATE TABLE IF NOT EXISTS result_peer (
    id TEXT PRIMARY KEY,
    peer_id TEXT NOT NULL,
    result TEXT NOT NULL,
    reviewer_id TEXT,
    reviewer_name TEXT,
    result_status TEXT NOT NULL,
    result_reasoning TEXT NOT NULL,
    prompt_id TEXT,
    FOREIGN KEY (peer_id) REFERENCES peer(id) ON DELETE CASCADE,
    FOREIGN KEY (prompt_id) REFERENCES prompt(id)
);

-- Comparison table (concordance analysis between OpenEval and peer results)
CREATE TABLE IF NOT EXISTS comparison (
    id TEXT PRIMARY KEY,
    openeval_result_id TEXT,
    peer_result_id TEXT,
    openeval_status TEXT,
    peer_status TEXT,
    agreement_status TEXT NOT NULL,
    comparison TEXT,
    n_openeval INTEGER,
    n_peer INTEGER,
    n_itx INTEGER,
    openeval_reasoning TEXT,
    peer_reasoning TEXT,
    prompt_id TEXT,
    FOREIGN KEY (openeval_result_id) REFERENCES result_llm(id) ON DELETE CASCADE,
    FOREIGN KEY (peer_result_id) REFERENCES result_peer(id) ON DELETE CASCADE,
    FOREIGN KEY (prompt_id) REFERENCES prompt(id)
);

-- Junction table: claims to LLM results (many-to-many)
CREATE TABLE IF NOT EXISTS claim_result_llm (
    claim_id TEXT NOT NULL,
    result_llm_id TEXT NOT NULL,
    PRIMARY KEY (claim_id, result_llm_id),
    FOREIGN KEY (claim_id) REFERENCES claim(id) ON DELETE CASCADE,
    FOREIGN KEY (result_llm_id) REFERENCES result_llm(id) ON DELETE CASCADE
);

-- Junction table: claims to peer results (many-to-many)
CREATE TABLE IF NOT EXISTS claim_result_peer (
    claim_id TEXT NOT NULL,
    result_peer_id TEXT NOT NULL,
    PRIMARY KEY (claim_id, result_peer_id),
    FOREIGN KEY (claim_id) REFERENCES claim(id) ON DELETE CASCADE,
    FOREIGN KEY (result_peer_id) REFERENCES result_peer(id) ON DELETE CASCADE
);

-- Create indexes for better query performance
CREATE INDEX IF NOT EXISTS idx_claim_manuscript ON claim(manuscript_id);
CREATE INDEX IF NOT EXISTS idx_claim_prompt ON claim(prompt_id);
CREATE INDEX IF NOT EXISTS idx_claim_embedding_created ON claim(embedding_created_at);
CREATE INDEX IF NOT EXISTS idx_peer_manuscript ON peer(manuscript_id);
CREATE INDEX IF NOT EXISTS idx_result_llm_manuscript ON result_llm(manuscript_id);
CREATE INDEX IF NOT EXISTS idx_result_llm_prompt ON result_llm(prompt_id);
CREATE INDEX IF NOT EXISTS idx_result_peer_peer ON result_peer(peer_id);
CREATE INDEX IF NOT EXISTS idx_result_peer_prompt ON result_peer(prompt_id);
CREATE INDEX IF NOT EXISTS idx_comparison_openeval_result ON comparison(openeval_result_id);
CREATE INDEX IF NOT EXISTS idx_comparison_peer_result ON comparison(peer_result_id);
CREATE INDEX IF NOT EXISTS idx_comparison_prompt ON comparison(prompt_id);
"""

# SQL to preserve auth tables (users and sessions)
AUTH_TABLES_SQL = """
-- Users table (for ORCID authentication)
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    orcid_id TEXT UNIQUE NOT NULL,
    name TEXT,
    email TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_login TIMESTAMP
);

-- Sessions table (for user sessions)
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMP NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(id)
);

-- Create indexes for auth tables
CREATE INDEX IF NOT EXISTS idx_sessions_user_id ON sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_sessions_expires ON sessions(expires_at);
"""
