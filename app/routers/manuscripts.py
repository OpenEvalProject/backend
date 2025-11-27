"""
Manuscripts API router.

Endpoints for listing and viewing manuscripts with their claims, results, and comparisons.
"""

import logging
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from app.database import get_db
from app.db_queries import get_manuscript_detail, get_manuscripts_list
from app.models import AggregateStatistics, ErrorResponse, ManuscriptDetail, ManuscriptListResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/manuscripts", tags=["manuscripts"])


@router.get("/stats", response_model=AggregateStatistics)
async def get_aggregate_statistics():
    """
    Get aggregate statistics across all manuscripts.

    Returns:
    - Total number of manuscripts
    - Total claims extracted
    - Total LLM results
    - Total peer results
    - Total comparisons/assessments
    """
    try:
        with get_db() as conn:
            cursor = conn.cursor()

            # Count submissions (manuscripts)
            cursor.execute("SELECT COUNT(*) FROM submission")
            total_manuscripts = cursor.fetchone()[0]

            # Count claims
            cursor.execute("SELECT COUNT(*) FROM claim")
            total_claims = cursor.fetchone()[0]

            # Count LLM results (from unified result table)
            cursor.execute("SELECT COUNT(*) FROM result WHERE result_category = 'llm'")
            total_llm_results = cursor.fetchone()[0]

            # Count peer results (from unified result table)
            cursor.execute("SELECT COUNT(*) FROM result WHERE result_category = 'peer'")
            total_peer_results = cursor.fetchone()[0]

            # Count comparisons
            cursor.execute("SELECT COUNT(*) FROM comparison")
            total_comparisons = cursor.fetchone()[0]

            # Count submissions with peer reviews that were successfully evaluated
            # (have comparisons between OpenEval and peer results)
            cursor.execute("""
                SELECT COUNT(DISTINCT c.submission_id)
                FROM comparison cmp
                INNER JOIN result r ON (r.id = cmp.openeval_result_id OR r.id = cmp.peer_result_id)
                INNER JOIN content c ON c.id = r.content_id
            """)
            manuscripts_with_peer_reviews = cursor.fetchone()[0]

            return AggregateStatistics(
                total_manuscripts=total_manuscripts,
                total_claims=total_claims,
                total_llm_results=total_llm_results,
                total_peer_results=total_peer_results,
                total_comparisons=total_comparisons,
                manuscripts_with_peer_reviews=manuscripts_with_peer_reviews
            )

    except Exception as e:
        logger.error(f"Error getting aggregate statistics: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Error retrieving statistics: {str(e)}"
        )


@router.get("", response_model=ManuscriptListResponse)
async def list_manuscripts(
    limit: Optional[int] = Query(50, description="Maximum number of manuscripts to return (default: 50)"),
    offset: int = Query(0, description="Number of manuscripts to skip")
):
    """
    Get list of all manuscripts with summary information.

    Returns manuscript list with:
    - Basic metadata (id, title, date)
    - Total claim count
    - Agreement counts (if peer reviews exist)

    Default limit is 50 manuscripts for faster initial load.
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


@router.get("/{manuscript_id}/markdown")
async def get_manuscript_markdown(manuscript_id: str):
    """
    Convert JATS XML to Markdown for a manuscript.

    This endpoint:
    1. Looks up the JATS XML file path from the database
    2. Calls the jats CLI tool to convert XML to markdown
    3. Returns the markdown content

    Args:
        manuscript_id: The submission ID

    Returns:
        JSON with markdown content, submission_id, and version

    Raises:
        404: If manuscript or JATS file not found
        500: If conversion fails
    """
    try:
        with get_db() as conn:
            cursor = conn.cursor()

            # Check if manuscript exists
            cursor.execute("SELECT id FROM submission WHERE id = ?", (manuscript_id,))
            if not cursor.fetchone():
                raise HTTPException(
                    status_code=404,
                    detail=f"Manuscript not found: {manuscript_id}"
                )

            # Get JATS file path
            cursor.execute(
                "SELECT xml_rel_path, version FROM jats WHERE submission_id = ?",
                (manuscript_id,)
            )
            jats_record = cursor.fetchone()

            if not jats_record:
                raise HTTPException(
                    status_code=404,
                    detail=f"JATS XML file not available for manuscript: {manuscript_id}"
                )

            xml_rel_path, version = jats_record

            # Resolve full path relative to the database location
            # The database is in backend/claim_verification.db
            # xml_rel_path is stored relative to the database location
            # __file__ is backend/app/routers/manuscripts.py, so go up 2 levels to get to backend/
            backend_dir = Path(__file__).parent.parent.parent

            # IMPORTANT: XML files may be symlinks. We need the parent directory of the symlink
            # (where pos_claims.json is stored), not the parent of the symlink target.
            # So we construct the path but don't resolve it yet.
            xml_path_unresolved = backend_dir / xml_rel_path
            xml_dir = xml_path_unresolved.parent

            # Now resolve for actual file operations
            xml_full_path = xml_path_unresolved.resolve()

            # Check if file exists
            if not xml_full_path.exists():
                logger.error(f"JATS file not found: {xml_full_path}")
                raise HTTPException(
                    status_code=404,
                    detail=f"JATS XML file not found at: {xml_rel_path}"
                )

            # Check for pos_claims.json to use annotated XML if available
            # Version is already like "v1", so just use it directly
            pos_claims_path = xml_dir / version / "pos_claims.json"

            xml_to_convert = xml_full_path

            # If pos_claims.json exists, create annotated XML
            if pos_claims_path.exists():
                try:
                    import tempfile
                    from jats.annotate import inject_named_content_tags

                    logger.info(f"Using annotated XML with pos_claims from {pos_claims_path}")

                    # Create annotated XML
                    annotated_root, successful, failed = inject_named_content_tags(
                        xml_full_path,
                        pos_claims_path
                    )

                    logger.info(f"Annotation complete: {successful} successful, {failed} failed")

                    # Write annotated XML to temporary file
                    with tempfile.NamedTemporaryFile(mode='wb', suffix='.xml', delete=False) as tmp:
                        from lxml import etree
                        tree = etree.ElementTree(annotated_root)
                        tree.write(tmp, encoding='utf-8', xml_declaration=True)
                        tmp_path = tmp.name

                    xml_to_convert = Path(tmp_path)

                except Exception as annotation_error:
                    logger.warning(f"Annotation failed, falling back to plain XML: {annotation_error}")
                    xml_to_convert = xml_full_path

            # Convert JATS XML to markdown using the jats library
            try:
                from app.services.jats_parser import parse_jats_xml

                markdown_content = parse_jats_xml(str(xml_to_convert))

                # Clean up temporary file if created
                if xml_to_convert != xml_full_path:
                    try:
                        xml_to_convert.unlink()
                    except:
                        pass

                return {
                    "markdown": markdown_content,
                    "submission_id": manuscript_id,
                    "version": version
                }

            except Exception as conversion_error:
                logger.error(f"JATS conversion failed: {conversion_error}")
                raise HTTPException(
                    status_code=500,
                    detail=f"Failed to convert JATS XML to markdown: {str(conversion_error)}"
                )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error converting manuscript {manuscript_id} to markdown: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Error converting to markdown: {str(e)}"
        )
