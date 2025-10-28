"""
Load CLLM db_export.json files into the new submission/content-based database.

UPDATED: 2025-10-25 to support new schema with submission/content tables
and unified result table with result_category field.
"""

import json
import os
import sqlite3
import sys
from pathlib import Path
from typing import Dict, Any, Optional

def load_cllm_export(db_path: str, json_path: str) -> str:
    """
    Load CLLM export JSON into submission/content-based database.

    Args:
        db_path: Path to SQLite database
        json_path: Path to db_export.json file

    Returns:
        submission_id: The ID of the created submission
    """
    # Load JSON
    with open(json_path, 'r') as f:
        data = json.load(f)

    # Load manuscript metadata from adjacent file
    json_path_obj = Path(json_path)
    metadata_path = json_path_obj.parent / "manuscript_metadata.json"
    metadata = {}
    if metadata_path.exists():
        with open(metadata_path, 'r') as f:
            metadata = json.load(f)

    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    cursor = conn.cursor()

    try:
        # Get submission data
        submission = data['submission']
        submission_id = submission['id']

        # Use metadata file for title, DOI, pub_date, and abstract if available
        title = metadata.get('title') or submission.get('manuscript_title')
        doi = metadata.get('doi') or submission.get('manuscript_doi')
        pub_date = metadata.get('pub_date')
        abstract = metadata.get('abstract')

        # If title still not found, extract from manuscript content
        if not title:
            manuscript_content = next((c for c in data['content'] if c['content_type'] == 'manuscript'), None)
            if manuscript_content:
                content_lines = manuscript_content['content_text'].split('\n')
                title = content_lines[0].strip('# ') if content_lines else 'Untitled'

        # ====================================================================
        # 1. INSERT SUBMISSION
        # ====================================================================
        cursor.execute("""
            INSERT INTO submission (id, user_id, manuscript_title, manuscript_doi, manuscript_pub_date, manuscript_abstract, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            submission_id,
            submission.get('user_id'),
            title,
            doi,
            pub_date,
            abstract,
            submission['status'],
            submission['created_at'],
            submission['updated_at']
        ))

        # ====================================================================
        # 2. INSERT AUTHORS AND AFFILIATIONS
        # ====================================================================
        # Maps affiliation_id (from JSON) to database affiliation.id
        affiliation_id_map: Dict[str, int] = {}

        # Insert affiliations first (from metadata)
        for aff in metadata.get('affiliations', []):
            cursor.execute("""
                INSERT INTO affiliation (submission_id, affiliation_id, institution, department, city, country)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                submission_id,
                aff['id'],
                aff.get('institution'),
                aff.get('department'),
                aff.get('city'),
                aff.get('country')
            ))
            # Map the JSON affiliation_id to database auto-increment id
            affiliation_id_map[aff['id']] = cursor.lastrowid

        # Insert authors (from metadata)
        for author in metadata.get('authors', []):
            cursor.execute("""
                INSERT INTO author (submission_id, given_names, surname, orcid, corresponding, position)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                submission_id,
                author['given_names'],
                author['surname'],
                author.get('orcid'),
                1 if author.get('corresponding') else 0,
                author['position']
            ))
            author_db_id = cursor.lastrowid

            # Create author-affiliation links
            for aff_id in author.get('affiliation_ids', []):
                if aff_id in affiliation_id_map:
                    cursor.execute("""
                        INSERT INTO author_affiliation (author_id, affiliation_id)
                        VALUES (?, ?)
                    """, (
                        author_db_id,
                        affiliation_id_map[aff_id]
                    ))

        # ====================================================================
        # 3. INSERT JATS FILE PATH
        # ====================================================================
        # Look for JATS XML file in the parent directory (manuscript directory)
        # json_path_obj.parent is the version directory (e.g., v1/)
        # Go up one more level to get the manuscript directory
        manuscript_dir = json_path_obj.resolve().parent.parent
        manuscript_id = manuscript_dir.name  # e.g., "elife-00003"
        version_dir_name = json_path_obj.resolve().parent.name  # e.g., "v1"

        # Pattern: {manuscript_id}-{version}.xml (e.g., elife-00003-v1.xml)
        jats_files = list(manuscript_dir.glob(f"{manuscript_id}-{version_dir_name}.xml"))

        if jats_files:
            # Use the first match (should only be one)
            jats_file = jats_files[0]
            # Extract version from directory name (e.g., "v1")
            version = version_dir_name
            # Store relative path from database location (backend/)
            # Database will be at backend/claim_verification.db
            # Use os.path.relpath to compute relative path from backend/ to jats_file
            # This will correctly use ../ to go up when needed
            db_dir = Path(__file__).resolve().parent
            rel_path = Path(os.path.relpath(jats_file, db_dir))

            cursor.execute("""
                INSERT INTO jats (submission_id, xml_rel_path, version)
                VALUES (?, ?, ?)
            """, (
                submission_id,
                str(rel_path),
                version
            ))

        # ====================================================================
        # 4. INSERT CONTENT (manuscript and peer_review)
        # ====================================================================
        content_id_map = {}  # Map old content IDs to new ones
        for content in data['content']:
            cursor.execute("""
                INSERT INTO content (id, submission_id, content_type, content_text, created_at)
                VALUES (?, ?, ?, ?, ?)
            """, (
                content['id'],
                submission_id,
                content['content_type'],
                content['content_text'],
                content['created_at']
            ))
            content_id_map[content['id']] = content['id']

        # ====================================================================
        # 5. INSERT PROMPTS
        # ====================================================================
        for prompt in data['prompts']:
            cursor.execute("""
                INSERT OR IGNORE INTO prompt (id, prompt_text, prompt_type, model, created_at)
                VALUES (?, ?, ?, ?, ?)
            """, (
                prompt['id'],
                prompt['prompt_text'],
                prompt.get('prompt_type'),  # May be None for old exports
                prompt['model'],
                prompt['created_at']
            ))

        # ====================================================================
        # 6. INSERT CLAIMS
        # ====================================================================
        for claim in data['claims']:
            # Convert source_text to source, evidence_reasoning to evidence
            cursor.execute("""
                INSERT INTO claim (id, content_id, claim_id, claim, claim_type, source,
                                   source_type, evidence, evidence_type, prompt_id, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                claim['id'],
                claim['content_id'],  # Now links to content table
                claim['claim_id'],
                claim['claim'],
                claim['claim_type'],
                claim.get('source') or claim.get('source_text', ''),  # Handle both old and new field names
                claim['source_type'],  # JSON string like '["TEXT"]'
                claim.get('evidence') or claim.get('evidence_reasoning', ''),  # Handle both old and new field names
                claim['evidence_type'],  # JSON string like '["CITATION", "KNOWLEDGE"]'
                claim['prompt_id'],
                claim['created_at']
            ))

        # ====================================================================
        # 7. INSERT RESULTS (unified table)
        # ====================================================================
        for result in data['results']:
            cursor.execute("""
                INSERT INTO result (id, content_id, result_id, result_category, result,
                                   result_status, result_reasoning, reviewer_id, reviewer_name,
                                   prompt_id, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                result['id'],
                result['content_id'],  # Now links to content table
                result.get('result_id'),
                result['result_category'],  # 'llm' or 'peer'
                result['result'],
                result.get('evaluation_type') or result.get('result_status', 'UNCERTAIN'),  # evaluation_type is the new field name
                result.get('evaluation') or result.get('result_reasoning', ''),  # evaluation is the new field name
                result.get('reviewer_id'),
                result.get('reviewer_name'),
                result.get('prompt_id'),
                result['created_at']
            ))

        # ====================================================================
        # 8. INSERT CLAIM_RESULT JUNCTIONS
        # ====================================================================
        for claim_result in data['claim_results']:
            cursor.execute("""
                INSERT INTO claim_result (claim_id, result_id)
                VALUES (?, ?)
            """, (
                claim_result['claim_id'],
                claim_result['result_id']
            ))

        # ====================================================================
        # 9. INSERT COMPARISONS
        # ====================================================================
        for comparison in data['comparisons']:
            cursor.execute("""
                INSERT INTO comparison (id, openeval_result_id, peer_result_id, openeval_status,
                                       peer_status, agreement_status, comparison, n_openeval,
                                       n_peer, n_itx, openeval_reasoning, peer_reasoning,
                                       openeval_result_type, peer_result_type, prompt_id, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                comparison['id'],
                comparison.get('openeval_result_id'),
                comparison.get('peer_result_id'),
                comparison.get('openeval_evaluation_type') or comparison.get('openeval_status'),  # NEW: openeval_evaluation_type
                comparison.get('peer_evaluation_type') or comparison.get('peer_status'),  # NEW: peer_evaluation_type
                comparison.get('comparison_type') or comparison.get('agreement_status', 'unknown'),  # NEW: comparison_type
                comparison.get('comparison'),
                comparison.get('n_openeval'),  # May not exist in new format
                comparison.get('n_peer'),      # May not exist in new format
                comparison.get('n_itx'),       # May not exist in new format
                comparison.get('openeval_reasoning'),  # May not exist in new format
                comparison.get('peer_reasoning'),      # May not exist in new format
                comparison.get('openeval_result_type'),
                comparison.get('peer_result_type'),
                comparison['prompt_id'],
                comparison['created_at']
            ))

        conn.commit()

        print(f"✅ Successfully loaded submission {submission_id}")
        print(f"   Title: {title}")
        print(f"   Authors: {len(metadata.get('authors', []))}")
        print(f"   Affiliations: {len(metadata.get('affiliations', []))}")
        print(f"   JATS file: {'Found' if jats_files else 'Not found'}")
        print(f"   Claims: {len(data['claims'])}")
        print(f"   Results: {len(data['results'])}")
        print(f"   Comparisons: {len(data['comparisons'])}")

        return submission_id

    except Exception as e:
        conn.rollback()
        print(f"❌ Error loading {json_path}: {e}")
        import traceback
        traceback.print_exc()
        raise
    finally:
        conn.close()


def load_all_from_directory(db_path: str, eval_dir: str):
    """
    Load all db_export.json files from eval directory.

    Args:
        db_path: Path to SQLite database
        eval_dir: Path to eval directory containing manuscripts
    """
    eval_path = Path(eval_dir)
    export_files = list(eval_path.rglob("db_export.json"))

    print(f"Found {len(export_files)} db_export.json files")

    loaded = 0
    failed = 0
    failed_files = []

    for export_file in sorted(export_files):
        try:
            load_cllm_export(db_path, str(export_file))
            loaded += 1
        except Exception as e:
            print(f"Failed to load {export_file}: {e}")
            failed += 1
            failed_files.append(str(export_file))

    print(f"\n📊 Summary:")
    print(f"   Loaded: {loaded}")
    print(f"   Failed: {failed}")

    if failed_files:
        print(f"\n❌ Failed files:")
        for f in failed_files:
            print(f"   - {f}")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python load_cllm_data.py <db_path> <eval_dir>")
        print("Example: python load_cllm_data.py claim_verification.db ../evals/manuscripts")
        sys.exit(1)

    db_path = sys.argv[1]
    eval_dir = sys.argv[2]

    load_all_from_directory(db_path, eval_dir)
