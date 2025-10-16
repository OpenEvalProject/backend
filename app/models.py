from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


# Request models
class AnalyzeURLRequest(BaseModel):
    """Request model for analyzing a bioRxiv paper"""
    biorxiv_url: str


# Response models
class Claim(BaseModel):
    """Individual claim from a paper"""
    id: Optional[int] = None
    claim: str = Field(alias="claim_text")
    source_text: str
    status: str  # SUPPORTED, UNSUPPORTED, UNCERTAIN
    evidence: str
    evidence_basis: Optional[str] = None  # DATA, CITATION, KNOWLEDGE, INFERENCE, SPECULATION
    reference_claims: Optional[List[int]] = None  # List of claim IDs this claim references
    reference_rationale: Optional[str] = None  # Explanation of how this claim references others

    class Config:
        populate_by_name = True
        by_alias = False  # Use field names, not aliases, when serializing


class AnalysisSummary(BaseModel):
    """Summary of paper analysis"""
    total_claims: int
    supported: int = Field(alias="supported_count")
    unsupported: int = Field(alias="unsupported_count")
    uncertain: int = Field(alias="uncertain_count")
    verification_score: float
    processing_time_seconds: Optional[float] = None

    class Config:
        populate_by_name = True


class PaperSummary(BaseModel):
    """Paper summary for list view"""
    id: int
    title: str
    source_type: str
    source_reference: str
    verification_score: float
    total_claims: int
    supported_count: int
    unsupported_count: int
    uncertain_count: int
    processed_at: str
    submitted_by: Optional[str] = None


class PaperDetails(BaseModel):
    """Detailed paper information"""
    id: int
    title: str
    source_type: str
    source_reference: str
    document_length: int
    processed_at: str
    submitted_by: Optional[str] = None


class EvidenceBasisMetrics(BaseModel):
    """Metrics for a specific evidence basis type"""
    total: int
    supported: int
    unsupported: int
    uncertain: int
    score: float


class AnalysisDetails(BaseModel):
    """Complete analysis details"""
    summary: AnalysisSummary
    claims: List[Claim]
    evidence_basis_breakdown: Optional[dict] = None


class PaperResponse(BaseModel):
    """Response for individual paper view"""
    paper: PaperDetails
    analysis: AnalysisDetails


class PapersListResponse(BaseModel):
    """Response for papers list"""
    papers: List[PaperSummary]
    total_count: int


class AnalyzeResponse(BaseModel):
    """Response from analyze endpoint"""
    status: str
    paper_id: Optional[int] = None
    message: str
    redirect_url: Optional[str] = None
    instructions: Optional[str] = None
    paper_info: Optional[dict] = None


class ErrorResponse(BaseModel):
    """Error response"""
    status: str = "error"
    error: str


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


# LLM response models
class LLMClaim(BaseModel):
    """Claim as returned by LLM"""
    claim: str
    source_text: str
    status: str
    evidence: str
    evidence_basis: str  # DATA, CITATION, KNOWLEDGE, INFERENCE, SPECULATION
    reference_claims: Optional[List[int]] = None  # List of claim IDs this claim references
    reference_rationale: Optional[str] = None  # Explanation of how this claim references others


class LLMAnalysisResponse(BaseModel):
    """Expected response structure from LLM"""
    claims: List[LLMClaim]


# New models for updated workflow
class PaperClaim(BaseModel):
    """Extracted claim from paper (no evaluation)"""
    id: Optional[int] = None
    short_id: str  # e.g., "PC1", "PC2"
    claim_text: str
    source_text: str


class LLMEvaluation(BaseModel):
    """LLM's evaluation of a paper claim"""
    id: Optional[int] = None
    paper_claim_id: int
    status: str  # SUPPORTED, UNSUPPORTED, UNCERTAIN
    evidence: str
    assumptions: Optional[str] = None
    weaknesses: Optional[str] = None
    evidence_basis: Optional[str] = None  # DATA, CITATION, KNOWLEDGE, INFERENCE, SPECULATION


class ReviewClaim(BaseModel):
    """Claim extracted from peer review"""
    id: Optional[int] = None
    claim_text: str
    source_text: str
    reference_paper_claims: Optional[List[int]] = None  # IDs of paper claims this references
    reference_rationale: Optional[str] = None
    reference_relation: Optional[bool] = None  # True = supports referenced claims, False = refutes them


class ConcordanceRow(BaseModel):
    """Concordance analysis comparing LLM and peer review"""
    paper_claim_id: int
    paper_claim_short_id: str
    paper_claim_text: str
    llm_addressed: bool
    review_addressed: bool
    agreement_status: str  # "agree", "disagree", "partial", "N/A"
    notes: Optional[str] = None


class AnalysisDetailsV2(BaseModel):
    """Complete analysis details for new workflow"""
    summary: AnalysisSummary
    paper_claims: List[PaperClaim]
    llm_evaluations: List[LLMEvaluation]
    review_claims: Optional[List[ReviewClaim]] = None
    concordance_table: Optional[List[ConcordanceRow]] = None


class PaperResponseV2(BaseModel):
    """Response for individual paper view (new workflow)"""
    paper: PaperDetails
    analysis: AnalysisDetailsV2


# LLM response models for new workflow
class LLMPaperClaim(BaseModel):
    """Paper claim as returned by LLM during extraction"""
    short_id: str
    claim_text: str
    source_text: str


class LLMPaperClaimsResponse(BaseModel):
    """Expected response structure from paper claim extraction"""
    claims: List[LLMPaperClaim]


class LLMEvaluationResult(BaseModel):
    """Evaluation result for a single paper claim"""
    short_id: str  # Must match the paper claim short_id
    status: str
    evidence: str
    assumptions: Optional[str] = None
    weaknesses: Optional[str] = None
    evidence_basis: Optional[str] = None


class LLMEvaluationsResponse(BaseModel):
    """Expected response structure from paper claim evaluation"""
    evaluations: List[LLMEvaluationResult]


class LLMReviewClaim(BaseModel):
    """Review claim as returned by LLM"""
    claim_text: str
    source_text: str
    reference_paper_claims: Optional[List[str]] = None  # Short IDs like ["PC1", "PC3"]
    reference_rationale: Optional[str] = None
    reference_relation: Optional[bool] = None  # True = supports referenced claims, False = refutes them


class LLMReviewClaimsResponse(BaseModel):
    """Expected response structure from review claim extraction"""
    claims: List[LLMReviewClaim]


class LLMConcordanceRow(BaseModel):
    """Concordance row as returned by LLM"""
    paper_claim_short_id: str
    llm_addressed: bool
    review_addressed: bool
    agreement_status: str
    notes: Optional[str] = None


class LLMConcordanceResponse(BaseModel):
    """Expected response structure from concordance analysis"""
    concordance: List[LLMConcordanceRow]


# ============================================================================
# V3 WORKFLOW MODELS - New claim extraction and results grouping workflow
# ============================================================================

class ClaimV3(BaseModel):
    """Claim model for V3 workflow - atomic factual claims"""
    id: Optional[int] = None
    claim_id: str  # e.g., "C1", "C2"
    claim: str  # Atomic factual claim text
    claim_type: str  # EXPLICIT or IMPLICIT
    source_text: str  # Exact excerpt from manuscript
    evidence_type: List[str]  # List: DATA, CITATION, KNOWLEDGE, INFERENCE, SPECULATION
    evidence_reasoning: str  # Brief explanation of evidence type


class ResultV3(BaseModel):
    """Result model for V3 workflow - grouped claims with evaluation"""
    id: Optional[int] = None
    claim_ids: List[str]  # List of claim IDs like ["C1", "C2"]
    status: str  # SUPPORTED, UNSUPPORTED, UNCERTAIN
    status_reasoning: str  # Brief explanation of status


class ResultsConcordance(BaseModel):
    """Concordance between LLM and peer review results"""
    llm_result_id: Optional[int] = None
    peer_result_id: Optional[int] = None
    llm_claim_ids: List[str]
    peer_claim_ids: List[str]
    llm_status: str
    peer_status: str
    agreement_status: str  # "agree", "disagree", "partial"
    notes: Optional[str] = None


class AnalysisDetailsV3(BaseModel):
    """Complete analysis details for V3 workflow"""
    summary: AnalysisSummary
    claims: List[ClaimV3]
    llm_results: List[ResultV3]
    peer_results: List[ResultV3]
    results_concordance: Optional[List[ResultsConcordance]] = None


class PaperResponseV3(BaseModel):
    """Response for individual paper view (V3 workflow)"""
    paper: PaperDetails
    analysis: AnalysisDetailsV3


# LLM response models for V3 workflow
class LLMClaimV3(BaseModel):
    """Claim as returned by LLM during extraction (V3)"""
    claim_id: str
    claim: str
    claim_type: str
    source_text: str
    evidence_type: List[str]
    evidence_reasoning: str


class LLMClaimsResponseV3(BaseModel):
    """Expected response structure from claim extraction (V3)"""
    claims: List[LLMClaimV3]


class LLMResultV3(BaseModel):
    """Result as returned by LLM (V3)"""
    claim_ids: List[str]
    status: str
    status_reasoning: str


class LLMResultsResponseV3(BaseModel):
    """Expected response structure from results grouping (V3)"""
    results: List[LLMResultV3]


class LLMResultsConcordanceRow(BaseModel):
    """Concordance row as returned by LLM (V3)"""
    llm_claim_ids: List[str]
    peer_claim_ids: List[str]
    llm_status: str
    peer_status: str
    agreement_status: str
    notes: Optional[str] = None


class LLMResultsConcordanceResponse(BaseModel):
    """Expected response structure from results concordance (V3)"""
    concordance: List[LLMResultsConcordanceRow]
