import sqlite3
from contextlib import contextmanager
from datetime import datetime
from typing import Optional

from app.config import settings


def get_connection():
    """Get a database connection"""
    conn = sqlite3.connect(settings.database_path)
    conn.row_factory = sqlite3.Row
    return conn


@contextmanager
def get_db():
    """Context manager for database connections"""
    conn = get_connection()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    """Initialize the database schema"""
    with get_db() as conn:
        cursor = conn.cursor()

        # Users table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                orcid_id TEXT UNIQUE NOT NULL,
                name TEXT,
                email TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_login TIMESTAMP
            )
        """)

        # Papers table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS papers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                title TEXT NOT NULL,
                source_type TEXT NOT NULL,
                source_reference TEXT,
                full_text TEXT NOT NULL,
                content_hash TEXT,
                document_length INTEGER,
                processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (id)
            )
        """)

        # Claims table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS claims (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                paper_id INTEGER NOT NULL,
                claim_text TEXT NOT NULL,
                source_text TEXT NOT NULL,
                status TEXT NOT NULL,
                evidence TEXT,
                evidence_basis TEXT,
                reference_claims TEXT,
                reference_rationale TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (paper_id) REFERENCES papers (id) ON DELETE CASCADE
            )
        """)

        # Analysis summary table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS analysis_summary (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                paper_id INTEGER UNIQUE NOT NULL,
                total_claims INTEGER NOT NULL,
                supported_count INTEGER NOT NULL,
                unsupported_count INTEGER NOT NULL,
                uncertain_count INTEGER NOT NULL,
                verification_score REAL NOT NULL,
                processing_time_seconds REAL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (paper_id) REFERENCES papers (id) ON DELETE CASCADE
            )
        """)

        # Sessions table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                expires_at TIMESTAMP NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users (id)
            )
        """)

        # Create indexes
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_papers_user_id ON papers(user_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_papers_processed_at ON papers(processed_at DESC)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_papers_content_hash ON papers(content_hash)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_claims_paper_id ON claims(paper_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_sessions_user_id ON sessions(user_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_sessions_expires ON sessions(expires_at)")

        conn.commit()
        print("Database initialized successfully")


def migrate_add_content_hash():
    """Add content_hash column to existing papers table"""
    with get_db() as conn:
        cursor = conn.cursor()

        # Check if column already exists
        cursor.execute("PRAGMA table_info(papers)")
        columns = [row[1] for row in cursor.fetchall()]

        if 'content_hash' not in columns:
            print("Adding content_hash column to papers table...")
            cursor.execute("ALTER TABLE papers ADD COLUMN content_hash TEXT")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_papers_content_hash ON papers(content_hash)")
            conn.commit()
            print("Migration complete: content_hash column added")
        else:
            print("content_hash column already exists")


def migrate_add_evidence_basis():
    """Add evidence_basis column to existing claims table"""
    with get_db() as conn:
        cursor = conn.cursor()

        # Check if column already exists
        cursor.execute("PRAGMA table_info(claims)")
        columns = [row[1] for row in cursor.fetchall()]

        if 'evidence_basis' not in columns:
            print("Adding evidence_basis column to claims table...")
            cursor.execute("ALTER TABLE claims ADD COLUMN evidence_basis TEXT")
            conn.commit()
            print("Migration complete: evidence_basis column added")
        else:
            print("evidence_basis column already exists")


def migrate_add_claim_references():
    """Add reference_claims and reference_rationale columns to existing claims table"""
    with get_db() as conn:
        cursor = conn.cursor()

        # Check if columns already exist
        cursor.execute("PRAGMA table_info(claims)")
        columns = [row[1] for row in cursor.fetchall()]

        if 'reference_claims' not in columns:
            print("Adding reference_claims column to claims table...")
            cursor.execute("ALTER TABLE claims ADD COLUMN reference_claims TEXT")  # JSON array stored as TEXT
            conn.commit()
            print("Migration complete: reference_claims column added")
        else:
            print("reference_claims column already exists")

        if 'reference_rationale' not in columns:
            print("Adding reference_rationale column to claims table...")
            cursor.execute("ALTER TABLE claims ADD COLUMN reference_rationale TEXT")
            conn.commit()
            print("Migration complete: reference_rationale column added")
        else:
            print("reference_rationale column already exists")


def migrate_add_new_workflow_tables():
    """Add new tables for the updated workflow: paper_claims, llm_evaluations, review_claims, concordance_analysis"""
    with get_db() as conn:
        cursor = conn.cursor()

        # Check if paper_claims table exists
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='paper_claims'")
        if not cursor.fetchone():
            print("Creating paper_claims table...")
            cursor.execute("""
                CREATE TABLE paper_claims (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    paper_id INTEGER NOT NULL,
                    short_id TEXT NOT NULL,
                    claim_text TEXT NOT NULL,
                    source_text TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (paper_id) REFERENCES papers (id) ON DELETE CASCADE
                )
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_paper_claims_paper_id ON paper_claims(paper_id)")
            print("paper_claims table created")
        else:
            print("paper_claims table already exists")

        # Check if llm_evaluations table exists
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='llm_evaluations'")
        if not cursor.fetchone():
            print("Creating llm_evaluations table...")
            cursor.execute("""
                CREATE TABLE llm_evaluations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    paper_claim_id INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    evidence TEXT NOT NULL,
                    assumptions TEXT,
                    weaknesses TEXT,
                    evidence_basis TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (paper_claim_id) REFERENCES paper_claims (id) ON DELETE CASCADE
                )
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_llm_evaluations_paper_claim_id ON llm_evaluations(paper_claim_id)")
            print("llm_evaluations table created")
        else:
            print("llm_evaluations table already exists")

        # Check if review_claims table exists
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='review_claims'")
        if not cursor.fetchone():
            print("Creating review_claims table...")
            cursor.execute("""
                CREATE TABLE review_claims (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    paper_id INTEGER NOT NULL,
                    claim_text TEXT NOT NULL,
                    source_text TEXT NOT NULL,
                    reference_paper_claims TEXT,
                    reference_rationale TEXT,
                    reference_relation BOOLEAN,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (paper_id) REFERENCES papers (id) ON DELETE CASCADE
                )
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_review_claims_paper_id ON review_claims(paper_id)")
            print("review_claims table created")
        else:
            print("review_claims table already exists")
            # Add reference_relation column if it doesn't exist
            cursor.execute("PRAGMA table_info(review_claims)")
            columns = [row[1] for row in cursor.fetchall()]
            if 'reference_relation' not in columns:
                print("Adding reference_relation column to review_claims table...")
                cursor.execute("ALTER TABLE review_claims ADD COLUMN reference_relation BOOLEAN")
                print("reference_relation column added")

        # Check if concordance_analysis table exists
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='concordance_analysis'")
        if not cursor.fetchone():
            print("Creating concordance_analysis table...")
            cursor.execute("""
                CREATE TABLE concordance_analysis (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    paper_id INTEGER NOT NULL,
                    paper_claim_id INTEGER NOT NULL,
                    llm_addressed BOOLEAN NOT NULL,
                    review_addressed BOOLEAN NOT NULL,
                    agreement_status TEXT NOT NULL,
                    notes TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (paper_id) REFERENCES papers (id) ON DELETE CASCADE,
                    FOREIGN KEY (paper_claim_id) REFERENCES paper_claims (id) ON DELETE CASCADE
                )
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_concordance_paper_id ON concordance_analysis(paper_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_concordance_paper_claim_id ON concordance_analysis(paper_claim_id)")
            print("concordance_analysis table created")
        else:
            print("concordance_analysis table already exists")

        conn.commit()
        print("Migration complete: New workflow tables added")


def migrate_add_v3_workflow_tables():
    """Add new tables for V3 workflow: claims_v3, results_v3, results_concordance"""
    with get_db() as conn:
        cursor = conn.cursor()

        # Check if claims_v3 table exists
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='claims_v3'")
        if not cursor.fetchone():
            print("Creating claims_v3 table...")
            cursor.execute("""
                CREATE TABLE claims_v3 (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    paper_id INTEGER NOT NULL,
                    claim_id TEXT NOT NULL,
                    claim TEXT NOT NULL,
                    claim_type TEXT NOT NULL,
                    source_text TEXT NOT NULL,
                    evidence_type TEXT NOT NULL,
                    evidence_reasoning TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (paper_id) REFERENCES papers (id) ON DELETE CASCADE
                )
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_claims_v3_paper_id ON claims_v3(paper_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_claims_v3_claim_id ON claims_v3(claim_id)")
            print("claims_v3 table created")
        else:
            print("claims_v3 table already exists")

        # Check if results_v3 table exists
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='results_v3'")
        if not cursor.fetchone():
            print("Creating results_v3 table...")
            cursor.execute("""
                CREATE TABLE results_v3 (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    paper_id INTEGER NOT NULL,
                    source TEXT NOT NULL,
                    claim_ids TEXT NOT NULL,
                    status TEXT NOT NULL,
                    status_reasoning TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (paper_id) REFERENCES papers (id) ON DELETE CASCADE
                )
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_results_v3_paper_id ON results_v3(paper_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_results_v3_source ON results_v3(source)")
            print("results_v3 table created")
        else:
            print("results_v3 table already exists")

        # Check if results_concordance table exists
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='results_concordance'")
        if not cursor.fetchone():
            print("Creating results_concordance table...")
            cursor.execute("""
                CREATE TABLE results_concordance (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    paper_id INTEGER NOT NULL,
                    llm_result_id INTEGER,
                    peer_result_id INTEGER,
                    llm_claim_ids TEXT NOT NULL,
                    peer_claim_ids TEXT NOT NULL,
                    llm_status TEXT NOT NULL,
                    peer_status TEXT NOT NULL,
                    agreement_status TEXT NOT NULL,
                    notes TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (paper_id) REFERENCES papers (id) ON DELETE CASCADE,
                    FOREIGN KEY (llm_result_id) REFERENCES results_v3 (id) ON DELETE CASCADE,
                    FOREIGN KEY (peer_result_id) REFERENCES results_v3 (id) ON DELETE CASCADE
                )
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_results_concordance_paper_id ON results_concordance(paper_id)")
            print("results_concordance table created")
        else:
            print("results_concordance table already exists")

        conn.commit()
        print("Migration complete: V3 workflow tables added")


if __name__ == "__main__":
    init_db()
    migrate_add_content_hash()
    migrate_add_evidence_basis()
    migrate_add_claim_references()
    migrate_add_new_workflow_tables()
    migrate_add_v3_workflow_tables()
