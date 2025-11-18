"""
Database query helpers for manuscripts API.

These functions encapsulate complex database queries and return
structured data for the API endpoints.
"""

import json
import sqlite3
from typing import Dict, List, Optional

from app.models import (
    ClaimFull,
    ComparisonFull,
    ManuscriptDetail,
    ManuscriptMetadata,
    ManuscriptSummary,
    ManuscriptSummaryStats,
    ResultLLM,
    ResultPeer,
)


def get_manuscripts_list(
    conn: sqlite3.Connection,
    limit: Optional[int] = None,
    offset: int = 0
) -> tuple[List[ManuscriptSummary], int]:
    """
    Get list of all submissions (manuscripts) with summary information.

    Args:
        conn: Database connection
        limit: Optional limit on number of results
        offset: Offset for pagination

    Returns:
        Tuple of (list of ManuscriptSummary, total_count)
    """
    cursor = conn.cursor()

    # Count total submissions
    cursor.execute("SELECT COUNT(*) FROM submission")
    total_count = cursor.fetchone()[0]

    # Build query using scalar subqueries for better performance
    # NEW: Works with submission/content/unified result tables
    query = """
        SELECT
            s.id,
            s.manuscript_title,
            s.manuscript_pub_date,
            s.created_at,
            (SELECT COUNT(DISTINCT c.id) FROM claim c
             JOIN content ct ON c.content_id = ct.id
             WHERE ct.submission_id = s.id) as total_claims,
            (SELECT COUNT(*) FROM result r
             JOIN content ct ON r.content_id = ct.id
             WHERE ct.submission_id = s.id AND r.result_category = 'llm') as total_results_llm,
            (SELECT COUNT(*) FROM result r
             JOIN content ct ON r.content_id = ct.id
             WHERE ct.submission_id = s.id AND r.result_category = 'peer') as total_results_peer,
            (SELECT COUNT(*) > 0 FROM content
             WHERE submission_id = s.id AND content_type = 'peer_review') as has_peer_reviews,
            (SELECT COUNT(*) FROM comparison cmp
             JOIN result r ON cmp.openeval_result_id = r.id
             JOIN content ct ON r.content_id = ct.id
             WHERE ct.submission_id = s.id) as total_comparisons,
            (SELECT COUNT(*) FROM comparison cmp
             JOIN result r ON cmp.openeval_result_id = r.id
             JOIN content ct ON r.content_id = ct.id
             WHERE ct.submission_id = s.id AND cmp.agreement_status = 'agree') as agree_count,
            (SELECT COUNT(*) FROM comparison cmp
             JOIN result r ON cmp.openeval_result_id = r.id
             JOIN content ct ON r.content_id = ct.id
             WHERE ct.submission_id = s.id AND cmp.agreement_status = 'partial') as partial_count,
            (SELECT COUNT(*) FROM comparison cmp
             JOIN result r ON cmp.openeval_result_id = r.id
             JOIN content ct ON r.content_id = ct.id
             WHERE ct.submission_id = s.id AND cmp.agreement_status = 'disagree') as disagree_count,
            (SELECT COUNT(*) FROM comparison cmp
             JOIN result r ON cmp.openeval_result_id = r.id
             JOIN content ct ON r.content_id = ct.id
             WHERE ct.submission_id = s.id AND cmp.agreement_status = 'disjoint') as disjoint_count
        FROM submission s
        ORDER BY s.created_at DESC
    """

    if limit:
        query += f" LIMIT {limit} OFFSET {offset}"

    cursor.execute(query)
    rows = cursor.fetchall()

    manuscripts = []
    for row in rows:
        has_peer_reviews = bool(row[7])
        manuscripts.append(ManuscriptSummary(
            id=row[0],
            title=row[1],
            pub_date=row[2],
            created_at=row[3],
            total_claims=row[4],
            total_results_llm=row[5],
            total_results_peer=row[6],
            has_peer_reviews=has_peer_reviews,
            total_comparisons=row[8],
            agree_count=row[9] if has_peer_reviews else None,
            partial_count=row[10] if has_peer_reviews else None,
            disagree_count=row[11] if has_peer_reviews else None,
            disjoint_count=row[12] if has_peer_reviews else None
        ))

    return manuscripts, total_count


def get_manuscript_detail(
    conn: sqlite3.Connection,
    manuscript_id: str
) -> Optional[ManuscriptDetail]:
    """
    Get complete details for a single submission (manuscript).

    Args:
        conn: Database connection
        manuscript_id: Submission ID

    Returns:
        ManuscriptDetail or None if not found
    """
    cursor = conn.cursor()

    # Get submission metadata with JATS availability check
    cursor.execute("""
        SELECT
            s.id,
            s.manuscript_doi,
            s.manuscript_title,
            s.manuscript_pub_date,
            s.manuscript_abstract,
            s.created_at,
            (SELECT COUNT(*) > 0 FROM jats WHERE submission_id = s.id) as has_jats
        FROM submission s
        WHERE s.id = ?
    """, (manuscript_id,))

    row = cursor.fetchone()
    if not row:
        return None

    metadata = ManuscriptMetadata(
        id=row[0],
        doi=row[1],
        title=row[2],
        pub_date=row[3],
        abstract=row[4],
        created_at=row[5],
        has_jats=bool(row[6])
    )

    # Get summary stats with status and agreement counts (NEW: submission/content model)
    cursor.execute("""
        SELECT
               (SELECT COUNT(DISTINCT c.id) FROM claim c
                JOIN content ct ON c.content_id = ct.id
                WHERE ct.submission_id = s.id) as total_claims,
               (SELECT COUNT(*) FROM result r
                JOIN content ct ON r.content_id = ct.id
                WHERE ct.submission_id = s.id AND r.result_category = 'llm') as total_results_llm,
               (SELECT COUNT(*) FROM result r
                JOIN content ct ON r.content_id = ct.id
                WHERE ct.submission_id = s.id AND r.result_category = 'peer') as total_results_peer,
               (SELECT COUNT(*) > 0 FROM content
                WHERE submission_id = s.id AND content_type = 'peer_review') as has_peer_reviews,
               (SELECT COUNT(*) FROM comparison cmp
                JOIN result r ON cmp.openeval_result_id = r.id
                JOIN content ct ON r.content_id = ct.id
                WHERE ct.submission_id = s.id) as total_comparisons,
               (SELECT COUNT(*) FROM result r
                JOIN content ct ON r.content_id = ct.id
                WHERE ct.submission_id = s.id AND r.result_category = 'llm' AND r.result_status = 'SUPPORTED') as llm_supported_count,
               (SELECT COUNT(*) FROM result r
                JOIN content ct ON r.content_id = ct.id
                WHERE ct.submission_id = s.id AND r.result_category = 'llm' AND r.result_status = 'UNSUPPORTED') as llm_unsupported_count,
               (SELECT COUNT(*) FROM result r
                JOIN content ct ON r.content_id = ct.id
                WHERE ct.submission_id = s.id AND r.result_category = 'llm' AND r.result_status = 'UNCERTAIN') as llm_uncertain_count,
               (SELECT COUNT(*) FROM result r
                JOIN content ct ON r.content_id = ct.id
                WHERE ct.submission_id = s.id AND r.result_category = 'peer' AND r.result_status = 'SUPPORTED') as peer_supported_count,
               (SELECT COUNT(*) FROM result r
                JOIN content ct ON r.content_id = ct.id
                WHERE ct.submission_id = s.id AND r.result_category = 'peer' AND r.result_status = 'UNSUPPORTED') as peer_unsupported_count,
               (SELECT COUNT(*) FROM result r
                JOIN content ct ON r.content_id = ct.id
                WHERE ct.submission_id = s.id AND r.result_category = 'peer' AND r.result_status = 'UNCERTAIN') as peer_uncertain_count,
               (SELECT COUNT(*) FROM comparison cmp
                JOIN result r ON cmp.openeval_result_id = r.id
                JOIN content ct ON r.content_id = ct.id
                WHERE ct.submission_id = s.id AND cmp.agreement_status = 'agree') as agree_count,
               (SELECT COUNT(*) FROM comparison cmp
                JOIN result r ON cmp.openeval_result_id = r.id
                JOIN content ct ON r.content_id = ct.id
                WHERE ct.submission_id = s.id AND cmp.agreement_status = 'partial') as partial_count,
               (SELECT COUNT(*) FROM comparison cmp
                JOIN result r ON cmp.openeval_result_id = r.id
                JOIN content ct ON r.content_id = ct.id
                WHERE ct.submission_id = s.id AND cmp.agreement_status = 'disagree') as disagree_count,
               (SELECT COUNT(*) FROM comparison cmp
                JOIN result r ON cmp.openeval_result_id = r.id
                JOIN content ct ON r.content_id = ct.id
                WHERE ct.submission_id = s.id AND cmp.agreement_status = 'disjoint') as disjoint_count
        FROM submission s
        WHERE s.id = ?
    """, (manuscript_id,))

    row = cursor.fetchone()
    has_peer_reviews = bool(row[3])
    summary_stats = ManuscriptSummaryStats(
        total_claims=row[0],
        total_results_llm=row[1],
        total_results_peer=row[2],
        has_peer_reviews=has_peer_reviews,
        total_comparisons=row[4],
        llm_supported_count=row[5],
        llm_unsupported_count=row[6],
        llm_uncertain_count=row[7],
        peer_supported_count=row[8] if has_peer_reviews else None,
        peer_unsupported_count=row[9] if has_peer_reviews else None,
        peer_uncertain_count=row[10] if has_peer_reviews else None,
        agree_count=row[11] if has_peer_reviews else None,
        partial_count=row[12] if has_peer_reviews else None,
        disagree_count=row[13] if has_peer_reviews else None,
        disjoint_count=row[14] if has_peer_reviews else None
    )

    # Get all claims
    claims = get_claims_for_manuscript(conn, manuscript_id)

    # Get LLM results with claim IDs
    results_llm = get_results_llm_for_manuscript(conn, manuscript_id)

    # Get peer results with claim IDs (if exist)
    results_peer = get_results_peer_for_manuscript(conn, manuscript_id)

    # Get comparisons (if exist)
    comparisons = get_comparisons_for_manuscript(conn, manuscript_id)

    return ManuscriptDetail(
        metadata=metadata,
        summary_stats=summary_stats,
        claims=claims,
        results_llm=results_llm,
        results_peer=results_peer,
        comparisons=comparisons
    )


def get_claims_for_manuscript(
    conn: sqlite3.Connection,
    manuscript_id: str
) -> List[ClaimFull]:
    """Get all claims for a submission (manuscript)."""
    cursor = conn.cursor()

    # NEW: Join through content table to get claims for submission
    cursor.execute("""
        SELECT c.id, c.claim_id, c.claim, c.claim_type, c.source, c.source_type, c.evidence, c.evidence_type,
               c.matched_segment, c.xpath_start, c.xpath_stop, c.char_offset_start, c.char_offset_stop
        FROM claim c
        JOIN content ct ON c.content_id = ct.id
        WHERE ct.submission_id = ?
        ORDER BY c.id
    """, (manuscript_id,))

    claims = []
    for row in cursor.fetchall():
        # Parse source_type JSON array
        source_type_raw = row[5]
        if source_type_raw:
            source_type_parsed = json.loads(source_type_raw)
            # If still a string, parse again
            if isinstance(source_type_parsed, str):
                source_type = json.loads(source_type_parsed)
            else:
                source_type = source_type_parsed
        else:
            source_type = []

        # Parse evidence_type JSON array
        evidence_type_raw = row[7]
        if evidence_type_raw:
            evidence_type_parsed = json.loads(evidence_type_raw)
            # If still a string, parse again
            if isinstance(evidence_type_parsed, str):
                evidence_type = json.loads(evidence_type_parsed)
            else:
                evidence_type = evidence_type_parsed
        else:
            evidence_type = []

        claims.append(ClaimFull(
            id=row[0],
            claim_id=row[1],
            claim=row[2],
            claim_type=row[3],
            source=row[4],
            source_type=source_type,
            evidence=row[6],
            evidence_type=evidence_type,
            matched_segment=row[8],
            xpath_start=row[9],
            xpath_stop=row[10],
            char_offset_start=row[11],
            char_offset_stop=row[12]
        ))

    return claims


def get_results_llm_for_manuscript(
    conn: sqlite3.Connection,
    manuscript_id: str
) -> List[ResultLLM]:
    """Get all LLM results for a submission (manuscript) with linked claim IDs."""
    cursor = conn.cursor()

    # NEW: Query unified result table filtering by result_category='llm'
    cursor.execute("""
        SELECT r.id, r.result_id, r.result, r.reviewer_id, r.reviewer_name, r.result_status, r.result_reasoning, r.result_type
        FROM result r
        JOIN content ct ON r.content_id = ct.id
        WHERE ct.submission_id = ? AND r.result_category = 'llm'
        ORDER BY r.id
    """, (manuscript_id,))

    results = []
    for row in cursor.fetchall():
        result_uuid = row[0]
        result_id = row[1]

        # Get claim IDs for this result (NEW: unified claim_result table)
        cursor.execute("""
            SELECT c.claim_id
            FROM claim_result cr
            JOIN claim c ON cr.claim_id = c.id
            WHERE cr.result_id = ?
            ORDER BY c.claim_id
        """, (result_uuid,))

        claim_ids = [r[0] for r in cursor.fetchall()]

        results.append(ResultLLM(
            id=result_uuid,
            result_id=result_id,
            result_category='llm',
            claim_ids=claim_ids,
            result=row[2],
            reviewer_id=row[3],
            reviewer_name=row[4],
            result_status=row[5],
            result_reasoning=row[6],
            result_type=row[7]
        ))

    return results


def get_results_peer_for_manuscript(
    conn: sqlite3.Connection,
    manuscript_id: str
) -> List[ResultPeer]:
    """Get all peer results for a submission (manuscript) with linked claim IDs."""
    cursor = conn.cursor()

    # NEW: Query unified result table filtering by result_category='peer'
    cursor.execute("""
        SELECT r.id, r.result_id, r.result, r.reviewer_id, r.reviewer_name, r.result_status, r.result_reasoning, r.result_type
        FROM result r
        JOIN content ct ON r.content_id = ct.id
        WHERE ct.submission_id = ? AND r.result_category = 'peer'
        ORDER BY r.id
    """, (manuscript_id,))

    results = []
    for row in cursor.fetchall():
        result_uuid = row[0]
        result_id = row[1]

        # Get claim IDs for this result (NEW: unified claim_result table)
        cursor.execute("""
            SELECT c.claim_id
            FROM claim_result cr
            JOIN claim c ON cr.claim_id = c.id
            WHERE cr.result_id = ?
            ORDER BY c.claim_id
        """, (result_uuid,))

        claim_ids = [r[0] for r in cursor.fetchall()]

        results.append(ResultPeer(
            id=result_uuid,
            result_id=result_id,
            result_category='peer',
            claim_ids=claim_ids,
            result=row[2],
            reviewer_id=row[3],
            reviewer_name=row[4],
            result_status=row[5],
            result_reasoning=row[6],
            result_type=row[7]
        ))

    return results


def get_comparisons_for_manuscript(
    conn: sqlite3.Connection,
    manuscript_id: str
) -> List[ComparisonFull]:
    """Get all comparison data for a submission (manuscript)."""
    cursor = conn.cursor()

    # NEW: Join through unified result table to get comparisons for submission
    cursor.execute("""
        SELECT
            cmp.id,
            cmp.openeval_result_id,
            cmp.peer_result_id,
            cmp.openeval_status,
            cmp.peer_status,
            cmp.agreement_status,
            cmp.comparison,
            cmp.n_openeval,
            cmp.n_peer,
            cmp.n_itx,
            cmp.openeval_reasoning,
            cmp.peer_reasoning,
            cmp.openeval_result_type,
            cmp.peer_result_type
        FROM comparison cmp
        JOIN result r ON cmp.openeval_result_id = r.id
        JOIN content ct ON r.content_id = ct.id
        WHERE ct.submission_id = ?
        ORDER BY cmp.id
    """, (manuscript_id,))

    comparisons = []
    for row in cursor.fetchall():
        comparisons.append(ComparisonFull(
            id=row[0],
            openeval_result_id=row[1],
            peer_result_id=row[2],
            openeval_status=row[3],
            peer_status=row[4],
            agreement_status=row[5],
            comparison=row[6],
            n_openeval=row[7],
            n_peer=row[8],
            n_itx=row[9],
            openeval_reasoning=row[10],
            peer_reasoning=row[11],
            openeval_result_type=row[12],
            peer_result_type=row[13]
        ))

    return comparisons
