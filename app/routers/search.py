"""
Search router for semantic claim search using embeddings.
"""

import pickle
import sqlite3
from typing import List, Optional

import numpy as np
from fastapi import APIRouter, HTTPException, Query, status
from openai import OpenAI
from pydantic import BaseModel, Field

from app.config import settings
from app.database import get_db

router = APIRouter(prefix="/api/claims", tags=["search"])


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
