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
    source: str  # Changed from source_text
    source_type: List[str]  # JSON array: ["TEXT"], ["FIGURE"], etc.
    evidence: str  # Changed from evidence_reasoning
    evidence_type: List[str]  # JSON array: ["DATA", "CITATION", ...]
    # JATS position data for precise claim highlighting
    matched_segment: Optional[str] = None
    xpath_start: Optional[str] = None
    xpath_stop: Optional[str] = None
    char_offset_start: Optional[int] = None
    char_offset_stop: Optional[int] = None


class ResultFull(BaseModel):
    """Unified result model for both LLM and peer evaluations"""
    id: str  # UUID
    result_id: Optional[str] = None  # Simple ID like "R1", "R2"
    result_category: str  # 'llm' or 'peer'
    claim_ids: List[str]  # List of claim IDs this result evaluates
    result: str  # Description of the scientific finding (2-3 sentences)
    reviewer_id: Optional[str] = None
    reviewer_name: Optional[str] = None
    result_status: str  # SUPPORTED, UNSUPPORTED, UNCERTAIN
    result_reasoning: str


# Backwards compatibility aliases
ResultLLM = ResultFull
ResultPeer = ResultFull


class ComparisonFull(BaseModel):
    """Full comparison object between OpenEval and peer results"""
    id: str
    openeval_result_id: Optional[str] = None
    peer_result_id: Optional[str] = None
    openeval_status: Optional[str] = None
    peer_status: Optional[str] = None
    agreement_status: str  # agree, disagree, partial, disjoint
    comparison: Optional[str] = None
    n_openeval: Optional[int] = None
    n_peer: Optional[int] = None
    n_itx: Optional[int] = None
    openeval_reasoning: Optional[str] = None
    peer_reasoning: Optional[str] = None
    # NEW: Result type fields for displaying claim categories
    openeval_result_type: Optional[str] = None  # MAJOR, MINOR, DATA, METHOD, etc.
    peer_result_type: Optional[str] = None  # MAJOR, MINOR, DATA, METHOD, etc.


class ManuscriptMetadata(BaseModel):
    """Manuscript metadata (from submission table)"""
    id: str
    doi: Optional[str] = None  # manuscript_doi field
    title: Optional[str] = None  # manuscript_title field
    pub_date: Optional[str] = None  # manuscript_pub_date field
    abstract: Optional[str] = None  # manuscript_abstract field
    created_at: str
    has_jats: bool  # Whether JATS XML file is available


class ManuscriptSummary(BaseModel):
    """Manuscript summary for list view (from submission table)"""
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
    partial_count: Optional[int] = None
    disagree_count: Optional[int] = None
    disjoint_count: Optional[int] = None
    has_peer_reviews: bool


class ManuscriptSummaryStats(BaseModel):
    """Summary statistics for a manuscript"""
    total_claims: int
    total_results_llm: int
    total_results_peer: int
    has_peer_reviews: bool
    total_comparisons: int
    # LLM result status counts
    llm_supported_count: int
    llm_unsupported_count: int
    llm_uncertain_count: int
    # Peer result status counts (empty if no peer reviews)
    peer_supported_count: Optional[int] = None
    peer_unsupported_count: Optional[int] = None
    peer_uncertain_count: Optional[int] = None
    # Agreement counts (empty if no peer reviews)
    agree_count: Optional[int] = None
    partial_count: Optional[int] = None
    disagree_count: Optional[int] = None
    disjoint_count: Optional[int] = None


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
