"""
Manuscripts API router.

Endpoints for listing and viewing manuscripts with their claims, results, and comparisons.
"""

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from app.database import get_db
from app.db_queries import get_manuscript_detail, get_manuscripts_list
from app.models import ErrorResponse, ManuscriptDetail, ManuscriptListResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/manuscripts", tags=["manuscripts"])


@router.get("", response_model=ManuscriptListResponse)
async def list_manuscripts(
    limit: Optional[int] = Query(None, description="Maximum number of manuscripts to return"),
    offset: int = Query(0, description="Number of manuscripts to skip")
):
    """
    Get list of all manuscripts with summary information.

    Returns manuscript list with:
    - Basic metadata (id, title, date)
    - Total claim count
    - Agreement counts (if peer reviews exist)
    """
    try:
        with get_db() as conn:
            manuscripts, total_count = get_manuscripts_list(conn, limit=limit, offset=offset)

            return ManuscriptListResponse(
                manuscripts=manuscripts,
                total_count=total_count
            )

    except Exception as e:
        logger.error(f"Error listing manuscripts: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Error retrieving manuscripts: {str(e)}"
        )


@router.get("/{manuscript_id}", response_model=ManuscriptDetail)
async def get_manuscript(manuscript_id: str):
    """
    Get complete details for a single manuscript.

    Returns:
    - Manuscript metadata
    - Summary statistics
    - All claims (full objects)
    - All LLM results (with claim IDs)
    - All peer results (with claim IDs, if exist)
    - All comparisons (if exist)
    """
    try:
        with get_db() as conn:
            manuscript = get_manuscript_detail(conn, manuscript_id)

            if not manuscript:
                raise HTTPException(
                    status_code=404,
                    detail=f"Manuscript not found: {manuscript_id}"
                )

            return manuscript

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error retrieving manuscript {manuscript_id}: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Error retrieving manuscript: {str(e)}"
        )
