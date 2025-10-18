"""
Manuscript ingestion script.

This script scans the evals/manuscripts directory for db_export.json files
and populates the database with manuscripts, claims, results, and comparisons.

Usage:
    python -m app.ingest_manuscripts [--force] [--limit N] [--manuscripts-dir PATH]
"""

import argparse
import json
import logging
import sqlite3
from pathlib import Path
from typing import Optional

from app.config import settings
from app.db_init import init_database

logger = logging.getLogger(__name__)


class ManuscriptIngester:
    """Handles ingestion of manuscripts from db_export.json files."""

    def __init__(self, db_path: str):
        self.db_path = db_path
        self.stats = {
            'total_processed': 0,
            'total_manuscripts': 0,
            'total_claims': 0,
            'total_results_llm': 0,
            'total_results_peer': 0,
            'total_comparisons': 0,
            'total_prompts': 0,
            'errors': 0
        }

    def find_db_export_files(self, manuscripts_dir: Path, limit: Optional[int] = None):
        """
        Find all db_export.json files in manuscripts directory.

        Args:
            manuscripts_dir: Path to manuscripts directory
            limit: Optional limit on number of files to process

        Yields:
            tuple of (article_id, version, db_export_path)
        """
        # Pattern: manuscripts/elife-XXXXX/vN/db_export.json
        pattern = "*/v*/db_export.json"
        files = sorted(manuscripts_dir.glob(pattern))

        if limit:
            files = files[:limit]

        for file_path in files:
            # Extract article_id and version from path
            # Example: /path/to/manuscripts/elife-00003/v1/db_export.json
            version_dir = file_path.parent  # v1
            article_dir = version_dir.parent  # elife-00003
            article_id = article_dir.name
            version = version_dir.name

            yield (article_id, version, file_path)

    def ingest_manuscript(self, conn: sqlite3.Connection, article_id: str, version: str, file_path: Path):
        """
        Ingest a single manuscript from db_export.json.

        Args:
            conn: Database connection
            article_id: Article ID (e.g., "elife-00003")
            version: Version (e.g., "v1")
            file_path: Path to db_export.json
        """
        try:
            # Load JSON data
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)

            # Extract main components
            submission = data.get('submission', {})
            content_list = data.get('content', [])
            claims_data = data.get('claims', [])
            results_data = data.get('results', [])
            claim_results_data = data.get('claim_results', [])
            comparisons_data = data.get('comparisons', [])
            prompts_list = data.get('prompts', [])

            # Separate results by type
            results_llm_data = [r for r in results_data if r.get('result_type') == 'llm']
            results_peer_data = [r for r in results_data if r.get('result_type') == 'peer']

            # Parse content list to find manuscript and peer review content
            manuscript_text = ''
            peer_review_text = None

            for content_item in content_list:
                content_type = content_item.get('content_type', '')
                if content_type == 'manuscript':
                    manuscript_text = content_item.get('content_text', '')
                elif content_type == 'peer_review':
                    peer_review_text = content_item.get('content_text', '')

            # Parse prompts list to create a mapping by prompt_type
            prompts_by_type = {}
            for prompt_item in prompts_list:
                prompt_type = prompt_item.get('prompt_type', '')
                if prompt_type:
                    prompts_by_type[prompt_type] = prompt_item

            cursor = conn.cursor()

            # Generate manuscript_id: article_id-version
            manuscript_id = f"{article_id}-{version}"

            # Load manuscript metadata from manuscript_metadata.json if it exists
            metadata_file = file_path.parent / "manuscript_metadata.json"
            doi = submission.get('manuscript_doi')
            title = submission.get('manuscript_title')
            abstract = None
            pub_date = None

            if metadata_file.exists():
                try:
                    with open(metadata_file, 'r', encoding='utf-8') as mf:
                        metadata = json.load(mf)
                        # Prefer metadata from JSON file over submission data
                        doi = metadata.get('doi') or doi
                        title = metadata.get('title') or title
                        abstract = metadata.get('abstract')
                        pub_date = metadata.get('pub_date')
                except Exception as e:
                    logger.warning(f"Could not load metadata from {metadata_file}: {e}")

            # Step 1: Insert manuscript
            cursor.execute("""
                INSERT OR REPLACE INTO manuscript (id, doi, title, abstract, pub_date, content, created_at)
                VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            """, (
                manuscript_id,
                doi,
                title,
                abstract,
                pub_date,
                manuscript_text
            ))

            self.stats['total_manuscripts'] += 1

            # Step 2: Insert prompts (deduplicate by ID)
            for prompt_item in prompts_list:
                cursor.execute("""
                    INSERT OR IGNORE INTO prompt (id, prompt_text, model, created_at)
                    VALUES (?, ?, ?, CURRENT_TIMESTAMP)
                """, (
                    prompt_item.get('id'),
                    prompt_item.get('prompt_text', ''),
                    prompt_item.get('model', '')
                ))

            self.stats['total_prompts'] += len(prompts_list)

            # Step 3: Insert claims
            for claim_data in claims_data:
                claim_id = claim_data.get('id')
                # Get prompt_id for claim extraction (usually "extract" type in prompts)
                extract_prompt = prompts_by_type.get('extract', {})
                prompt_id = extract_prompt.get('id')

                cursor.execute("""
                    INSERT OR REPLACE INTO claim (
                        id, manuscript_id, claim_id, claim, claim_type, source_text,
                        evidence_type, evidence_reasoning, prompt_id
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    claim_id,
                    manuscript_id,
                    claim_data.get('claim_id'),  # Simple claim ID like "C1", "C2"
                    claim_data.get('claim', ''),
                    claim_data.get('claim_type', ''),
                    claim_data.get('source_text', ''),
                    json.dumps(claim_data.get('evidence_type', [])),  # Store as JSON array
                    claim_data.get('evidence_reasoning', ''),
                    prompt_id
                ))

            self.stats['total_claims'] += len(claims_data)

            # Step 4: Insert peer review content (if exists)
            peer_id = None
            if peer_review_text:
                peer_id = f"{manuscript_id}-peer"
                cursor.execute("""
                    INSERT OR REPLACE INTO peer (id, manuscript_id, content, created_at)
                    VALUES (?, ?, ?, CURRENT_TIMESTAMP)
                """, (peer_id, manuscript_id, peer_review_text))

            # Step 5: Insert LLM results
            for result_data in results_llm_data:
                result_id = result_data.get('id')
                cursor.execute("""
                    INSERT OR REPLACE INTO result_llm (
                        id, manuscript_id, reviewer_id, reviewer_name,
                        result_status, result_reasoning, prompt_id
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (
                    result_id,
                    manuscript_id,
                    result_data.get('reviewer_id', 'LLM'),
                    result_data.get('reviewer_name', 'LLM'),
                    result_data.get('result_status', ''),
                    result_data.get('result_reasoning', ''),
                    result_data.get('prompt_id')
                ))

            # Insert junction records from claim_results (for LLM results)
            for junction in claim_results_data:
                result_id = junction.get('result_id')
                claim_id = junction.get('claim_id')
                # Check if this result is an LLM result
                if any(r.get('id') == result_id for r in results_llm_data):
                    cursor.execute("""
                        INSERT OR IGNORE INTO claim_result_llm (claim_id, result_llm_id)
                        VALUES (?, ?)
                    """, (claim_id, result_id))

            self.stats['total_results_llm'] += len(results_llm_data)

            # Step 6: Insert peer results (if exist)
            if results_peer_data:
                for result_data in results_peer_data:
                    result_id = result_data.get('id')
                    cursor.execute("""
                        INSERT OR REPLACE INTO result_peer (
                            id, peer_id, reviewer_id, reviewer_name,
                            result_status, result_reasoning, prompt_id
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                    """, (
                        result_id,
                        peer_id,
                        result_data.get('reviewer_id', 'Peer'),
                        result_data.get('reviewer_name', 'Peer'),
                        result_data.get('result_status', ''),
                        result_data.get('result_reasoning', ''),
                        result_data.get('prompt_id')
                    ))

                # Insert junction records from claim_results (for peer results)
                for junction in claim_results_data:
                    result_id = junction.get('result_id')
                    claim_id = junction.get('claim_id')
                    # Check if this result is a peer result
                    if any(r.get('id') == result_id for r in results_peer_data):
                        cursor.execute("""
                            INSERT OR IGNORE INTO claim_result_peer (claim_id, result_peer_id)
                            VALUES (?, ?)
                        """, (claim_id, result_id))

                self.stats['total_results_peer'] += len(results_peer_data)

            # Step 7: Insert comparisons (if exist)
            if comparisons_data:
                compare_prompt = prompts_by_type.get('compare', {})
                compare_prompt_id = compare_prompt.get('id')

                for i, comp_data in enumerate(comparisons_data):
                    comp_id = f"{manuscript_id}-comparison-{i}"
                    cursor.execute("""
                        INSERT OR REPLACE INTO comparison (
                            id, llm_result_id, peer_result_id,
                            llm_status, peer_status, agreement_status, notes,
                            n_llm, n_peer, n_itx,
                            llm_reasoning, peer_reasoning, prompt_id
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        comp_id,
                        comp_data.get('llm_result_id'),
                        comp_data.get('peer_result_id'),
                        comp_data.get('llm_status'),
                        comp_data.get('peer_status'),
                        comp_data.get('agreement_status', ''),
                        comp_data.get('notes'),
                        comp_data.get('n_llm'),
                        comp_data.get('n_peer'),
                        comp_data.get('n_itx'),
                        comp_data.get('llm_reasoning'),
                        comp_data.get('peer_reasoning'),
                        compare_prompt_id
                    ))

                self.stats['total_comparisons'] += len(comparisons_data)

            conn.commit()
            self.stats['total_processed'] += 1

            logger.info(f"✓ Ingested {manuscript_id}: {len(claims_data)} claims, "
                       f"{len(results_llm_data)} LLM results, {len(results_peer_data)} peer results, "
                       f"{len(comparisons_data)} comparisons")

        except Exception as e:
            logger.error(f"✗ Error ingesting {article_id}/{version}: {e}")
            self.stats['errors'] += 1
            conn.rollback()
            raise

    def ingest_all(self, manuscripts_dir: Path, force: bool = False, limit: Optional[int] = None):
        """
        Ingest all manuscripts from directory.

        Args:
            manuscripts_dir: Path to manuscripts directory
            force: If True, re-ingest even if already exists
            limit: Optional limit on number of manuscripts
        """
        conn = sqlite3.connect(self.db_path)

        try:
            files = list(self.find_db_export_files(manuscripts_dir, limit))
            total_files = len(files)

            logger.info(f"Found {total_files} manuscripts to process")

            for i, (article_id, version, file_path) in enumerate(files, 1):
                logger.info(f"[{i}/{total_files}] Processing {article_id}/{version}")

                # Check if already ingested (unless force=True)
                if not force:
                    cursor = conn.cursor()
                    manuscript_id = f"{article_id}-{version}"
                    cursor.execute("SELECT id FROM manuscript WHERE id = ?", (manuscript_id,))
                    if cursor.fetchone():
                        logger.info(f"⏭️  Skipping {manuscript_id} (already exists, use --force to re-ingest)")
                        continue

                self.ingest_manuscript(conn, article_id, version, file_path)

        finally:
            conn.close()

    def print_stats(self):
        """Print ingestion statistics."""
        print("\n" + "=" * 70)
        print("INGESTION STATISTICS")
        print("=" * 70)
        print(f"Total files processed: {self.stats['total_processed']}")
        print(f"Manuscripts ingested: {self.stats['total_manuscripts']}")
        print(f"Claims ingested: {self.stats['total_claims']}")
        print(f"LLM results ingested: {self.stats['total_results_llm']}")
        print(f"Peer results ingested: {self.stats['total_results_peer']}")
        print(f"Comparisons ingested: {self.stats['total_comparisons']}")
        print(f"Unique prompts: {self.stats['total_prompts']}")
        print(f"Errors: {self.stats['errors']}")
        print("=" * 70)


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Ingest manuscripts from db_export.json files"
    )

    parser.add_argument(
        "--manuscripts-dir",
        type=Path,
        required=True,
        help="Path to manuscripts directory"
    )

    parser.add_argument(
        "--force", "-f",
        action="store_true",
        help="Re-ingest even if manuscript already exists"
    )

    parser.add_argument(
        "--limit", "-l",
        type=int,
        default=None,
        help="Limit number of manuscripts to process"
    )

    args = parser.parse_args()

    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )

    # Check manuscripts directory exists
    if not args.manuscripts_dir.exists():
        logger.error(f"Manuscripts directory not found: {args.manuscripts_dir}")
        return 1

    # Initialize database (create tables if they don't exist)
    init_database()

    # Initialize ingester
    ingester = ManuscriptIngester(settings.database_path)

    try:
        # Ingest all manuscripts
        ingester.ingest_all(
            manuscripts_dir=args.manuscripts_dir,
            force=args.force,
            limit=args.limit
        )

        # Print statistics
        ingester.print_stats()

        return 0

    except KeyboardInterrupt:
        logger.info("\n\n⚠️  Interrupted by user")
        ingester.print_stats()
        return 1

    except Exception as e:
        logger.error(f"\n❌ Fatal error: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    exit(main())
