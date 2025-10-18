#!/usr/bin/env python3
"""
Script to generate embeddings for claims in the database.

This script:
1. Queries claims that don't have embeddings yet (incremental processing)
2. Generates embeddings using OpenAI's text-embedding-3-small model
3. Stores embeddings in the database as BLOB (serialized numpy arrays)

Usage:
    python scripts/embed_claims.py [--batch-size 100] [--model text-embedding-3-small]
"""

import argparse
import pickle
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from typing import List, Tuple

import numpy as np
from openai import OpenAI

# Add parent directory to path to import app modules
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.config import settings


def get_unembedded_claims(conn: sqlite3.Connection) -> List[Tuple[str, str]]:
    """Get all claims that don't have embeddings yet.

    Returns:
        List of (claim_id, claim_text) tuples
    """
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, claim
        FROM claim
        WHERE embedding IS NULL
        ORDER BY id
    """)
    return cursor.fetchall()


def generate_embeddings(texts: List[str], model: str, client: OpenAI) -> np.ndarray:
    """Generate embeddings for a batch of texts using OpenAI API.

    Args:
        texts: List of text strings to embed
        model: OpenAI embedding model name
        client: OpenAI client instance

    Returns:
        numpy array of shape (len(texts), embedding_dim)
    """
    response = client.embeddings.create(
        input=texts,
        model=model
    )

    # Extract embeddings and convert to numpy array
    embeddings = [item.embedding for item in response.data]
    return np.array(embeddings, dtype=np.float32)


def store_embeddings(
    conn: sqlite3.Connection,
    claim_ids: List[str],
    embeddings: np.ndarray,
    model: str
) -> int:
    """Store embeddings in the database.

    Args:
        conn: Database connection
        claim_ids: List of claim IDs
        embeddings: numpy array of embeddings
        model: Model name used for embeddings

    Returns:
        Number of embeddings stored
    """
    cursor = conn.cursor()
    now = datetime.utcnow()

    count = 0
    for claim_id, embedding in zip(claim_ids, embeddings):
        # Serialize numpy array to bytes using pickle
        embedding_blob = pickle.dumps(embedding)

        cursor.execute("""
            UPDATE claim
            SET embedding = ?,
                embedding_model = ?,
                embedding_created_at = ?
            WHERE id = ?
        """, (embedding_blob, model, now, claim_id))
        count += 1

    conn.commit()
    return count


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Generate embeddings for claims in the database"
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=100,
        help="Number of claims to process in each batch (default: 100)"
    )
    parser.add_argument(
        "--model",
        type=str,
        default="text-embedding-3-small",
        help="OpenAI embedding model to use (default: text-embedding-3-small)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be done without actually generating embeddings"
    )

    args = parser.parse_args()

    print("=" * 70)
    print("Claim Embedding Generator")
    print("=" * 70)
    print(f"Database: {settings.database_path}")
    print(f"Model: {args.model}")
    print(f"Batch size: {args.batch_size}")
    print("=" * 70)

    # Check database exists
    db_path = Path(settings.database_path)
    if not db_path.exists():
        print(f"\n❌ Error: Database not found: {db_path}")
        print("   Run the application first to create the database.")
        sys.exit(1)

    # Check OpenAI API key
    openai_api_key = settings.openai_api_key
    if not openai_api_key:
        print("\n❌ Error: OPENAI_API_KEY not found in environment")
        print("   Set the OPENAI_API_KEY environment variable or add it to .env")
        sys.exit(1)

    try:
        # Connect to database
        conn = sqlite3.connect(db_path)

        # Get unembedded claims
        print("\n🔍 Checking for unembedded claims...")
        unembedded = get_unembedded_claims(conn)

        if not unembedded:
            print("✅ All claims already have embeddings!")

            # Show statistics
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM claim")
            total = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(*) FROM claim WHERE embedding IS NOT NULL")
            embedded = cursor.fetchone()[0]

            print(f"\n📊 Statistics:")
            print(f"   Total claims: {total}")
            print(f"   Embedded claims: {embedded}")

            conn.close()
            return

        print(f"📊 Found {len(unembedded)} claims without embeddings")

        if args.dry_run:
            print("\n🔍 Dry run mode - no embeddings will be generated")
            print(f"   Would process {len(unembedded)} claims in batches of {args.batch_size}")
            conn.close()
            return

        # Initialize OpenAI client
        client = OpenAI(api_key=openai_api_key)

        # Process in batches
        total_processed = 0
        batch_count = 0

        print(f"\n🚀 Starting embedding generation...")

        for i in range(0, len(unembedded), args.batch_size):
            batch = unembedded[i:i + args.batch_size]
            batch_count += 1

            claim_ids = [item[0] for item in batch]
            claim_texts = [item[1] for item in batch]

            print(f"\n   Batch {batch_count}: Processing {len(batch)} claims...")

            try:
                # Generate embeddings
                embeddings = generate_embeddings(claim_texts, args.model, client)

                # Store in database
                stored = store_embeddings(conn, claim_ids, embeddings, args.model)
                total_processed += stored

                print(f"   ✓ Stored {stored} embeddings")

            except Exception as e:
                print(f"   ✗ Error processing batch {batch_count}: {e}")
                print("   Continuing with next batch...")
                continue

        print(f"\n✅ Embedding generation complete!")
        print(f"   Total claims processed: {total_processed}")

        # Show final statistics
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM claim")
        total = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM claim WHERE embedding IS NOT NULL")
        embedded = cursor.fetchone()[0]

        print(f"\n📊 Final statistics:")
        print(f"   Total claims: {total}")
        print(f"   Embedded claims: {embedded}")
        print(f"   Unembedded claims: {total - embedded}")

        if total > embedded:
            print(f"\n💡 Note: {total - embedded} claims still need embeddings")
            print("   Run this script again to process them")

        conn.close()

    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
