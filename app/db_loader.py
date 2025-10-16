"""
Database loader for CLLM JSON exports.

Imports database-ready JSON from CLLM workflow into SQLite database.
"""

import json
import sqlite3
from pathlib import Path
from typing import Dict, Any, Optional

from app.database import get_db


def load_cllm_export(json_path: Path, user_id: Optional[int] = None) -> str:
    """
    Load CLLM export JSON into database.

    Args:
        json_path: Path to db_export.json file
        user_id: Optional user ID to associate with submission

    Returns:
        submission_id: The ID of the created submission

    Raises:
        ValueError: If JSON is invalid or missing required fields
        sqlite3.IntegrityError: If foreign key constraints are violated
    """
    # Load JSON
    with open(json_path, 'r') as f:
        data = json.load(f)

    with get_db() as conn:
        cursor = conn.cursor()

        # ====================================================================
        # 1. INSERT SUBMISSION
        # ====================================================================
        submission = data['submission']

        # Override user_id if provided
        if user_id is not None:
            submission['user_id'] = user_id

        cursor.execute("""
            INSERT INTO submissions (id, user_id, manuscript_title, manuscript_doi, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            submission['id'],
            submission.get('user_id'),
            submission.get('manuscript_title'),
            submission.get('manuscript_doi'),
            submission['status'],
            submission['created_at'],
            submission['updated_at'],
        ))

        # ====================================================================
        # 2. INSERT CONTENT
        # ====================================================================
        for content in data['content']:
            cursor.execute("""
                INSERT INTO content (id, submission_id, content_type, content_text, created_at)
                VALUES (?, ?, ?, ?, ?)
            """, (
                content['id'],
                content['submission_id'],
                content['content_type'],
                content['content_text'],
                content['created_at'],
            ))

        # ====================================================================
        # 3. INSERT PROMPTS
        # ====================================================================
        for prompt in data['prompts']:
            # Use INSERT OR IGNORE to handle duplicate prompts (same prompt_text + model)
            cursor.execute("""
                INSERT OR IGNORE INTO prompt (id, prompt_text, prompt_type, model, created_at)
                VALUES (?, ?, ?, ?, ?)
            """, (
                prompt['id'],
                prompt['prompt_text'],
                prompt['prompt_type'],
                prompt['model'],
                prompt['created_at'],
            ))

        # ====================================================================
        # 4. INSERT CLAIMS
        # ====================================================================
        for claim in data['claims']:
            cursor.execute("""
                INSERT INTO claim (id, content_id, claim_id, claim, claim_type, source_text, evidence_type, evidence_reasoning, prompt_id, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                claim['id'],
                claim['content_id'],
                claim['claim_id'],
                claim['claim'],
                claim['claim_type'],
                claim['source_text'],
                claim['evidence_type'],
                claim['evidence_reasoning'],
                claim['prompt_id'],
                claim['created_at'],
            ))

        # ====================================================================
        # 5. INSERT RESULTS
        # ====================================================================
        for result in data['results']:
            cursor.execute("""
                INSERT INTO result (id, content_id, result_id, result_type, reviewer_id, reviewer_name, result_status, result_reasoning, prompt_id, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                result['id'],
                result['content_id'],
                result['result_id'],
                result['result_type'],
                result['reviewer_id'],
                result['reviewer_name'],
                result['result_status'],
                result['result_reasoning'],
                result['prompt_id'],
                result['created_at'],
            ))

        # ====================================================================
        # 6. INSERT CLAIM_RESULT JUNCTIONS
        # ====================================================================
        for claim_result in data['claim_results']:
            cursor.execute("""
                INSERT INTO claim_result (claim_id, result_id)
                VALUES (?, ?)
            """, (
                claim_result['claim_id'],
                claim_result['result_id'],
            ))

        # ====================================================================
        # 7. INSERT COMPARISONS
        # ====================================================================
        for comparison in data['comparisons']:
            cursor.execute("""
                INSERT INTO comparison (id, submission_id, llm_result_id, peer_result_id, llm_status, peer_status, agreement_status, notes, prompt_id, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                comparison['id'],
                comparison['submission_id'],
                comparison.get('llm_result_id'),
                comparison.get('peer_result_id'),
                comparison.get('llm_status'),
                comparison.get('peer_status'),
                comparison['agreement_status'],
                comparison.get('notes'),
                comparison['prompt_id'],
                comparison['created_at'],
            ))

        conn.commit()

        print(f"✅ Successfully loaded submission {submission['id']}")
        print(f"   - Content records: {len(data['content'])}")
        print(f"   - Prompts: {len(data['prompts'])}")
        print(f"   - Claims: {len(data['claims'])}")
        print(f"   - Results: {len(data['results'])}")
        print(f"   - Claim-Result links: {len(data['claim_results'])}")
        print(f"   - Comparisons: {len(data['comparisons'])}")

        return submission['id']


def get_submission_summary(submission_id: str) -> Dict[str, Any]:
    """
    Get summary statistics for a submission.

    Args:
        submission_id: The submission ID

    Returns:
        Dictionary with summary statistics
    """
    with get_db() as conn:
        cursor = conn.cursor()

        # Get submission info
        cursor.execute("""
            SELECT s.id, s.manuscript_title, s.manuscript_doi, s.status, s.created_at,
                   u.name as user_name, u.orcid_id
            FROM submissions s
            LEFT JOIN users u ON s.user_id = u.id
            WHERE s.id = ?
        """, (submission_id,))

        submission = cursor.fetchone()
        if not submission:
            raise ValueError(f"Submission {submission_id} not found")

        # Count claims
        cursor.execute("""
            SELECT COUNT(*) FROM claim c
            JOIN content ct ON c.content_id = ct.id
            WHERE ct.submission_id = ?
        """, (submission_id,))
        num_claims = cursor.fetchone()[0]

        # Count LLM results
        cursor.execute("""
            SELECT COUNT(*) FROM result r
            JOIN content ct ON r.content_id = ct.id
            WHERE ct.submission_id = ? AND r.result_type = 'llm'
        """, (submission_id,))
        num_llm_results = cursor.fetchone()[0]

        # Count peer results
        cursor.execute("""
            SELECT COUNT(*) FROM result r
            JOIN content ct ON r.content_id = ct.id
            WHERE ct.submission_id = ? AND r.result_type = 'peer'
        """, (submission_id,))
        num_peer_results = cursor.fetchone()[0]

        # Count comparisons
        cursor.execute("""
            SELECT COUNT(*) FROM comparison
            WHERE submission_id = ?
        """, (submission_id,))
        num_comparisons = cursor.fetchone()[0]

        return {
            "submission_id": submission['id'],
            "manuscript_title": submission['manuscript_title'],
            "manuscript_doi": submission['manuscript_doi'],
            "status": submission['status'],
            "created_at": submission['created_at'],
            "user_name": submission['user_name'],
            "orcid_id": submission['orcid_id'],
            "num_claims": num_claims,
            "num_llm_results": num_llm_results,
            "num_peer_results": num_peer_results,
            "num_comparisons": num_comparisons,
        }


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python -m app.db_loader <path_to_db_export.json> [user_id]")
        sys.exit(1)

    json_path = Path(sys.argv[1])
    user_id = int(sys.argv[2]) if len(sys.argv) > 2 else None

    try:
        submission_id = load_cllm_export(json_path, user_id)
        print(f"\n📊 Summary:")
        summary = get_submission_summary(submission_id)
        for key, value in summary.items():
            print(f"   {key}: {value}")
    except Exception as e:
        print(f"❌ Error: {e}")
        sys.exit(1)
