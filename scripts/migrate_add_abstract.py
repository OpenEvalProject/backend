#!/usr/bin/env python3
"""
Add abstract column to manuscript table.

This migration adds an abstract TEXT column to store manuscript abstracts.
"""

import sqlite3
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.config import settings


def migrate():
    """Add abstract column to manuscript table."""
    conn = sqlite3.connect(settings.database_path)
    cursor = conn.cursor()

    try:
        # Check if abstract column already exists
        cursor.execute("PRAGMA table_info(manuscript)")
        columns = [row[1] for row in cursor.fetchall()]

        if 'abstract' in columns:
            print("✓ Abstract column already exists")
            return

        # Add abstract column
        print("Adding abstract column to manuscript table...")
        cursor.execute("ALTER TABLE manuscript ADD COLUMN abstract TEXT")

        conn.commit()
        print("✓ Migration complete: Added abstract column")

    except Exception as e:
        print(f"✗ Migration failed: {e}")
        conn.rollback()
        raise

    finally:
        conn.close()


if __name__ == "__main__":
    migrate()
