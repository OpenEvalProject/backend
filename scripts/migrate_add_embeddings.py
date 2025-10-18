#!/usr/bin/env python3
"""
Migration script to add embedding columns to existing claim table.

This script adds the following columns to the claim table:
- embedding BLOB
- embedding_model TEXT
- embedding_created_at TIMESTAMP

Usage:
    python scripts/migrate_add_embeddings.py
"""

import sqlite3
import sys
from pathlib import Path

# Add parent directory to path to import app modules
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.config import settings


def check_columns_exist(conn: sqlite3.Connection) -> dict:
    """Check which embedding columns already exist in the claim table."""
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(claim)")
    columns = {row[1] for row in cursor.fetchall()}

    return {
        'embedding': 'embedding' in columns,
        'embedding_model': 'embedding_model' in columns,
        'embedding_created_at': 'embedding_created_at' in columns,
    }


def add_embedding_columns(conn: sqlite3.Connection):
    """Add embedding columns to the claim table if they don't exist."""
    cursor = conn.cursor()

    # Check which columns exist
    existing = check_columns_exist(conn)

    print("\n📊 Current claim table structure:")
    print(f"  - embedding: {'✓ exists' if existing['embedding'] else '✗ missing'}")
    print(f"  - embedding_model: {'✓ exists' if existing['embedding_model'] else '✗ missing'}")
    print(f"  - embedding_created_at: {'✓ exists' if existing['embedding_created_at'] else '✗ missing'}")

    # Add missing columns
    changes_made = False

    if not existing['embedding']:
        print("\n🔧 Adding 'embedding' column...")
        cursor.execute("ALTER TABLE claim ADD COLUMN embedding BLOB")
        changes_made = True
        print("  ✓ Added embedding column")

    if not existing['embedding_model']:
        print("\n🔧 Adding 'embedding_model' column...")
        cursor.execute("ALTER TABLE claim ADD COLUMN embedding_model TEXT")
        changes_made = True
        print("  ✓ Added embedding_model column")

    if not existing['embedding_created_at']:
        print("\n🔧 Adding 'embedding_created_at' column...")
        cursor.execute("ALTER TABLE claim ADD COLUMN embedding_created_at TIMESTAMP")
        changes_made = True
        print("  ✓ Added embedding_created_at column")

    if changes_made:
        # Add index for embedding_created_at
        print("\n🔧 Creating index on embedding_created_at...")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_claim_embedding_created ON claim(embedding_created_at)")
        print("  ✓ Created index")

        conn.commit()
        print("\n✅ Migration completed successfully!")
    else:
        print("\n✅ All embedding columns already exist. No migration needed.")

    return changes_made


def main():
    """Main entry point."""
    print("=" * 70)
    print("Database Migration: Add Embedding Columns to Claim Table")
    print("=" * 70)
    print(f"Database: {settings.database_path}")
    print("=" * 70)

    db_path = Path(settings.database_path)

    if not db_path.exists():
        print(f"\n❌ Error: Database not found: {db_path}")
        print("   Run the application first to create the database.")
        sys.exit(1)

    try:
        # Connect to database
        conn = sqlite3.connect(db_path)

        # Run migration
        add_embedding_columns(conn)

        # Verify final structure
        print("\n📊 Verifying final structure...")
        final_check = check_columns_exist(conn)
        all_present = all(final_check.values())

        if all_present:
            print("  ✓ All embedding columns present")

            # Count claims
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM claim")
            claim_count = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(*) FROM claim WHERE embedding IS NOT NULL")
            embedded_count = cursor.fetchone()[0]

            print(f"\n📈 Database statistics:")
            print(f"  - Total claims: {claim_count}")
            print(f"  - Embedded claims: {embedded_count}")
            print(f"  - Unembedded claims: {claim_count - embedded_count}")

            if claim_count > embedded_count:
                print(f"\n💡 Next step: Run embed_claims.py to generate embeddings for {claim_count - embedded_count} claims")
        else:
            print("  ✗ Some columns are still missing!")
            sys.exit(1)

        conn.close()

    except Exception as e:
        print(f"\n❌ Error during migration: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
