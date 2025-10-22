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
    Get list of all manuscripts with summary information.

    Args:
        conn: Database connection
        limit: Optional limit on number of results
        offset: Offset for pagination

    Returns:
        Tuple of (list of ManuscriptSummary, total_count)
    """
    cursor = conn.cursor()

    # Count total manuscripts
    cursor.execute("SELECT COUNT(*) FROM manuscript")
    total_count = cursor.fetchone()[0]

    # Build query using scalar subqueries for better performance
    # This avoids cartesian products from multiple JOINs
    query = """
        SELECT
            m.id,
            m.title,
            m.pub_date,
            m.created_at,
            (SELECT COUNT(*) FROM claim WHERE manuscript_id = m.id) as total_claims,
            (SELECT COUNT(*) FROM result_llm WHERE manuscript_id = m.id) as total_results_llm,
            (SELECT COUNT(rp.id) FROM result_peer rp
             JOIN peer p ON rp.peer_id = p.id
             WHERE p.manuscript_id = m.id) as total_results_peer,
            (SELECT COUNT(*) > 0 FROM peer WHERE manuscript_id = m.id) as has_peer_reviews,
            (SELECT COUNT(cmp.id) FROM comparison cmp
             JOIN result_llm rl ON cmp.openeval_result_id = rl.id
             WHERE rl.manuscript_id = m.id) as total_comparisons,
            (SELECT COUNT(cmp.id) FROM comparison cmp
             JOIN result_llm rl ON cmp.openeval_result_id = rl.id
             WHERE rl.manuscript_id = m.id AND cmp.agreement_status = 'agree') as agree_count,
            (SELECT COUNT(cmp.id) FROM comparison cmp
             JOIN result_llm rl ON cmp.openeval_result_id = rl.id
             WHERE rl.manuscript_id = m.id AND cmp.agreement_status = 'partial') as partial_count,
            (SELECT COUNT(cmp.id) FROM comparison cmp
             JOIN result_llm rl ON cmp.openeval_result_id = rl.id
             WHERE rl.manuscript_id = m.id AND cmp.agreement_status = 'disagree') as disagree_count,
            (SELECT COUNT(cmp.id) FROM comparison cmp
             JOIN result_llm rl ON cmp.openeval_result_id = rl.id
             WHERE rl.manuscript_id = m.id AND cmp.agreement_status = 'disjoint') as disjoint_count
        FROM manuscript m
        ORDER BY m.created_at DESC
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
    Get complete details for a single manuscript.

    Args:
        conn: Database connection
        manuscript_id: Manuscript ID

    Returns:
        ManuscriptDetail or None if not found
    """
    cursor = conn.cursor()

    # Get manuscript metadata
    cursor.execute("""
        SELECT id, doi, title, abstract, pub_date, created_at
        FROM manuscript
        WHERE id = ?
    """, (manuscript_id,))

    row = cursor.fetchone()
    if not row:
        return None

    metadata = ManuscriptMetadata(
        id=row[0],
        doi=row[1],
        title=row[2],
        abstract=row[3],
        pub_date=row[4],
        created_at=row[5]
    )

    # Get summary stats with agreement counts
    cursor.execute("""
        SELECT COUNT(DISTINCT c.id) as total_claims,
               COUNT(DISTINCT rl.id) as total_results_llm,
               COUNT(DISTINCT rp.id) as total_results_peer,
               COUNT(DISTINCT p.id) > 0 as has_peer_reviews,
               (SELECT COUNT(*) FROM comparison cmp
                JOIN result_llm rl2 ON cmp.openeval_result_id = rl2.id
                WHERE rl2.manuscript_id = m.id) as total_comparisons,
               (SELECT COUNT(*) FROM comparison cmp
                JOIN result_llm rl2 ON cmp.openeval_result_id = rl2.id
                WHERE rl2.manuscript_id = m.id AND cmp.agreement_status = 'agree') as agree_count,
               (SELECT COUNT(*) FROM comparison cmp
                JOIN result_llm rl2 ON cmp.openeval_result_id = rl2.id
                WHERE rl2.manuscript_id = m.id AND cmp.agreement_status = 'partial') as partial_count,
               (SELECT COUNT(*) FROM comparison cmp
                JOIN result_llm rl2 ON cmp.openeval_result_id = rl2.id
                WHERE rl2.manuscript_id = m.id AND cmp.agreement_status = 'disagree') as disagree_count,
               (SELECT COUNT(*) FROM comparison cmp
                JOIN result_llm rl2 ON cmp.openeval_result_id = rl2.id
                WHERE rl2.manuscript_id = m.id AND cmp.agreement_status = 'disjoint') as disjoint_count
        FROM manuscript m
        LEFT JOIN claim c ON m.id = c.manuscript_id
        LEFT JOIN result_llm rl ON m.id = rl.manuscript_id
        LEFT JOIN peer p ON m.id = p.manuscript_id
        LEFT JOIN result_peer rp ON p.id = rp.peer_id
        WHERE m.id = ?
    """, (manuscript_id,))

    row = cursor.fetchone()
    has_peer_reviews = bool(row[3])
    summary_stats = ManuscriptSummaryStats(
        total_claims=row[0],
        total_results_llm=row[1],
        total_results_peer=row[2],
        has_peer_reviews=has_peer_reviews,
        total_comparisons=row[4],
        agree_count=row[5] if has_peer_reviews else None,
        partial_count=row[6] if has_peer_reviews else None,
        disagree_count=row[7] if has_peer_reviews else None,
        disjoint_count=row[8] if has_peer_reviews else None
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
    """Get all claims for a manuscript."""
    cursor = conn.cursor()

    cursor.execute("""
        SELECT id, claim_id, claim, claim_type, source_text, evidence_type, evidence_reasoning
        FROM claim
        WHERE manuscript_id = ?
        ORDER BY id
    """, (manuscript_id,))

    claims = []
    for row in cursor.fetchall():
        # evidence_type is double-JSON encoded, so we need to parse it twice
        evidence_type_raw = row[5]
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
            source_text=row[4],
            evidence_type=evidence_type,
            evidence_reasoning=row[6]
        ))

    return claims


def get_results_llm_for_manuscript(
    conn: sqlite3.Connection,
    manuscript_id: str
) -> List[ResultLLM]:
    """Get all LLM results for a manuscript with linked claim IDs."""
    cursor = conn.cursor()

    cursor.execute("""
        SELECT id, result, reviewer_id, reviewer_name, result_status, result_reasoning
        FROM result_llm
        WHERE manuscript_id = ?
        ORDER BY id
    """, (manuscript_id,))

    results = []
    for row in cursor.fetchall():
        result_id = row[0]

        # Get claim IDs for this result
        cursor.execute("""
            SELECT claim_id
            FROM claim_result_llm
            WHERE result_llm_id = ?
            ORDER BY claim_id
        """, (result_id,))

        claim_ids = [r[0] for r in cursor.fetchall()]

        results.append(ResultLLM(
            id=result_id,
            claim_ids=claim_ids,
            result=row[1],
            reviewer_id=row[2],
            reviewer_name=row[3],
            result_status=row[4],
            result_reasoning=row[5]
        ))

    return results


def get_results_peer_for_manuscript(
    conn: sqlite3.Connection,
    manuscript_id: str
) -> List[ResultPeer]:
    """Get all peer results for a manuscript with linked claim IDs."""
    cursor = conn.cursor()

    # First get peer_id for this manuscript
    cursor.execute("""
        SELECT id FROM peer WHERE manuscript_id = ?
    """, (manuscript_id,))

    peer_row = cursor.fetchone()
    if not peer_row:
        return []

    peer_id = peer_row[0]

    cursor.execute("""
        SELECT id, result, reviewer_id, reviewer_name, result_status, result_reasoning
        FROM result_peer
        WHERE peer_id = ?
        ORDER BY id
    """, (peer_id,))

    results = []
    for row in cursor.fetchall():
        result_id = row[0]

        # Get claim IDs for this result
        cursor.execute("""
            SELECT claim_id
            FROM claim_result_peer
            WHERE result_peer_id = ?
            ORDER BY claim_id
        """, (result_id,))

        claim_ids = [r[0] for r in cursor.fetchall()]

        results.append(ResultPeer(
            id=result_id,
            claim_ids=claim_ids,
            result=row[1],
            reviewer_id=row[2],
            reviewer_name=row[3],
            result_status=row[4],
            result_reasoning=row[5]
        ))

    return results


def get_comparisons_for_manuscript(
    conn: sqlite3.Connection,
    manuscript_id: str
) -> List[ComparisonFull]:
    """Get all comparison data for a manuscript."""
    cursor = conn.cursor()

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
            rl.result_reasoning as openeval_reasoning,
            rp.result_reasoning as peer_reasoning
        FROM comparison cmp
        LEFT JOIN result_llm rl ON cmp.openeval_result_id = rl.id
        LEFT JOIN result_peer rp ON cmp.peer_result_id = rp.id
        WHERE cmp.openeval_result_id IN (
            SELECT id FROM result_llm WHERE manuscript_id = ?
        )
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
            peer_reasoning=row[11]
        ))

    return comparisons
