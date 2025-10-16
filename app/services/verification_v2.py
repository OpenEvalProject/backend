"""
New workflow verification service for claim extraction and evaluation.

This module implements the updated 2-4 stage workflow:
1. Extract paper claims (descriptive only)
2. Evaluate paper claims (LLM judgment)
3. Extract review claims (with references to paper claims)
4. Analyze concordance (compare LLM and peer review)
"""

import json
import time
from typing import List, Tuple

from anthropic import Anthropic, APIError

from app.config import settings
from app.models import (
    LLMPaperClaimsResponse,
    LLMPaperClaim,
    LLMEvaluationsResponse,
    LLMEvaluationResult,
    LLMReviewClaimsResponse,
    LLMReviewClaim,
    LLMConcordanceResponse,
    LLMConcordanceRow,
    PaperClaim,
)


# ============================================================================
# STAGE 1: PAPER CLAIM EXTRACTION PROMPT
# ============================================================================

PAPER_CLAIM_EXTRACTION_PROMPT = """You are a scientific document analyst. Your task is to extract explicit claims from a research paper WITHOUT evaluating or judging them.

<instructions>
Extract all explicit claims made in the paper. A claim is a factual statement that the authors assert to be true. For each claim:
1. Assign a short ID in the format "PC1", "PC2", "PC3", etc.
2. Extract the claim text exactly as stated by the authors
3. Include the source text (the relevant passage from the paper)

DO NOT evaluate the claims. DO NOT assess whether claims are supported or unsupported. Simply extract what the authors claim.

Focus on:
- Key findings and results
- Methodological claims
- Interpretations and conclusions
- Theoretical assertions

Return your response as a JSON object with this structure:
{{
  "claims": [
    {{
      "short_id": "PC1",
      "claim_text": "The claim as stated by authors",
      "source_text": "Relevant passage from paper"
    }}
  ]
}}
</instructions>

<paper>
{paper_text}
</paper>

Extract all claims from the paper now:"""


# ============================================================================
# STAGE 2: PAPER CLAIM EVALUATION PROMPT
# ============================================================================

PAPER_CLAIM_EVALUATION_PROMPT = """You are a scientific paper evaluator. Your task is to evaluate pre-extracted claims from a paper.

<instructions>
You will be given:
1. The full paper text
2. A list of claims that were extracted from the paper

For each claim, evaluate it and provide:
- status: "SUPPORTED", "UNSUPPORTED", or "UNCERTAIN"
- evidence: A detailed explanation of the evidence supporting your judgment
- assumptions: Any key assumptions the claim relies on
- weaknesses: Potential weaknesses or limitations in the claim
- evidence_basis: The type of evidence ("DATA", "CITATION", "KNOWLEDGE", "INFERENCE", or "SPECULATION")

Important:
- Use the full paper context when evaluating
- Keep the original claim wording intact (use the short_id to reference it)
- Be thorough and cite specific evidence from the paper
- Consider whether the evidence in the paper actually supports the claim

Return your response as a JSON object with this structure:
{{
  "evaluations": [
    {{
      "short_id": "PC1",
      "status": "SUPPORTED|UNSUPPORTED|UNCERTAIN",
      "evidence": "Detailed evidence for this judgment",
      "assumptions": "Key assumptions",
      "weaknesses": "Limitations or weaknesses",
      "evidence_basis": "DATA|CITATION|KNOWLEDGE|INFERENCE|SPECULATION"
    }}
  ]
}}
</instructions>

<paper>
{paper_text}
</paper>

<claims_to_evaluate>
{claims_json}
</claims_to_evaluate>

Evaluate each claim now:"""


# ============================================================================
# STAGE 3: REVIEW CLAIM EXTRACTION PROMPT
# ============================================================================

REVIEW_CLAIM_EXTRACTION_PROMPT = """You are a peer review analyst. Your task is to extract claims from a peer review and link them to the paper claims.

<instructions>
You will be given:
1. The peer review text
2. A list of paper claims (with their short_ids like "PC1", "PC2", etc.)

For each claim in the peer review, extract:
- claim_text: What the reviewer is claiming or asserting
- source_text: The relevant passage from the review
- reference_paper_claims: List of paper claim short_ids this review claim addresses (e.g., ["PC1", "PC3"])
- reference_rationale: Why this review claim relates to those paper claims
- reference_relation: Boolean indicating if the reviewer supports (true) or refutes (false) the referenced paper claims
  - true = reviewer agrees with / supports the referenced paper claims
  - false = reviewer disagrees with / refutes / critiques the referenced paper claims
  - null = neutral or unclear relationship

Important:
- Review claims include critiques, confirmations, questions, and suggestions
- Not all review claims will reference specific paper claims
- A single review claim may reference multiple paper claims
- Use short_ids (like "PC1", "PC3") in reference_paper_claims
- The reference_relation indicates the reviewer's stance toward the referenced claims

Return your response as a JSON object with this structure:
{{
  "claims": [
    {{
      "claim_text": "What the reviewer claims",
      "source_text": "Passage from review",
      "reference_paper_claims": ["PC1", "PC3"],
      "reference_rationale": "Why this relates to PC1 and PC3",
      "reference_relation": true
    }}
  ]
}}
</instructions>

<peer_review>
{review_text}
</peer_review>

<paper_claims>
{paper_claims_json}
</paper_claims>

Extract review claims now:"""


# ============================================================================
# STAGE 4: CONCORDANCE ANALYSIS PROMPT
# ============================================================================

CONCORDANCE_ANALYSIS_PROMPT = """You are a scientific analysis synthesizer. Your task is to analyze concordance between LLM evaluations and peer review.

<instructions>
You will be given:
1. Paper claims with their short_ids
2. LLM evaluations of those claims (status: SUPPORTED/UNSUPPORTED/UNCERTAIN)
3. Peer review claims (some of which reference paper claims)

For each paper claim, determine:
- llm_addressed: Did the LLM evaluate this claim? (true/false)
- review_addressed: Did the peer reviewers address this claim? (true/false)
- agreement_status: "agree", "disagree", or "n/a"
  - "agree": LLM and reviewers have similar assessments
  - "disagree": LLM and reviewers have conflicting assessments
  - "n/a": Cannot compare (one or both didn't address it)
- notes: Brief explanation of the comparison

Agreement rules:
- LLM says SUPPORTED + Review is positive/accepting → "agree"
- LLM says UNSUPPORTED/UNCERTAIN + Review is critical/skeptical → "agree"
- LLM says SUPPORTED + Review is critical → "disagree"
- LLM says UNSUPPORTED + Review is positive → "disagree"
- If only one addressed it → "n/a"

Return your response as a JSON object with this structure:
{{
  "concordance": [
    {{
      "paper_claim_short_id": "PC1",
      "llm_addressed": true,
      "review_addressed": true,
      "agreement_status": "agree|disagree|n/a",
      "notes": "Brief comparison explanation"
    }}
  ]
}}
</instructions>

<paper_claims>
{paper_claims_json}
</paper_claims>

<llm_evaluations>
{llm_evaluations_json}
</llm_evaluations>

<review_claims>
{review_claims_json}
</review_claims>

Analyze concordance now:"""


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================


def call_llm(prompt: str) -> dict:
    """
    Call Claude API with the given prompt and return parsed JSON response.

    Args:
        prompt: The prompt to send to Claude

    Returns:
        Parsed JSON response as a dictionary

    Raises:
        ValueError: If the API call fails or response cannot be parsed
    """
    client = Anthropic(api_key=settings.anthropic_api_key)

    try:
        response = client.messages.create(
            model=settings.anthropic_model,
            max_tokens=15000,
            temperature=0.0,
            messages=[{"role": "user", "content": prompt}],
        )

        # Extract text from response
        response_text = response.content[0].text

        # Parse JSON from response
        # Try to find JSON in the response (handle cases where LLM adds explanation)
        try:
            return json.loads(response_text)
        except json.JSONDecodeError:
            # Try to extract JSON from markdown code blocks
            if "```json" in response_text:
                json_start = response_text.find("```json") + 7
                json_end = response_text.find("```", json_start)
                json_text = response_text[json_start:json_end].strip()
                return json.loads(json_text)
            elif "```" in response_text:
                json_start = response_text.find("```") + 3
                json_end = response_text.find("```", json_start)
                json_text = response_text[json_start:json_end].strip()
                return json.loads(json_text)
            else:
                raise ValueError(
                    f"Could not parse JSON from response: {response_text[:500]}"
                )

    except APIError as e:
        raise ValueError(f"Anthropic API error: {str(e)}")
    except Exception as e:
        raise ValueError(f"Error calling LLM: {str(e)}")


# ============================================================================
# STAGE 1: EXTRACT PAPER CLAIMS
# ============================================================================


def extract_paper_claims(paper_text: str) -> Tuple[List[LLMPaperClaim], float]:
    """
    Stage 1: Extract claims from paper WITHOUT evaluation.

    Args:
        paper_text: Full text of the paper

    Returns:
        Tuple of (list of paper claims, processing time in seconds)

    Raises:
        ValueError: If extraction fails
    """
    start_time = time.time()

    prompt = PAPER_CLAIM_EXTRACTION_PROMPT.format(paper_text=paper_text)
    response_data = call_llm(prompt)

    # Validate response structure
    if "claims" not in response_data:
        raise ValueError("LLM response missing 'claims' field")

    # Parse into Pydantic models
    try:
        llm_response = LLMPaperClaimsResponse(**response_data)
    except Exception as e:
        raise ValueError(f"Failed to parse LLM response: {str(e)}")

    processing_time = time.time() - start_time
    return llm_response.claims, processing_time


# ============================================================================
# STAGE 2: EVALUATE PAPER CLAIMS
# ============================================================================


def evaluate_paper_claims(
    paper_text: str, paper_claims: List[PaperClaim]
) -> Tuple[List[LLMEvaluationResult], float]:
    """
    Stage 2: Evaluate pre-extracted paper claims.

    Args:
        paper_text: Full text of the paper
        paper_claims: List of paper claims to evaluate

    Returns:
        Tuple of (list of evaluations, processing time in seconds)

    Raises:
        ValueError: If evaluation fails
    """
    start_time = time.time()

    # Convert paper claims to JSON for the prompt
    claims_for_prompt = [
        {
            "short_id": claim.short_id,
            "claim_text": claim.claim_text,
            "source_text": claim.source_text,
        }
        for claim in paper_claims
    ]
    claims_json = json.dumps(claims_for_prompt, indent=2)

    prompt = PAPER_CLAIM_EVALUATION_PROMPT.format(
        paper_text=paper_text, claims_json=claims_json
    )
    response_data = call_llm(prompt)

    # Validate response structure
    if "evaluations" not in response_data:
        raise ValueError("LLM response missing 'evaluations' field")

    # Parse into Pydantic models
    try:
        llm_response = LLMEvaluationsResponse(**response_data)
    except Exception as e:
        raise ValueError(f"Failed to parse LLM response: {str(e)}")

    processing_time = time.time() - start_time
    return llm_response.evaluations, processing_time


# ============================================================================
# STAGE 3: EXTRACT REVIEW CLAIMS
# ============================================================================


def extract_review_claims(
    review_text: str, paper_claims: List[PaperClaim]
) -> Tuple[List[LLMReviewClaim], float]:
    """
    Stage 3: Extract claims from peer review and link to paper claims.

    Args:
        review_text: Full text of peer review
        paper_claims: List of paper claims to reference

    Returns:
        Tuple of (list of review claims, processing time in seconds)

    Raises:
        ValueError: If extraction fails
    """
    start_time = time.time()

    # Convert paper claims to JSON for the prompt
    claims_for_prompt = [
        {"short_id": claim.short_id, "claim_text": claim.claim_text}
        for claim in paper_claims
    ]
    paper_claims_json = json.dumps(claims_for_prompt, indent=2)

    prompt = REVIEW_CLAIM_EXTRACTION_PROMPT.format(
        review_text=review_text, paper_claims_json=paper_claims_json
    )
    response_data = call_llm(prompt)

    # Validate response structure
    if "claims" not in response_data:
        raise ValueError("LLM response missing 'claims' field")

    # Parse into Pydantic models
    try:
        llm_response = LLMReviewClaimsResponse(**response_data)
    except Exception as e:
        raise ValueError(f"Failed to parse LLM response: {str(e)}")

    processing_time = time.time() - start_time
    return llm_response.claims, processing_time


# ============================================================================
# STAGE 4: ANALYZE CONCORDANCE
# ============================================================================


def analyze_concordance(
    paper_claims: List[PaperClaim],
    llm_evaluations: List[LLMEvaluationResult],
    review_claims: List[LLMReviewClaim],
) -> Tuple[List[LLMConcordanceRow], float]:
    """
    Stage 4: Analyze concordance between LLM evaluations and peer review.

    Args:
        paper_claims: List of paper claims
        llm_evaluations: List of LLM evaluations
        review_claims: List of review claims

    Returns:
        Tuple of (list of concordance rows, processing time in seconds)

    Raises:
        ValueError: If analysis fails
    """
    start_time = time.time()

    # Convert data to JSON for the prompt
    paper_claims_json = json.dumps(
        [
            {"short_id": claim.short_id, "claim_text": claim.claim_text}
            for claim in paper_claims
        ],
        indent=2,
    )

    llm_evaluations_json = json.dumps(
        [
            {
                "short_id": eval.short_id,
                "status": eval.status,
                "evidence": eval.evidence,
            }
            for eval in llm_evaluations
        ],
        indent=2,
    )

    review_claims_json = json.dumps(
        [
            {
                "claim_text": claim.claim_text,
                "reference_paper_claims": claim.reference_paper_claims or [],
                "reference_rationale": claim.reference_rationale,
            }
            for claim in review_claims
        ],
        indent=2,
    )

    prompt = CONCORDANCE_ANALYSIS_PROMPT.format(
        paper_claims_json=paper_claims_json,
        llm_evaluations_json=llm_evaluations_json,
        review_claims_json=review_claims_json,
    )
    response_data = call_llm(prompt)

    # Validate response structure
    if "concordance" not in response_data:
        raise ValueError("LLM response missing 'concordance' field")

    # Parse into Pydantic models
    try:
        llm_response = LLMConcordanceResponse(**response_data)
    except Exception as e:
        raise ValueError(f"Failed to parse LLM response: {str(e)}")

    processing_time = time.time() - start_time
    return llm_response.concordance, processing_time


# ============================================================================
# CONCORDANCE METRICS CALCULATION
# ============================================================================


def calculate_concordance_metrics(concordance_table: List[LLMConcordanceRow]) -> dict:
    """
    Calculate summary metrics from concordance analysis.

    Args:
        concordance_table: List of concordance rows

    Returns:
        Dictionary with concordance metrics
    """
    total_claims = len(concordance_table)

    if total_claims == 0:
        return {
            "total_claims": 0,
            "llm_addressed_count": 0,
            "review_addressed_count": 0,
            "both_addressed_count": 0,
            "agreement_count": 0,
            "disagreement_count": 0,
            "agreement_rate": 0.0,
        }

    llm_addressed = sum(1 for row in concordance_table if row.llm_addressed)
    review_addressed = sum(1 for row in concordance_table if row.review_addressed)
    both_addressed = sum(
        1 for row in concordance_table if row.llm_addressed and row.review_addressed
    )

    agreements = sum(1 for row in concordance_table if row.agreement_status == "agree")
    disagreements = sum(
        1 for row in concordance_table if row.agreement_status == "disagree"
    )

    # Agreement rate is calculated only for claims where both addressed
    agreement_rate = (agreements / both_addressed * 100) if both_addressed > 0 else 0.0

    return {
        "total_claims": total_claims,
        "llm_addressed_count": llm_addressed,
        "review_addressed_count": review_addressed,
        "both_addressed_count": both_addressed,
        "agreement_count": agreements,
        "disagreement_count": disagreements,
        "agreement_rate": round(agreement_rate, 2),
    }
