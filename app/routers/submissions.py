"""
API endpoints for submissions.
"""

import json
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from pydantic import BaseModel

from app.database import get_db
from app.dependencies import get_current_user
from app.db_loader import load_cllm_export, get_submission_summary

router = APIRouter(prefix="/api/submissions", tags=["submissions"])


# ============================================================================
# MODELS
# ============================================================================


class SubmissionCreate(BaseModel):
    """Request to create a new submission."""
    manuscript_title: Optional[str] = None
    manuscript_doi: Optional[str] = None


class SubmissionResponse(BaseModel):
    """Submission information."""
    id: str
    user_id: Optional[int]
    manuscript_title: Optional[str]
    manuscript_doi: Optional[str]
    status: str
    created_at: str
    updated_at: str
    user_name: Optional[str] = None
    orcid_id: Optional[str] = None


class SubmissionSummary(BaseModel):
    """Submission with summary statistics."""
    id: str
    manuscript_title: Optional[str]
    manuscript_doi: Optional[str]
    status: str
    created_at: str
    user_name: Optional[str]
    orcid_id: Optional[str]
    num_claims: int
    num_llm_results: int
    num_peer_results: int
    num_comparisons: int


class ClaimResponse(BaseModel):
    """Claim information."""
    id: str
    content_id: str
    claim_id: str
    claim: str
    claim_type: str
    source_text: str
    evidence_type: str
    evidence_reasoning: str
    prompt_id: str
    created_at: str


class ResultResponse(BaseModel):
    """Result information."""
    id: str
    content_id: str
    result_id: str
    result_type: str
    reviewer_id: str
    reviewer_name: str
    result_status: str
    result_reasoning: str
    prompt_id: str
    created_at: str
    claim_ids: List[str]  # List of claim IDs associated with this result


class ComparisonResponse(BaseModel):
    """Comparison information."""
    id: str
    submission_id: str
    llm_result_id: Optional[str]
    peer_result_id: Optional[str]
    llm_status: Optional[str]
    peer_status: Optional[str]
    agreement_status: str
    notes: Optional[str]
    prompt_id: str
    created_at: str


# ============================================================================
# ENDPOINTS
# ============================================================================


@router.get("/", response_model=List[SubmissionSummary])
def list_submissions(user: dict = Depends(get_current_user)):
    """List all submissions for the current user."""
    with get_db() as conn:
        cursor = conn.cursor()

        cursor.execute("""
            SELECT s.id, s.manuscript_title, s.manuscript_doi, s.status, s.created_at,
                   u.name as user_name, u.orcid_id
            FROM submissions s
            LEFT JOIN users u ON s.user_id = u.id
            WHERE s.user_id = ?
            ORDER BY s.created_at DESC
        """, (user['user_id'],))

        submissions = []
        for row in cursor.fetchall():
            # Get counts for this submission
            summary = get_submission_summary(row['id'])
            submissions.append(SubmissionSummary(**summary))

        return submissions


@router.get("/{submission_id}", response_model=SubmissionSummary)
def get_submission(submission_id: str, user: dict = Depends(get_current_user)):
    """Get submission details."""
    with get_db() as conn:
        cursor = conn.cursor()

        cursor.execute("""
            SELECT s.id, s.user_id
            FROM submissions s
            WHERE s.id = ?
        """, (submission_id,))

        submission = cursor.fetchone()
        if not submission:
            raise HTTPException(status_code=404, detail="Submission not found")

        # Check ownership
        if submission['user_id'] != user['user_id']:
            raise HTTPException(status_code=403, detail="Access denied")

        summary = get_submission_summary(submission_id)
        return SubmissionSummary(**summary)


@router.post("/{submission_id}/import-cllm")
def import_cllm_data(
    submission_id: str,
    file: UploadFile = File(...),
    user: dict = Depends(get_current_user)
):
    """Import CLLM JSON export for an existing submission."""
    # Validate file type
    if not file.filename.endswith('.json'):
        raise HTTPException(status_code=400, detail="File must be a JSON file")

    # Save uploaded file temporarily
    import tempfile
    with tempfile.NamedTemporaryFile(delete=False, suffix='.json') as tmp:
        content = file.file.read()
        tmp.write(content)
        tmp_path = Path(tmp.name)

    try:
        # Load data from JSON
        with open(tmp_path, 'r') as f:
            data = json.load(f)

        # Update submission_id in the data to match the requested ID
        data['submission']['id'] = submission_id
        data['submission']['user_id'] = user['user_id']

        # Update all references to submission_id
        for content in data['content']:
            content['submission_id'] = submission_id
        for comparison in data['comparisons']:
            comparison['submission_id'] = submission_id

        # Write modified data back
        with open(tmp_path, 'w') as f:
            json.dump(data, f)

        # Import into database
        loaded_id = load_cllm_export(tmp_path, user_id=user['user_id'])

        # Get summary
        summary = get_submission_summary(loaded_id)

        return {
            "status": "success",
            "message": f"Successfully imported data for submission {loaded_id}",
            "summary": summary
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Import failed: {str(e)}")
    finally:
        # Clean up temp file
        tmp_path.unlink(missing_ok=True)


@router.get("/{submission_id}/claims", response_model=List[ClaimResponse])
def get_claims(submission_id: str, user: dict = Depends(get_current_user)):
    """Get all claims for a submission."""
    with get_db() as conn:
        cursor = conn.cursor()

        # Check ownership
        cursor.execute("SELECT user_id FROM submissions WHERE id = ?", (submission_id,))
        submission = cursor.fetchone()
        if not submission:
            raise HTTPException(status_code=404, detail="Submission not found")
        if submission['user_id'] != user['user_id']:
            raise HTTPException(status_code=403, detail="Access denied")

        # Get claims
        cursor.execute("""
            SELECT c.*
            FROM claim c
            JOIN content ct ON c.content_id = ct.id
            WHERE ct.submission_id = ?
            ORDER BY c.claim_id
        """, (submission_id,))

        claims = [dict(row) for row in cursor.fetchall()]
        return claims


@router.get("/{submission_id}/results", response_model=List[ResultResponse])
def get_results(submission_id: str, result_type: Optional[str] = None, user: dict = Depends(get_current_user)):
    """Get all results for a submission. Optionally filter by result_type ('llm' or 'peer')."""
    with get_db() as conn:
        cursor = conn.cursor()

        # Check ownership
        cursor.execute("SELECT user_id FROM submissions WHERE id = ?", (submission_id,))
        submission = cursor.fetchone()
        if not submission:
            raise HTTPException(status_code=404, detail="Submission not found")
        if submission['user_id'] != user['user_id']:
            raise HTTPException(status_code=403, detail="Access denied")

        # Build query
        if result_type:
            if result_type not in ['llm', 'peer']:
                raise HTTPException(status_code=400, detail="result_type must be 'llm' or 'peer'")

            cursor.execute("""
                SELECT r.*
                FROM result r
                JOIN content ct ON r.content_id = ct.id
                WHERE ct.submission_id = ? AND r.result_type = ?
                ORDER BY r.result_id
            """, (submission_id, result_type))
        else:
            cursor.execute("""
                SELECT r.*
                FROM result r
                JOIN content ct ON r.content_id = ct.id
                WHERE ct.submission_id = ?
                ORDER BY r.result_type, r.result_id
            """, (submission_id,))

        results = []
        for row in cursor.fetchall():
            result = dict(row)

            # Get claim_ids for this result
            cursor.execute("""
                SELECT c.claim_id
                FROM claim_result cr
                JOIN claim c ON cr.claim_id = c.id
                WHERE cr.result_id = ?
                ORDER BY c.claim_id
            """, (result['id'],))

            result['claim_ids'] = [r['claim_id'] for r in cursor.fetchall()]
            results.append(result)

        return results


@router.get("/{submission_id}/comparison", response_model=List[ComparisonResponse])
def get_comparison(submission_id: str, user: dict = Depends(get_current_user)):
    """Get comparison results for a submission."""
    with get_db() as conn:
        cursor = conn.cursor()

        # Check ownership
        cursor.execute("SELECT user_id FROM submissions WHERE id = ?", (submission_id,))
        submission = cursor.fetchone()
        if not submission:
            raise HTTPException(status_code=404, detail="Submission not found")
        if submission['user_id'] != user['user_id']:
            raise HTTPException(status_code=403, detail="Access denied")

        # Get comparisons
        cursor.execute("""
            SELECT *
            FROM comparison
            WHERE submission_id = ?
            ORDER BY created_at
        """, (submission_id,))

        comparisons = [dict(row) for row in cursor.fetchall()]
        return comparisons


@router.delete("/{submission_id}")
def delete_submission(submission_id: str, user: dict = Depends(get_current_user)):
    """Delete a submission and all associated data."""
    with get_db() as conn:
        cursor = conn.cursor()

        # Check ownership
        cursor.execute("SELECT user_id FROM submissions WHERE id = ?", (submission_id,))
        submission = cursor.fetchone()
        if not submission:
            raise HTTPException(status_code=404, detail="Submission not found")
        if submission['user_id'] != user['user_id']:
            raise HTTPException(status_code=403, detail="Access denied")

        # Delete submission (cascade will handle related records)
        cursor.execute("DELETE FROM submissions WHERE id = ?", (submission_id,))
        conn.commit()

        return {"status": "success", "message": f"Submission {submission_id} deleted"}
