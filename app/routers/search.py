"""
Search router for semantic claim search using embeddings and paper search.
"""

import pickle
import sqlite3
from typing import List, Optional
from enum import Enum

import numpy as np
from fastapi import APIRouter, HTTPException, Query, status
from openai import OpenAI
from pydantic import BaseModel, Field

from app.config import settings
from app.database import get_db

router = APIRouter(prefix="/api/claims", tags=["search"])
papers_router = APIRouter(prefix="/api/papers", tags=["papers"])


class ClaimSearchResult(BaseModel):
    """Single claim search result with similarity score"""

    claim_id: str  # UUID
    claim_display_id: Optional[str] = None  # Human-readable ID like "C1", "C2"
    manuscript_id: str
    claim: str
    claim_type: str
    source_text: str
    evidence_type: str
    evidence_reasoning: str
    similarity: float = Field(..., description="Cosine similarity score (0-1)")


class ClaimSearchResponse(BaseModel):
    """Response for claim search endpoint"""

    query: str
    results: List[ClaimSearchResult]
    total_results: int


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Calculate cosine similarity between two vectors.

    Args:
        a: First vector
        b: Second vector

    Returns:
        Cosine similarity score (0-1)
    """
    dot_product = np.dot(a, b)
    norm_a = np.linalg.norm(a)
    norm_b = np.linalg.norm(b)

    if norm_a == 0 or norm_b == 0:
        return 0.0

    return float(dot_product / (norm_a * norm_b))


def generate_query_embedding(query: str, model: str = "text-embedding-3-small") -> np.ndarray:
    """Generate embedding for search query.

    Args:
        query: Search query text
        model: OpenAI embedding model to use

    Returns:
        Query embedding as numpy array
    """
    # Check API key
    api_key = settings.openai_api_key
    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="OpenAI API key not configured"
        )

    try:
        client = OpenAI(api_key=api_key)
        response = client.embeddings.create(
            input=[query],
            model=model
        )
        return np.array(response.data[0].embedding, dtype=np.float32)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to generate query embedding: {str(e)}"
        )


def search_similar_claims(
    query_embedding: np.ndarray,
    limit: int = 10,
    model: str = "text-embedding-3-small"
) -> List[ClaimSearchResult]:
    """Search for claims similar to query embedding.

    Args:
        query_embedding: Query embedding vector
        limit: Maximum number of results to return
        model: Embedding model name to filter by

    Returns:
        List of similar claims with similarity scores
    """
    with get_db() as conn:
        cursor = conn.cursor()

        # Get all claims with embeddings from the specified model
        cursor.execute("""
            SELECT
                id,
                claim_id,
                manuscript_id,
                claim,
                claim_type,
                source_text,
                evidence_type,
                evidence_reasoning,
                embedding
            FROM claim
            WHERE embedding IS NOT NULL
            AND embedding_model = ?
        """, (model,))

        results = []

        for row in cursor.fetchall():
            uuid, claim_display_id, manuscript_id, claim, claim_type, source_text, evidence_type, evidence_reasoning, embedding_blob = row

            # Deserialize embedding
            try:
                claim_embedding = pickle.loads(embedding_blob)
            except Exception:
                # Skip claims with invalid embeddings
                continue

            # Calculate similarity
            similarity = cosine_similarity(query_embedding, claim_embedding)

            results.append(ClaimSearchResult(
                claim_id=uuid,
                claim_display_id=claim_display_id,
                manuscript_id=manuscript_id,
                claim=claim,
                claim_type=claim_type,
                source_text=source_text,
                evidence_type=evidence_type,
                evidence_reasoning=evidence_reasoning,
                similarity=similarity
            ))

    # Sort by similarity (descending) and return top k
    results.sort(key=lambda x: x.similarity, reverse=True)
    return results[:limit]


@router.get("/search", response_model=ClaimSearchResponse)
async def search_claims(
    q: str = Query(..., description="Search query text", min_length=1),
    limit: int = Query(10, description="Maximum number of results to return", ge=1, le=100),
    model: str = Query("text-embedding-3-small", description="Embedding model to use")
):
    """
    Search for claims semantically similar to the query.

    This endpoint:
    1. Generates an embedding for the search query
    2. Compares it with all claim embeddings in the database
    3. Returns the top-k most similar claims ranked by cosine similarity

    Args:
        q: Search query text
        limit: Maximum number of results (default: 10, max: 100)
        model: Embedding model name (default: text-embedding-3-small)

    Returns:
        Search results with similarity scores
    """
    # Generate query embedding
    query_embedding = generate_query_embedding(q, model)

    # Search for similar claims
    results = search_similar_claims(query_embedding, limit, model)

    return ClaimSearchResponse(
        query=q,
        results=results,
        total_results=len(results)
    )


# ============================================================================
# PAPER SEARCH ENDPOINTS
# ============================================================================

class SearchType(str, Enum):
    """Type of paper search to perform"""
    AUTHOR = "author"
    INSTITUTION = "institution"
    ORCID = "orcid"


class AuthorInfo(BaseModel):
    """Author information"""
    given_names: str
    surname: str
    orcid: Optional[str] = None
    corresponding: bool = False
    position: int


class PaperSearchResult(BaseModel):
    """Single paper search result"""
    submission_id: str
    title: str
    doi: Optional[str] = None
    pub_date: Optional[str] = None
    abstract: Optional[str] = None
    matching_authors: List[AuthorInfo]


class PaperSearchResponse(BaseModel):
    """Response for paper search endpoint"""
    query: str
    search_type: str
    results: List[PaperSearchResult]
    total_results: int


@papers_router.get("/search", response_model=PaperSearchResponse)
async def search_papers(
    q: str = Query(..., description="Search query (author name, institution, or ORCID ID)", min_length=1),
    search_type: SearchType = Query(SearchType.AUTHOR, description="Type of search to perform"),
    limit: int = Query(50, description="Maximum number of results to return", ge=1, le=200)
):
    """
    Search for papers by author name, institution, or ORCID ID.

    Search types:
    - author: Search by author surname or full name (case-insensitive, partial match)
    - institution: Search by institution name (case-insensitive, partial match)
    - orcid: Search by ORCID ID (exact match)

    Args:
        q: Search query text
        search_type: Type of search (author, institution, or orcid)
        limit: Maximum number of results (default: 50, max: 200)

    Returns:
        List of papers with matching authors
    """
    with get_db() as conn:
        cursor = conn.cursor()

        results = []

        if search_type == SearchType.AUTHOR:
            # Search by author name (surname or full name)
            # Split query into potential given_names and surname
            query_lower = q.lower()

            cursor.execute("""
                SELECT DISTINCT
                    s.id,
                    s.manuscript_title,
                    s.manuscript_doi,
                    s.manuscript_pub_date,
                    s.manuscript_abstract
                FROM submission s
                JOIN author a ON s.id = a.submission_id
                WHERE LOWER(a.surname) LIKE ?
                   OR LOWER(a.given_names || ' ' || a.surname) LIKE ?
                ORDER BY s.manuscript_pub_date DESC
                LIMIT ?
            """, (f"%{query_lower}%", f"%{query_lower}%", limit))

        elif search_type == SearchType.INSTITUTION:
            # Search by institution
            query_lower = q.lower()

            cursor.execute("""
                SELECT DISTINCT
                    s.id,
                    s.manuscript_title,
                    s.manuscript_doi,
                    s.manuscript_pub_date,
                    s.manuscript_abstract
                FROM submission s
                JOIN author a ON s.id = a.submission_id
                JOIN author_affiliation aa ON a.id = aa.author_id
                JOIN affiliation aff ON aa.affiliation_id = aff.id
                WHERE LOWER(aff.institution) LIKE ?
                   OR LOWER(aff.department) LIKE ?
                ORDER BY s.manuscript_pub_date DESC
                LIMIT ?
            """, (f"%{query_lower}%", f"%{query_lower}%", limit))

        elif search_type == SearchType.ORCID:
            # Search by ORCID (exact match)
            cursor.execute("""
                SELECT DISTINCT
                    s.id,
                    s.manuscript_title,
                    s.manuscript_doi,
                    s.manuscript_pub_date,
                    s.manuscript_abstract
                FROM submission s
                JOIN author a ON s.id = a.submission_id
                WHERE a.orcid = ?
                ORDER BY s.manuscript_pub_date DESC
                LIMIT ?
            """, (q, limit))

        # Fetch paper results
        papers = cursor.fetchall()

        # For each paper, get matching authors
        for paper in papers:
            submission_id, title, doi, pub_date, abstract = paper

            # Get authors that match the search criteria
            if search_type == SearchType.AUTHOR:
                cursor.execute("""
                    SELECT
                        given_names,
                        surname,
                        orcid,
                        corresponding,
                        position
                    FROM author
                    WHERE submission_id = ?
                      AND (LOWER(surname) LIKE ?
                           OR LOWER(given_names || ' ' || surname) LIKE ?)
                    ORDER BY position
                """, (submission_id, f"%{query_lower}%", f"%{query_lower}%"))

            elif search_type == SearchType.INSTITUTION:
                cursor.execute("""
                    SELECT DISTINCT
                        a.given_names,
                        a.surname,
                        a.orcid,
                        a.corresponding,
                        a.position
                    FROM author a
                    JOIN author_affiliation aa ON a.id = aa.author_id
                    JOIN affiliation aff ON aa.affiliation_id = aff.id
                    WHERE a.submission_id = ?
                      AND (LOWER(aff.institution) LIKE ?
                           OR LOWER(aff.department) LIKE ?)
                    ORDER BY a.position
                """, (submission_id, f"%{query_lower}%", f"%{query_lower}%"))

            elif search_type == SearchType.ORCID:
                cursor.execute("""
                    SELECT
                        given_names,
                        surname,
                        orcid,
                        corresponding,
                        position
                    FROM author
                    WHERE submission_id = ?
                      AND orcid = ?
                    ORDER BY position
                """, (submission_id, q))

            matching_authors = []
            for author_row in cursor.fetchall():
                given_names, surname, orcid, corresponding, position = author_row
                matching_authors.append(AuthorInfo(
                    given_names=given_names,
                    surname=surname,
                    orcid=orcid,
                    corresponding=bool(corresponding),
                    position=position
                ))

            results.append(PaperSearchResult(
                submission_id=submission_id,
                title=title,
                doi=doi,
                pub_date=pub_date,
                abstract=abstract,
                matching_authors=matching_authors
            ))

    return PaperSearchResponse(
        query=q,
        search_type=search_type.value,
        results=results,
        total_results=len(results)
    )


class AffiliationInfo(BaseModel):
    """Affiliation information"""
    institution: Optional[str] = None
    department: Optional[str] = None
    city: Optional[str] = None
    country: Optional[str] = None


class AuthorWithAffiliations(BaseModel):
    """Author with their affiliations"""
    given_names: str
    surname: str
    orcid: Optional[str] = None
    corresponding: bool = False
    position: int
    affiliations: List[AffiliationInfo]


class AuthorsResponse(BaseModel):
    """Response for manuscript authors endpoint"""
    submission_id: str
    authors: List[AuthorWithAffiliations]


@papers_router.get("/{submission_id}/authors", response_model=AuthorsResponse)
async def get_manuscript_authors(submission_id: str):
    """
    Get all authors and their affiliations for a specific manuscript.

    Args:
        submission_id: Manuscript submission ID

    Returns:
        List of authors with their affiliations
    """
    with get_db() as conn:
        cursor = conn.cursor()

        # Check if submission exists
        cursor.execute("SELECT id FROM submission WHERE id = ?", (submission_id,))
        if not cursor.fetchone():
            raise HTTPException(
                status_code=404,
                detail=f"Manuscript not found: {submission_id}"
            )

        # Get all authors for this submission
        cursor.execute("""
            SELECT
                id,
                given_names,
                surname,
                orcid,
                corresponding,
                position
            FROM author
            WHERE submission_id = ?
            ORDER BY position
        """, (submission_id,))

        authors_data = []

        for author_row in cursor.fetchall():
            author_id, given_names, surname, orcid, corresponding, position = author_row

            # Get affiliations for this author
            cursor.execute("""
                SELECT
                    aff.institution,
                    aff.department,
                    aff.city,
                    aff.country
                FROM affiliation aff
                JOIN author_affiliation aa ON aff.id = aa.affiliation_id
                WHERE aa.author_id = ?
                ORDER BY aff.affiliation_id
            """, (author_id,))

            affiliations = []
            for aff_row in cursor.fetchall():
                institution, department, city, country = aff_row
                affiliations.append(AffiliationInfo(
                    institution=institution,
                    department=department,
                    city=city,
                    country=country
                ))

            authors_data.append(AuthorWithAffiliations(
                given_names=given_names,
                surname=surname,
                orcid=orcid,
                corresponding=bool(corresponding),
                position=position,
                affiliations=affiliations
            ))

    return AuthorsResponse(
        submission_id=submission_id,
        authors=authors_data
    )
