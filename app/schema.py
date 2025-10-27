"""
Database schema for claim verification system.

This schema is designed to store manuscripts with their claims, results, and comparisons
based on the CLLM evaluation workflow.

UPDATED: 2025-10-25 to support new db_export.json structure with submission/content model.
"""

# SQL Schema for the claim verification database
SCHEMA_SQL = """
-- Submission table (top-level container for each paper evaluation)
CREATE TABLE IF NOT EXISTS submission (
    id TEXT PRIMARY KEY,
    user_id TEXT,
    manuscript_title TEXT,
    manuscript_doi TEXT,
    manuscript_pub_date TEXT,
    manuscript_abstract TEXT,
    status TEXT NOT NULL,
    created_at TIMESTAMP NOT NULL,
    updated_at TIMESTAMP NOT NULL
);

-- Author table (stores manuscript authors)
CREATE TABLE IF NOT EXISTS author (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    submission_id TEXT NOT NULL,
    given_names TEXT NOT NULL,
    surname TEXT NOT NULL,
    orcid TEXT,
    corresponding BOOLEAN DEFAULT 0,
    position INTEGER NOT NULL,
    FOREIGN KEY (submission_id) REFERENCES submission(id) ON DELETE CASCADE
);

-- Affiliation table (stores institutional affiliations)
CREATE TABLE IF NOT EXISTS affiliation (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    submission_id TEXT NOT NULL,
    affiliation_id TEXT NOT NULL,
    institution TEXT,
    department TEXT,
    city TEXT,
    country TEXT,
    FOREIGN KEY (submission_id) REFERENCES submission(id) ON DELETE CASCADE,
    UNIQUE(submission_id, affiliation_id)
);

-- Junction table: authors to affiliations (many-to-many)
CREATE TABLE IF NOT EXISTS author_affiliation (
    author_id INTEGER NOT NULL,
    affiliation_id INTEGER NOT NULL,
    PRIMARY KEY (author_id, affiliation_id),
    FOREIGN KEY (author_id) REFERENCES author(id) ON DELETE CASCADE,
    FOREIGN KEY (affiliation_id) REFERENCES affiliation(id) ON DELETE CASCADE
);

-- Content table (stores manuscript text and peer reviews)
CREATE TABLE IF NOT EXISTS content (
    id TEXT PRIMARY KEY,
    submission_id TEXT NOT NULL,
    content_type TEXT NOT NULL CHECK(content_type IN ('manuscript', 'peer_review')),
    content_text TEXT NOT NULL,
    created_at TIMESTAMP NOT NULL,
    FOREIGN KEY (submission_id) REFERENCES submission(id) ON DELETE CASCADE
);

-- Prompts table (stores prompts used for extraction/evaluation)
CREATE TABLE IF NOT EXISTS prompt (
    id TEXT PRIMARY KEY,
    prompt_text TEXT NOT NULL,
    prompt_type TEXT CHECK(prompt_type IN ('extract', 'eval_llm', 'eval_peer', 'compare')),
    model TEXT NOT NULL,
    created_at TIMESTAMP NOT NULL
);

-- Claims table (atomic factual claims extracted from manuscript)
CREATE TABLE IF NOT EXISTS claim (
    id TEXT PRIMARY KEY,
    content_id TEXT NOT NULL,
    claim_id TEXT,
    claim TEXT NOT NULL,
    claim_type TEXT NOT NULL CHECK(claim_type IN ('EXPLICIT', 'IMPLICIT')),
    source TEXT NOT NULL,
    source_type TEXT NOT NULL,
    evidence TEXT NOT NULL,
    evidence_type TEXT NOT NULL,
    prompt_id TEXT,
    embedding BLOB,
    embedding_model TEXT,
    embedding_created_at TIMESTAMP,
    created_at TIMESTAMP NOT NULL,
    FOREIGN KEY (content_id) REFERENCES content(id) ON DELETE CASCADE,
    FOREIGN KEY (prompt_id) REFERENCES prompt(id)
);

-- Results table (unified table for both LLM and peer evaluation results)
CREATE TABLE IF NOT EXISTS result (
    id TEXT PRIMARY KEY,
    content_id TEXT NOT NULL,
    result_id TEXT,
    result_category TEXT NOT NULL CHECK(result_category IN ('llm', 'peer')),
    result TEXT NOT NULL,
    result_status TEXT NOT NULL CHECK(result_status IN ('SUPPORTED', 'UNSUPPORTED', 'UNCERTAIN')),
    result_reasoning TEXT NOT NULL,
    reviewer_id TEXT,
    reviewer_name TEXT,
    prompt_id TEXT,
    created_at TIMESTAMP NOT NULL,
    FOREIGN KEY (content_id) REFERENCES content(id) ON DELETE CASCADE,
    FOREIGN KEY (prompt_id) REFERENCES prompt(id)
);

-- Comparison table (concordance analysis between OpenEval and peer results)
CREATE TABLE IF NOT EXISTS comparison (
    id TEXT PRIMARY KEY,
    openeval_result_id TEXT,
    peer_result_id TEXT,
    openeval_status TEXT,
    peer_status TEXT,
    agreement_status TEXT NOT NULL CHECK(agreement_status IN ('agree', 'partial', 'disagree', 'disjoint')),
    comparison TEXT,
    n_openeval INTEGER,
    n_peer INTEGER,
    n_itx INTEGER,
    openeval_reasoning TEXT,
    peer_reasoning TEXT,
    openeval_result_type TEXT,
    peer_result_type TEXT,
    prompt_id TEXT,
    created_at TIMESTAMP NOT NULL,
    FOREIGN KEY (openeval_result_id) REFERENCES result(id) ON DELETE CASCADE,
    FOREIGN KEY (peer_result_id) REFERENCES result(id) ON DELETE CASCADE,
    FOREIGN KEY (prompt_id) REFERENCES prompt(id)
);

-- Junction table: claims to results (many-to-many)
CREATE TABLE IF NOT EXISTS claim_result (
    claim_id TEXT NOT NULL,
    result_id TEXT NOT NULL,
    PRIMARY KEY (claim_id, result_id),
    FOREIGN KEY (claim_id) REFERENCES claim(id) ON DELETE CASCADE,
    FOREIGN KEY (result_id) REFERENCES result(id) ON DELETE CASCADE
);

-- Create indexes for better query performance
CREATE INDEX IF NOT EXISTS idx_content_submission ON content(submission_id);
CREATE INDEX IF NOT EXISTS idx_content_type ON content(content_type);
CREATE INDEX IF NOT EXISTS idx_claim_content ON claim(content_id);
CREATE INDEX IF NOT EXISTS idx_claim_prompt ON claim(prompt_id);
CREATE INDEX IF NOT EXISTS idx_claim_embedding_created ON claim(embedding_created_at);
CREATE INDEX IF NOT EXISTS idx_result_content ON result(content_id);
CREATE INDEX IF NOT EXISTS idx_result_category ON result(result_category);
CREATE INDEX IF NOT EXISTS idx_result_prompt ON result(prompt_id);
CREATE INDEX IF NOT EXISTS idx_comparison_openeval_result ON comparison(openeval_result_id);
CREATE INDEX IF NOT EXISTS idx_comparison_peer_result ON comparison(peer_result_id);
CREATE INDEX IF NOT EXISTS idx_comparison_prompt ON comparison(prompt_id);
CREATE INDEX IF NOT EXISTS idx_prompt_type ON prompt(prompt_type);
CREATE INDEX IF NOT EXISTS idx_author_submission ON author(submission_id);
CREATE INDEX IF NOT EXISTS idx_author_surname ON author(surname);
CREATE INDEX IF NOT EXISTS idx_author_orcid ON author(orcid);
CREATE INDEX IF NOT EXISTS idx_affiliation_submission ON affiliation(submission_id);
CREATE INDEX IF NOT EXISTS idx_affiliation_institution ON affiliation(institution);
CREATE INDEX IF NOT EXISTS idx_affiliation_country ON affiliation(country);
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
