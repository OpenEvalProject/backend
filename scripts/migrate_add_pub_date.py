"""
Migration script to add pub_date column to manuscript table.
"""

import sqlite3
import sys
from pathlib import Path

# Add parent directory to path so we can import settings
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.config import settings


def migrate():
    """Add pub_date column to manuscript table."""
    conn = sqlite3.connect(settings.database_path)
    cursor = conn.cursor()

    try:
        # Check if pub_date column already exists
        cursor.execute("PRAGMA table_info(manuscript)")
        columns = [row[1] for row in cursor.fetchall()]

        if 'pub_date' in columns:
            print("✓ pub_date column already exists")
            return

        # Add pub_date column
        print("Adding pub_date column to manuscript table...")
        cursor.execute("ALTER TABLE manuscript ADD COLUMN pub_date TEXT")

        conn.commit()
        print("✓ Migration complete: Added pub_date column")

    except Exception as e:
        print(f"✗ Migration failed: {e}")
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    migrate()
