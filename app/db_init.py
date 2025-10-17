"""
Database initialization for claim verification system.

This module handles:
1. Dropping old tables (papers, claims, analysis_summary, etc.)
2. Creating new schema tables
3. Preserving auth tables (users, sessions)
"""

import logging
import sqlite3
from pathlib import Path

from app.config import settings
from app.schema import AUTH_TABLES_SQL, SCHEMA_SQL

logger = logging.getLogger(__name__)


def init_database():
    """Initialize the database with new schema while preserving auth tables."""
    db_path = Path(settings.database_path)
    logger.info(f"Initializing database at: {db_path}")

    # Create database file if it doesn't exist
    db_path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(db_path)
    # Enable foreign keys
    conn.execute("PRAGMA foreign_keys = ON")
    cursor = conn.cursor()

    try:
        # Get list of existing tables
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        existing_tables = {row[0] for row in cursor.fetchall()}

        logger.info(f"Found {len(existing_tables)} existing tables")

        # Temporarily disable foreign keys to drop tables
        cursor.execute("PRAGMA foreign_keys = OFF")

        # Tables to drop (old schema)
        tables_to_drop = [
            'papers',
            'claims',
            'analysis_summary',
            'paper_claims',
            'llm_evaluations',
            'review_claims',
            'concordance_analysis',
            'claims_v3',
            'results_v3',
            'results_concordance',
            # Drop all existing schema tables to recreate them
            'claim',
            'claim_result',
            'claim_result_llm',
            'claim_result_peer',
            'comparison',
            'content',
            'manuscript',
            'peer',
            'prompt',
            'result',
            'result_llm',
            'result_peer',
            'submissions'
        ]

        # Drop old tables
        for table in tables_to_drop:
            if table in existing_tables:
                logger.info(f"Dropping old table: {table}")
                cursor.execute(f"DROP TABLE IF EXISTS {table}")

        conn.commit()

        # Re-enable foreign keys
        cursor.execute("PRAGMA foreign_keys = ON")

        logger.info("Creating auth tables (users, sessions)...")
        cursor.executescript(AUTH_TABLES_SQL)

        logger.info("Creating new schema tables...")
        cursor.executescript(SCHEMA_SQL)

        conn.commit()
        logger.info("Database initialization complete")

        # Verify tables were created
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
        final_tables = [row[0] for row in cursor.fetchall()]
        logger.info(f"Database now has {len(final_tables)} tables: {', '.join(final_tables)}")

    except Exception as e:
        logger.error(f"Error initializing database: {e}")
        conn.rollback()
        raise
    finally:
        conn.close()


def reset_database():
    """
    Completely reset the database (including auth tables).
    USE WITH CAUTION - will delete all data!
    """
    db_path = Path(settings.database_path)
    logger.warning(f"RESETTING DATABASE: {db_path}")

    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    cursor = conn.cursor()

    try:
        # Temporarily disable foreign keys to drop tables
        cursor.execute("PRAGMA foreign_keys = OFF")

        # Get all tables
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        all_tables = [row[0] for row in cursor.fetchall()]

        # Drop all tables
        for table in all_tables:
            logger.info(f"Dropping table: {table}")
            cursor.execute(f"DROP TABLE IF EXISTS {table}")

        conn.commit()

        # Re-enable foreign keys
        cursor.execute("PRAGMA foreign_keys = ON")

        # Recreate all tables
        logger.info("Creating auth tables...")
        cursor.executescript(AUTH_TABLES_SQL)

        logger.info("Creating schema tables...")
        cursor.executescript(SCHEMA_SQL)

        conn.commit()
        logger.info("Database reset complete")

    except Exception as e:
        logger.error(f"Error resetting database: {e}")
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    # Configure logging for CLI usage
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "--reset":
        print("⚠️  WARNING: This will delete ALL data including users and sessions!")
        response = input("Type 'yes' to confirm: ")
        if response.lower() == 'yes':
            reset_database()
        else:
            print("Reset cancelled")
    else:
        init_database()
