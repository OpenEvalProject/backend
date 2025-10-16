"""
Database migrations for claim validation system.

This module handles schema versioning and migrations.
"""

import sqlite3
from datetime import datetime

from app.database import get_db


def migrate_to_new_schema():
    """
    Migrate to new schema:
    - Drop old claim/result tables
    - Create new submission-based schema
    - Preserve users and sessions tables
    """
    with get_db() as conn:
        cursor = conn.cursor()

        print("=" * 60)
        print("MIGRATING TO NEW SCHEMA")
        print("=" * 60)

        # Drop old tables (preserving users and sessions)
        old_tables = [
            "papers",
            "claims",
            "analysis_summary",
            "paper_claims",
            "llm_evaluations",
            "review_claims",
            "concordance_analysis",
            "claims_v3",
            "results_v3",
            "results_concordance",
        ]

        for table in old_tables:
            cursor.execute(f"SELECT name FROM sqlite_master WHERE type='table' AND name='{table}'")
            if cursor.fetchone():
                print(f"Dropping table: {table}")
                cursor.execute(f"DROP TABLE {table}")

        # Create submissions table
        print("Creating table: submissions")
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS submissions (
                id TEXT PRIMARY KEY,
                user_id INTEGER,
                manuscript_title TEXT,
                manuscript_doi TEXT,
                status TEXT NOT NULL DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (id)
            )
        """)

        # Create content table
        print("Creating table: content")
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS content (
                id TEXT PRIMARY KEY,
                submission_id TEXT NOT NULL,
                content_type TEXT NOT NULL,
                content_text TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (submission_id) REFERENCES submissions (id) ON DELETE CASCADE
            )
        """)

        # Create prompt table
        print("Creating table: prompt")
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS prompt (
                id TEXT PRIMARY KEY,
                prompt_text TEXT NOT NULL,
                prompt_type TEXT NOT NULL,
                model TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(prompt_text, model)
            )
        """)

        # Create claim table
        print("Creating table: claim")
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS claim (
                id TEXT PRIMARY KEY,
                content_id TEXT NOT NULL,
                claim_id TEXT NOT NULL,
                claim TEXT NOT NULL,
                claim_type TEXT NOT NULL,
                source_text TEXT NOT NULL,
                evidence_type TEXT NOT NULL,
                evidence_reasoning TEXT NOT NULL,
                prompt_id TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (content_id) REFERENCES content (id) ON DELETE CASCADE,
                FOREIGN KEY (prompt_id) REFERENCES prompt (id),
                UNIQUE(content_id, claim_id)
            )
        """)

        # Create result table
        print("Creating table: result")
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS result (
                id TEXT PRIMARY KEY,
                content_id TEXT NOT NULL,
                result_id TEXT NOT NULL,
                result_type TEXT NOT NULL,
                reviewer_id TEXT NOT NULL,
                reviewer_name TEXT NOT NULL,
                result_status TEXT NOT NULL,
                result_reasoning TEXT NOT NULL,
                prompt_id TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (content_id) REFERENCES content (id) ON DELETE CASCADE,
                FOREIGN KEY (prompt_id) REFERENCES prompt (id),
                UNIQUE(content_id, result_id, result_type)
            )
        """)

        # Create claim_result junction table
        print("Creating table: claim_result")
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS claim_result (
                claim_id TEXT NOT NULL,
                result_id TEXT NOT NULL,
                PRIMARY KEY (claim_id, result_id),
                FOREIGN KEY (claim_id) REFERENCES claim (id) ON DELETE CASCADE,
                FOREIGN KEY (result_id) REFERENCES result (id) ON DELETE CASCADE
            )
        """)

        # Create comparison table
        print("Creating table: comparison")
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS comparison (
                id TEXT PRIMARY KEY,
                submission_id TEXT NOT NULL,
                llm_result_id TEXT,
                peer_result_id TEXT,
                llm_status TEXT,
                peer_status TEXT,
                agreement_status TEXT NOT NULL,
                notes TEXT,
                prompt_id TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (submission_id) REFERENCES submissions (id) ON DELETE CASCADE,
                FOREIGN KEY (llm_result_id) REFERENCES result (id) ON DELETE CASCADE,
                FOREIGN KEY (peer_result_id) REFERENCES result (id) ON DELETE CASCADE,
                FOREIGN KEY (prompt_id) REFERENCES prompt (id)
            )
        """)

        # Create indexes
        print("Creating indexes...")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_content_submission ON content(submission_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_claim_content ON claim(content_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_result_content ON result(content_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_result_type ON result(result_type)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_comparison_submission ON comparison(submission_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_submissions_user ON submissions(user_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_submissions_status ON submissions(status)")

        conn.commit()
        print("=" * 60)
        print("MIGRATION COMPLETE")
        print("=" * 60)


if __name__ == "__main__":
    migrate_to_new_schema()
