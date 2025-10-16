"""
Database helper functions for the V3 workflow.

This module provides functions to save and retrieve data for the V3 results-based workflow:
1. Claims (atomic factual claims)
2. Results (grouped claims with evaluation) - both LLM and peer review
3. Results concordance (comparison between LLM and peer results)
"""

import json
import sqlite3
from typing import List, Optional

from app.models import (
    ClaimV3,
    ResultV3,
    ResultsConcordance,
    PaperDetails,
    AnalysisSummary,
    AnalysisDetailsV3,
    PaperResponseV3,
)


# ============================================================================
# SAVE FUNCTIONS
# ============================================================================


def save_claims_v3(
    conn: sqlite3.Connection, paper_id: int, claims: List[ClaimV3]
) -> List[int]:
    """
    Save V3 claims to database.

    Args:
        conn: Database connection
        paper_id: ID of the paper
        claims: List of claims to save

    Returns:
        List of database IDs for the saved claims
    """
    cursor = conn.cursor()
    claim_ids = []

    for claim in claims:
        # Convert evidence_type list to JSON string
        evidence_type_json = json.dumps(claim.evidence_type)

        cursor.execute(
            """
            INSERT INTO claims_v3 (paper_id, claim_id, claim, claim_type, source_text, evidence_type, evidence_reasoning)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                paper_id,
                claim.claim_id,
                claim.claim,
                claim.claim_type,
                claim.source_text,
                evidence_type_json,
                claim.evidence_reasoning,
            ),
        )
        claim_ids.append(cursor.lastrowid)

    return claim_ids


def save_results_v3(
    conn: sqlite3.Connection,
    paper_id: int,
    results: List[ResultV3],
    source: str,  # "LLM" or "PEER_REVIEW"
) -> List[int]:
    """
    Save V3 results to database.

    Args:
        conn: Database connection
        paper_id: ID of the paper
        results: List of results to save
        source: Source of results ("LLM" or "PEER_REVIEW")

    Returns:
        List of database IDs for the saved results
    """
    cursor = conn.cursor()
    result_ids = []

    for result in results:
        # Convert claim_ids list to JSON string
        claim_ids_json = json.dumps(result.claim_ids)

        cursor.execute(
            """
            INSERT INTO results_v3 (paper_id, source, claim_ids, status, status_reasoning)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                paper_id,
                source,
                claim_ids_json,
                result.status,
                result.status_reasoning,
            ),
        )
        result_ids.append(cursor.lastrowid)

    return result_ids


def save_results_concordance(
    conn: sqlite3.Connection,
    paper_id: int,
    concordance_rows: List[ResultsConcordance],
) -> List[int]:
    """
    Save results concordance to database.

    Args:
        conn: Database connection
        paper_id: ID of the paper
        concordance_rows: List of concordance rows to save

    Returns:
        List of database IDs for the saved concordance rows
    """
    cursor = conn.cursor()
    row_ids = []

    for row in concordance_rows:
        # Convert claim_ids lists to JSON strings
        llm_claim_ids_json = json.dumps(row.llm_claim_ids)
        peer_claim_ids_json = json.dumps(row.peer_claim_ids)

        cursor.execute(
            """
            INSERT INTO results_concordance
            (paper_id, llm_result_id, peer_result_id, llm_claim_ids, peer_claim_ids, llm_status, peer_status, agreement_status, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                paper_id,
                row.llm_result_id,
                row.peer_result_id,
                llm_claim_ids_json,
                peer_claim_ids_json,
                row.llm_status,
                row.peer_status,
                row.agreement_status,
                row.notes,
            ),
        )
        row_ids.append(cursor.lastrowid)

    return row_ids


# ============================================================================
# RETRIEVE FUNCTIONS
# ============================================================================


def get_claims_v3(conn: sqlite3.Connection, paper_id: int) -> List[ClaimV3]:
    """
    Retrieve V3 claims from database.

    Args:
        conn: Database connection
        paper_id: ID of the paper

    Returns:
        List of claims
    """
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT id, claim_id, claim, claim_type, source_text, evidence_type, evidence_reasoning
        FROM claims_v3
        WHERE paper_id = ?
        ORDER BY id
        """,
        (paper_id,),
    )

    claims = []
    for row in cursor.fetchall():
        # Parse evidence_type from JSON
        evidence_type = []
        if row["evidence_type"]:
            try:
                evidence_type = json.loads(row["evidence_type"])
            except json.JSONDecodeError:
                evidence_type = []

        claims.append(
            ClaimV3(
                id=row["id"],
                claim_id=row["claim_id"],
                claim=row["claim"],
                claim_type=row["claim_type"],
                source_text=row["source_text"],
                evidence_type=evidence_type,
                evidence_reasoning=row["evidence_reasoning"],
            )
        )

    return claims


def get_results_v3(
    conn: sqlite3.Connection, paper_id: int, source: Optional[str] = None
) -> List[ResultV3]:
    """
    Retrieve V3 results from database.

    Args:
        conn: Database connection
        paper_id: ID of the paper
        source: Optional filter by source ("LLM" or "PEER_REVIEW")

    Returns:
        List of results
    """
    cursor = conn.cursor()

    if source:
        cursor.execute(
            """
            SELECT id, claim_ids, status, status_reasoning
            FROM results_v3
            WHERE paper_id = ? AND source = ?
            ORDER BY id
            """,
            (paper_id, source),
        )
    else:
        cursor.execute(
            """
            SELECT id, claim_ids, status, status_reasoning
            FROM results_v3
            WHERE paper_id = ?
            ORDER BY id
            """,
            (paper_id,),
        )

    results = []
    for row in cursor.fetchall():
        # Parse claim_ids from JSON
        claim_ids = []
        if row["claim_ids"]:
            try:
                claim_ids = json.loads(row["claim_ids"])
            except json.JSONDecodeError:
                claim_ids = []

        results.append(
            ResultV3(
                id=row["id"],
                claim_ids=claim_ids,
                status=row["status"],
                status_reasoning=row["status_reasoning"],
            )
        )

    return results


def get_results_concordance(
    conn: sqlite3.Connection, paper_id: int
) -> List[ResultsConcordance]:
    """
    Retrieve results concordance from database.

    Args:
        conn: Database connection
        paper_id: ID of the paper

    Returns:
        List of concordance rows
    """
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT
            llm_result_id,
            peer_result_id,
            llm_claim_ids,
            peer_claim_ids,
            llm_status,
            peer_status,
            agreement_status,
            notes
        FROM results_concordance
        WHERE paper_id = ?
        ORDER BY id
        """,
        (paper_id,),
    )

    rows = []
    for row in cursor.fetchall():
        # Parse claim_ids from JSON
        llm_claim_ids = []
        peer_claim_ids = []

        if row["llm_claim_ids"]:
            try:
                llm_claim_ids = json.loads(row["llm_claim_ids"])
            except json.JSONDecodeError:
                llm_claim_ids = []

        if row["peer_claim_ids"]:
            try:
                peer_claim_ids = json.loads(row["peer_claim_ids"])
            except json.JSONDecodeError:
                peer_claim_ids = []

        rows.append(
            ResultsConcordance(
                llm_result_id=row["llm_result_id"],
                peer_result_id=row["peer_result_id"],
                llm_claim_ids=llm_claim_ids,
                peer_claim_ids=peer_claim_ids,
                llm_status=row["llm_status"],
                peer_status=row["peer_status"],
                agreement_status=row["agreement_status"],
                notes=row["notes"],
            )
        )

    return rows


def get_paper_with_v3_analysis(
    conn: sqlite3.Connection, paper_id: int
) -> Optional[PaperResponseV3]:
    """
    Retrieve complete paper with V3 analysis.

    Args:
        conn: Database connection
        paper_id: ID of the paper

    Returns:
        PaperResponseV3 with all analysis data, or None if paper not found
    """
    cursor = conn.cursor()

    # Get paper details
    cursor.execute(
        """
        SELECT
            p.id,
            p.title,
            p.source_type,
            p.source_reference,
            p.document_length,
            p.processed_at,
            u.name as submitted_by
        FROM papers p
        JOIN users u ON p.user_id = u.id
        WHERE p.id = ?
        """,
        (paper_id,),
    )
    paper_row = cursor.fetchone()

    if not paper_row:
        return None

    # Get analysis summary
    cursor.execute(
        """
        SELECT
            total_claims,
            supported_count,
            unsupported_count,
            uncertain_count,
            verification_score,
            processing_time_seconds
        FROM analysis_summary
        WHERE paper_id = ?
        """,
        (paper_id,),
    )
    summary_row = cursor.fetchone()

    # Build response
    paper_details = PaperDetails(
        id=paper_row["id"],
        title=paper_row["title"],
        source_type=paper_row["source_type"],
        source_reference=paper_row["source_reference"],
        document_length=paper_row["document_length"],
        processed_at=paper_row["processed_at"],
        submitted_by=paper_row["submitted_by"],
    )

    summary = AnalysisSummary(
        total_claims=summary_row["total_claims"],
        supported=summary_row["supported_count"],
        unsupported=summary_row["unsupported_count"],
        uncertain=summary_row["uncertain_count"],
        verification_score=summary_row["verification_score"],
        processing_time_seconds=summary_row["processing_time_seconds"],
    )

    # Get all V3 analysis data
    claims = get_claims_v3(conn, paper_id)
    llm_results = get_results_v3(conn, paper_id, source="LLM")
    peer_results = get_results_v3(conn, paper_id, source="PEER_REVIEW")
    concordance = get_results_concordance(conn, paper_id)

    analysis = AnalysisDetailsV3(
        summary=summary,
        claims=claims,
        llm_results=llm_results,
        peer_results=peer_results,
        results_concordance=concordance if concordance else None,
    )

    return PaperResponseV3(paper=paper_details, analysis=analysis)
