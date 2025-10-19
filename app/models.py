"""
Pydantic models for the claim verification API.

These models define the structure of API requests and responses.
"""

from typing import List, Optional

from pydantic import BaseModel


# ============================================================================
# AUTH MODELS (preserved from original)
# ============================================================================

class UserInfo(BaseModel):
    """User information"""
    orcid_id: str
    name: Optional[str] = None
    email: Optional[str] = None


class AuthResponse(BaseModel):
    """Authentication status response"""
    authenticated: bool
    user: Optional[UserInfo] = None


class HealthResponse(BaseModel):
    """Health check response"""
    status: str
    version: str
    database: str


class ErrorResponse(BaseModel):
    """Error response"""
    status: str = "error"
    error: str


# ============================================================================
# MANUSCRIPT MODELS (new schema)
# ============================================================================

class ClaimFull(BaseModel):
    """Full claim object with all fields"""
    id: str  # UUID
    claim_id: Optional[str] = None  # Simple ID like "C1", "C2"
    claim: str
    claim_type: str  # EXPLICIT or IMPLICIT
    source_text: str
    evidence_type: List[str]  # JSON array: ["DATA", "CITATION", ...]
    evidence_reasoning: str


class ResultLLM(BaseModel):
    """LLM evaluation result"""
    id: str  # e.g., "R1", "R2"
    claim_ids: List[str]  # List of claim IDs this result evaluates
    reviewer_id: Optional[str] = None
    reviewer_name: Optional[str] = None
    result_status: str  # SUPPORTED, UNSUPPORTED, UNCERTAIN
    result_reasoning: str


class ResultPeer(BaseModel):
    """Peer evaluation result"""
    id: str  # e.g., "R1", "R2"
    claim_ids: List[str]  # List of claim IDs this result evaluates
    reviewer_id: Optional[str] = None
    reviewer_name: Optional[str] = None
    result_status: str  # SUPPORTED, UNSUPPORTED, UNCERTAIN
    result_reasoning: str


class ComparisonFull(BaseModel):
    """Full comparison object between LLM and peer results"""
    id: str
    llm_result_id: Optional[str] = None
    peer_result_id: Optional[str] = None
    llm_status: Optional[str] = None
    peer_status: Optional[str] = None
    agreement_status: str  # agree, disagree, disjoint
    notes: Optional[str] = None
    n_llm: Optional[int] = None
    n_peer: Optional[int] = None
    n_itx: Optional[int] = None
    llm_reasoning: Optional[str] = None
    peer_reasoning: Optional[str] = None


class ManuscriptMetadata(BaseModel):
    """Manuscript metadata"""
    id: str
    doi: Optional[str] = None
    title: Optional[str] = None
    abstract: Optional[str] = None
    pub_date: Optional[str] = None
    created_at: str


class ManuscriptSummary(BaseModel):
    """Manuscript summary for list view"""
    id: str
    title: Optional[str] = None
    pub_date: Optional[str] = None
    created_at: str
    total_claims: int
    total_results_llm: int
    total_results_peer: int
    total_comparisons: int
    # Agreement counts (empty if no peer reviews)
    agree_count: Optional[int] = None
    disjoint_count: Optional[int] = None
    disagree_count: Optional[int] = None
    has_peer_reviews: bool


class ManuscriptSummaryStats(BaseModel):
    """Summary statistics for a manuscript"""
    total_claims: int
    total_results_llm: int
    total_results_peer: int
    has_peer_reviews: bool


class ManuscriptDetail(BaseModel):
    """Complete manuscript detail for detail view"""
    metadata: ManuscriptMetadata
    summary_stats: ManuscriptSummaryStats
    claims: List[ClaimFull]
    results_llm: List[ResultLLM]
    results_peer: List[ResultPeer]
    comparisons: List[ComparisonFull]


class ManuscriptListResponse(BaseModel):
    """Response for manuscripts list endpoint"""
    manuscripts: List[ManuscriptSummary]
    total_count: int


class AggregateStatistics(BaseModel):
    """Aggregate statistics across all manuscripts"""
    total_manuscripts: int
    total_claims: int
    total_llm_results: int
    total_peer_results: int
    total_comparisons: int
    manuscripts_with_peer_reviews: int
