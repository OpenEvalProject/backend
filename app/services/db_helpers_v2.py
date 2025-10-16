"""
Database helper functions for the new workflow (V2).

This module provides functions to save and retrieve data for the 4-stage workflow:
1. Paper claims
2. LLM evaluations
3. Review claims
4. Concordance analysis
"""

import json
import sqlite3
from typing import List, Optional

from app.models import (
    PaperClaim,
    LLMEvaluation,
    ReviewClaim,
    ConcordanceRow,
    PaperDetails,
    AnalysisSummary,
    AnalysisDetailsV2,
    PaperResponseV2,
)


# ============================================================================
# SAVE FUNCTIONS
# ============================================================================

def save_paper_claims(
    conn: sqlite3.Connection,
    paper_id: int,
    paper_claims: List[PaperClaim]
) -> List[int]:
    """
    Save paper claims to database.

    Args:
        conn: Database connection
        paper_id: ID of the paper
        paper_claims: List of paper claims to save

    Returns:
        List of database IDs for the saved claims
    """
    cursor = conn.cursor()
    claim_ids = []

    for claim in paper_claims:
        cursor.execute(
            """
            INSERT INTO paper_claims (paper_id, short_id, claim_text, source_text)
            VALUES (?, ?, ?, ?)
            """,
            (paper_id, claim.short_id, claim.claim_text, claim.source_text)
        )
        claim_ids.append(cursor.lastrowid)

    return claim_ids


def save_llm_evaluations(
    conn: sqlite3.Connection,
    paper_claims: List[PaperClaim],
    llm_evaluations: List[LLMEvaluation]
) -> List[int]:
    """
    Save LLM evaluations to database.

    Args:
        conn: Database connection
        paper_claims: List of paper claims (with database IDs)
        llm_evaluations: List of LLM evaluations to save

    Returns:
        List of database IDs for the saved evaluations
    """
    cursor = conn.cursor()
    evaluation_ids = []

    for evaluation in llm_evaluations:
        cursor.execute(
            """
            INSERT INTO llm_evaluations
            (paper_claim_id, status, evidence, assumptions, weaknesses, evidence_basis)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                evaluation.paper_claim_id,
                evaluation.status,
                evaluation.evidence,
                evaluation.assumptions,
                evaluation.weaknesses,
                evaluation.evidence_basis
            )
        )
        evaluation_ids.append(cursor.lastrowid)

    return evaluation_ids


def save_review_claims(
    conn: sqlite3.Connection,
    paper_id: int,
    review_claims: List[ReviewClaim]
) -> List[int]:
    """
    Save review claims to database.

    Args:
        conn: Database connection
        paper_id: ID of the paper
        review_claims: List of review claims to save

    Returns:
        List of database IDs for the saved review claims
    """
    cursor = conn.cursor()
    claim_ids = []

    for claim in review_claims:
        # Convert reference_paper_claims list to JSON string
        reference_json = None
        if claim.reference_paper_claims:
            reference_json = json.dumps(claim.reference_paper_claims)

        cursor.execute(
            """
            INSERT INTO review_claims
            (paper_id, claim_text, source_text, reference_paper_claims, reference_rationale, reference_relation)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                paper_id,
                claim.claim_text,
                claim.source_text,
                reference_json,
                claim.reference_rationale,
                claim.reference_relation
            )
        )
        claim_ids.append(cursor.lastrowid)

    return claim_ids


def save_concordance_analysis(
    conn: sqlite3.Connection,
    paper_id: int,
    concordance_table: List[ConcordanceRow]
) -> List[int]:
    """
    Save concordance analysis to database.

    Args:
        conn: Database connection
        paper_id: ID of the paper
        concordance_table: List of concordance rows to save

    Returns:
        List of database IDs for the saved concordance rows
    """
    cursor = conn.cursor()
    row_ids = []

    for row in concordance_table:
        cursor.execute(
            """
            INSERT INTO concordance_analysis
            (paper_id, paper_claim_id, llm_addressed, review_addressed, agreement_status, notes)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                paper_id,
                row.paper_claim_id,
                row.llm_addressed,
                row.review_addressed,
                row.agreement_status,
                row.notes
            )
        )
        row_ids.append(cursor.lastrowid)

    return row_ids


# ============================================================================
# RETRIEVE FUNCTIONS
# ============================================================================

def get_paper_claims(
    conn: sqlite3.Connection,
    paper_id: int
) -> List[PaperClaim]:
    """
    Retrieve paper claims from database.

    Args:
        conn: Database connection
        paper_id: ID of the paper

    Returns:
        List of paper claims
    """
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT id, short_id, claim_text, source_text
        FROM paper_claims
        WHERE paper_id = ?
        ORDER BY id
        """,
        (paper_id,)
    )

    claims = []
    for row in cursor.fetchall():
        claims.append(PaperClaim(
            id=row["id"],
            short_id=row["short_id"],
            claim_text=row["claim_text"],
            source_text=row["source_text"]
        ))

    return claims


def get_llm_evaluations(
    conn: sqlite3.Connection,
    paper_id: int
) -> List[LLMEvaluation]:
    """
    Retrieve LLM evaluations from database.

    Args:
        conn: Database connection
        paper_id: ID of the paper

    Returns:
        List of LLM evaluations
    """
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT
            e.id,
            e.paper_claim_id,
            e.status,
            e.evidence,
            e.assumptions,
            e.weaknesses,
            e.evidence_basis
        FROM llm_evaluations e
        JOIN paper_claims pc ON e.paper_claim_id = pc.id
        WHERE pc.paper_id = ?
        ORDER BY e.id
        """,
        (paper_id,)
    )

    evaluations = []
    for row in cursor.fetchall():
        evaluations.append(LLMEvaluation(
            id=row["id"],
            paper_claim_id=row["paper_claim_id"],
            status=row["status"],
            evidence=row["evidence"],
            assumptions=row["assumptions"],
            weaknesses=row["weaknesses"],
            evidence_basis=row["evidence_basis"]
        ))

    return evaluations


def get_review_claims(
    conn: sqlite3.Connection,
    paper_id: int
) -> List[ReviewClaim]:
    """
    Retrieve review claims from database.

    Args:
        conn: Database connection
        paper_id: ID of the paper

    Returns:
        List of review claims
    """
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT
            id,
            claim_text,
            source_text,
            reference_paper_claims,
            reference_rationale,
            reference_relation
        FROM review_claims
        WHERE paper_id = ?
        ORDER BY id
        """,
        (paper_id,)
    )

    claims = []
    for row in cursor.fetchall():
        # Parse reference_paper_claims from JSON
        reference_claims = None
        if row["reference_paper_claims"]:
            try:
                reference_claims = json.loads(row["reference_paper_claims"])
            except json.JSONDecodeError:
                reference_claims = None

        claims.append(ReviewClaim(
            id=row["id"],
            claim_text=row["claim_text"],
            source_text=row["source_text"],
            reference_paper_claims=reference_claims,
            reference_rationale=row["reference_rationale"],
            reference_relation=bool(row["reference_relation"]) if row["reference_relation"] is not None else None
        ))

    return claims


def get_concordance_analysis(
    conn: sqlite3.Connection,
    paper_id: int
) -> List[ConcordanceRow]:
    """
    Retrieve concordance analysis from database.

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
            c.paper_claim_id,
            pc.short_id as paper_claim_short_id,
            pc.claim_text as paper_claim_text,
            c.llm_addressed,
            c.review_addressed,
            c.agreement_status,
            c.notes
        FROM concordance_analysis c
        JOIN paper_claims pc ON c.paper_claim_id = pc.id
        WHERE c.paper_id = ?
        ORDER BY c.id
        """,
        (paper_id,)
    )

    rows = []
    for row in cursor.fetchall():
        rows.append(ConcordanceRow(
            paper_claim_id=row["paper_claim_id"],
            paper_claim_short_id=row["paper_claim_short_id"],
            paper_claim_text=row["paper_claim_text"],
            llm_addressed=bool(row["llm_addressed"]),
            review_addressed=bool(row["review_addressed"]),
            agreement_status=row["agreement_status"],
            notes=row["notes"]
        ))

    return rows


def get_paper_with_v2_analysis(
    conn: sqlite3.Connection,
    paper_id: int
) -> Optional[PaperResponseV2]:
    """
    Retrieve complete paper with V2 analysis.

    Args:
        conn: Database connection
        paper_id: ID of the paper

    Returns:
        PaperResponseV2 with all analysis data, or None if paper not found
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
        (paper_id,)
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
        (paper_id,)
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
        submitted_by=paper_row["submitted_by"]
    )

    summary = AnalysisSummary(
        total_claims=summary_row["total_claims"],
        supported=summary_row["supported_count"],
        unsupported=summary_row["unsupported_count"],
        uncertain=summary_row["uncertain_count"],
        verification_score=summary_row["verification_score"],
        processing_time_seconds=summary_row["processing_time_seconds"]
    )

    # Get all V2 analysis data
    paper_claims = get_paper_claims(conn, paper_id)
    llm_evaluations = get_llm_evaluations(conn, paper_id)
    review_claims = get_review_claims(conn, paper_id)
    concordance_table = get_concordance_analysis(conn, paper_id)

    analysis = AnalysisDetailsV2(
        summary=summary,
        paper_claims=paper_claims,
        llm_evaluations=llm_evaluations,
        review_claims=review_claims if review_claims else None,
        concordance_table=concordance_table if concordance_table else None
    )

    return PaperResponseV2(paper=paper_details, analysis=analysis)
