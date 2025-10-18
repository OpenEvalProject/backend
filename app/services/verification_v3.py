"""
Verification service for V3 workflow - Results-based grouping approach.

This module implements a 4-stage workflow:
1. Extract atomic factual claims from manuscript
2. LLM groups claims into results (with evaluation)
3. Peer review groups claims into results (with evaluation)
4. Compare results between LLM and peer reviewer
"""

import json
import time
from typing import List, Tuple

from anthropic import Anthropic

from app.config import settings
from app.models import (
    LLMClaimV3,
    LLMClaimsResponseV3,
    LLMResultV3,
    LLMResultsResponseV3,
    LLMResultsConcordanceRow,
    LLMResultsConcordanceResponse,
)


def get_anthropic_client():
    """Get configured Anthropic client with extended timeout for large responses"""
    return Anthropic(
        api_key=settings.anthropic_api_key,
        timeout=600.0,  # 10 minutes to handle large token responses
    )


def extract_json_from_response(response_text: str) -> str:
    """
    Extract JSON from LLM response, handling markdown code fences and extra text.

    Args:
        response_text: Raw response text from LLM

    Returns:
        Cleaned JSON string
    """
    # Strip whitespace
    text = response_text.strip()

    # Check for markdown code fences anywhere in the text
    if "```" in text:
        lines = text.split("\n")
        start_idx = None
        end_idx = None

        # Find the first opening fence
        for i, line in enumerate(lines):
            if line.strip().startswith("```"):
                start_idx = i + 1
                break

        # If we found an opening fence, find the closing fence
        if start_idx is not None:
            for i in range(start_idx, len(lines)):
                if lines[i].strip() == "```":
                    end_idx = i
                    break

            # If we found both fences, extract the content
            if end_idx is not None and start_idx < end_idx:
                text = "\n".join(lines[start_idx:end_idx])
            elif start_idx is not None:
                # Opening fence found but no closing fence - take everything after opening
                text = "\n".join(lines[start_idx:])

    # If text is empty or only whitespace, try to find JSON starting with { or [
    if not text.strip():
        # Look for JSON object/array start
        for start_char in ['{', '[']:
            idx = response_text.find(start_char)
            if idx >= 0:
                text = response_text[idx:]
                break

    return text.strip()


# ============================================================================
# STAGE 1: EXTRACT CLAIMS FROM MANUSCRIPT
# ============================================================================

STAGE1_PROMPT_TEMPLATE = """You are a scientific claim extraction expert. Your task is to extract ALL atomic factual claims from a scientific manuscript.

# Claim Extraction Guidelines

## What is an Atomic Factual Claim?
An atomic factual claim is a single, discrete, factual statement that:
- Makes ONE specific assertion about the world
- Can be evaluated as supported or unsupported independently
- Cannot be meaningfully broken down into smaller factual components

## Claim Types
- **EXPLICIT**: Directly stated in the text
- **IMPLICIT**: Logically follows from what is stated but not directly written

## Evidence Types (can be multiple)
- **DATA**: Based on experimental data, measurements, or observations presented in the paper
- **CITATION**: Supported by citation to other work
- **KNOWLEDGE**: Relies on established scientific knowledge or consensus
- **INFERENCE**: Logical inference from presented information
- **SPECULATION**: Speculative or hypothetical assertion

## Extraction Rules
1. Extract ALL factual claims, both major findings and supporting statements
2. Each claim should be completely self-contained and understandable on its own
3. Include exact source text (direct quote from manuscript)
4. Provide brief reasoning for evidence type classification
5. Use sequential IDs: C1, C2, C3, etc.
6. DO NOT evaluate claims - only extract and categorize them

## Example Output Format
```json
{
  "claims": [
    {
      "claim_id": "C1",
      "claim": "Protein X phosphorylates protein Y at serine 123",
      "claim_type": "EXPLICIT",
      "source_text": "We found that protein X directly phosphorylates protein Y at serine 123 in vitro",
      "evidence_type": ["DATA"],
      "evidence_reasoning": "Based on experimental phosphorylation assay results presented in Figure 2"
    },
    {
      "claim_id": "C2",
      "claim": "Phosphorylation of Y is required for cell migration",
      "claim_type": "EXPLICIT",
      "source_text": "Cells expressing non-phosphorylatable Y-S123A showed 80% reduction in migration",
      "evidence_type": ["DATA", "INFERENCE"],
      "evidence_reasoning": "Direct measurement of cell migration combined with inference about requirement"
    }
  ]
}
```

# Manuscript to Analyze

$MANUSCRIPT_TEXT

Please extract ALL atomic factual claims from this manuscript. Return ONLY valid JSON matching the schema above."""


def extract_claims(manuscript_text: str) -> Tuple[List[LLMClaimV3], float]:
    """
    Stage 1: Extract atomic factual claims from manuscript.

    Args:
        manuscript_text: Full text of the manuscript

    Returns:
        Tuple of (list of extracted claims, processing time in seconds)

    Raises:
        ValueError: If LLM response is invalid or cannot be parsed
    """
    client = get_anthropic_client()
    start_time = time.time()

    # Use simple string replacement to avoid issues with curly braces in manuscript text
    prompt = STAGE1_PROMPT_TEMPLATE.replace("$MANUSCRIPT_TEXT", manuscript_text)

    try:
        message = client.messages.create(
            model=settings.anthropic_model,
            max_tokens=30000,  # Large limit for extensive claim extraction
            temperature=0.0,
            messages=[{"role": "user", "content": prompt}],
        )

        response_text = message.content[0].text

        # Extract JSON from response (handle markdown code fences)
        json_text = extract_json_from_response(response_text)

        # Debug: Check if extraction worked
        if not json_text or not json_text.strip():
            raise ValueError(f"Failed to extract JSON from response. Response text: {response_text[:1000]}")

        # Parse JSON response
        try:
            response_data = json.loads(json_text)
            llm_response = LLMClaimsResponseV3(**response_data)
        except json.JSONDecodeError as e:
            raise ValueError(f"Failed to parse LLM response as JSON: {e}\nExtracted JSON: {json_text[:500]}\nFull response: {response_text[:1000]}")
        except Exception as e:
            raise ValueError(f"Failed to validate LLM response: {e}\nExtracted JSON: {json_text[:500]}\nFull response: {response_text[:1000]}")

        processing_time = time.time() - start_time
        return llm_response.claims, processing_time

    except Exception as e:
        raise ValueError(f"Stage 1 (Claim Extraction) failed: {str(e)}")


# ============================================================================
# STAGE 2: LLM GROUPS CLAIMS INTO RESULTS
# ============================================================================

STAGE2_PROMPT_TEMPLATE = """You are a scientific evaluation expert. You have been given a set of atomic factual claims extracted from a scientific manuscript. Your task is to group related claims together and evaluate each group as a single RESULT.

# Result Grouping Guidelines

## What is a Result?
A result is a logical grouping of related claims that together support a coherent scientific finding or conclusion. Results represent meaningful units of scientific work.

## Grouping Principles
1. Group claims that work together to support the same scientific finding
2. A result can contain 1 or more claims
3. Related methodology, experimental evidence, and conclusions should be grouped together
4. Keep results focused - don't combine unrelated findings

## Status Evaluation
Evaluate each result as a whole:
- **SUPPORTED**: The grouped claims are well-supported by the evidence presented
- **UNSUPPORTED**: The grouped claims are not adequately supported
- **UNCERTAIN**: Insufficient evidence to determine support

## Status Reasoning
Provide a brief explanation (2-3 sentences) justifying the status evaluation for each result.

# Manuscript (for context)

$MANUSCRIPT_TEXT

# Extracted Claims

$CLAIMS_JSON

## Example Output Format
```json
{
  "results": [
    {
      "claim_ids": ["C1", "C2", "C3"],
      "status": "SUPPORTED",
      "status_reasoning": "Claims C1-C3 collectively establish that protein X phosphorylates protein Y and this is functionally important. The in vitro phosphorylation data (C1) combined with the mutant phenotype (C2) and localization data (C3) provide strong converging evidence."
    },
    {
      "claim_ids": ["C4"],
      "status": "UNCERTAIN",
      "status_reasoning": "While the correlation between X expression and patient outcomes is shown, the mechanistic link is speculative without additional validation."
    }
  ]
}
```

Please group the claims into results and evaluate each result. Return ONLY valid JSON matching the schema above."""


def llm_group_claims_into_results(
    manuscript_text: str, claims: List[LLMClaimV3]
) -> Tuple[List[LLMResultV3], float]:
    """
    Stage 2: LLM groups claims into results and evaluates each result.

    Args:
        manuscript_text: Full text of the manuscript (for context)
        claims: List of extracted claims from Stage 1

    Returns:
        Tuple of (list of results, processing time in seconds)

    Raises:
        ValueError: If LLM response is invalid or cannot be parsed
    """
    client = get_anthropic_client()
    start_time = time.time()

    # Convert claims to JSON for prompt
    claims_json = json.dumps(
        [
            {
                "claim_id": c.claim_id,
                "claim": c.claim,
                "claim_type": c.claim_type,
                "source_text": c.source_text,
                "evidence_type": c.evidence_type,
                "evidence_reasoning": c.evidence_reasoning,
            }
            for c in claims
        ],
        indent=2,
    )

    # Use simple string replacement to avoid issues with curly braces
    prompt = STAGE2_PROMPT_TEMPLATE.replace("$MANUSCRIPT_TEXT", manuscript_text).replace("$CLAIMS_JSON", claims_json)

    try:
        message = client.messages.create(
            model=settings.anthropic_model,
            max_tokens=30000,  # Large limit for extensive result grouping
            temperature=0.0,
            messages=[{"role": "user", "content": prompt}],
        )

        response_text = message.content[0].text

        # Extract JSON from response (handle markdown code fences)
        json_text = extract_json_from_response(response_text)

        # Debug: Check if extraction worked
        if not json_text or not json_text.strip():
            raise ValueError(f"Failed to extract JSON from response. Response text: {response_text[:1000]}")

        # Parse JSON response
        try:
            response_data = json.loads(json_text)
            llm_response = LLMResultsResponseV3(**response_data)
        except json.JSONDecodeError as e:
            raise ValueError(f"Failed to parse LLM response as JSON: {e}\nExtracted JSON: {json_text[:500]}\nFull response: {response_text[:1000]}")
        except Exception as e:
            raise ValueError(f"Failed to validate LLM response: {e}\nExtracted JSON: {json_text[:500]}\nFull response: {response_text[:1000]}")

        processing_time = time.time() - start_time
        return llm_response.results, processing_time

    except Exception as e:
        raise ValueError(f"Stage 2 (LLM Result Grouping) failed: {str(e)}")


# ============================================================================
# STAGE 3: PEER REVIEW GROUPS CLAIMS INTO RESULTS
# ============================================================================

STAGE3_PROMPT_TEMPLATE = """You are a scientific peer review expert. You have been given:
1. A set of atomic factual claims extracted from a scientific manuscript
2. The peer review comments for that manuscript

Your task is to identify which claims the peer reviewers are addressing and group them into RESULTS that represent the reviewers' perspective.

# Result Grouping from Peer Review

## Guidelines
1. Identify which manuscript claims the reviewers are discussing
2. Group related claims together as the reviewers would see them
3. Evaluate each group based on the reviewer's assessment
4. Focus on what reviewers EXPLICITLY mention or critique

## Status Evaluation
Based on peer review comments:
- **SUPPORTED**: Reviewers affirm or do not challenge these claims
- **UNSUPPORTED**: Reviewers explicitly critique or reject these claims
- **UNCERTAIN**: Reviewers express concerns or request additional validation

## Status Reasoning
Explain the reviewer's perspective on each result. Quote or paraphrase reviewer comments when relevant.

# Manuscript Claims

$CLAIMS_JSON

# Peer Review Text

$REVIEW_TEXT

## Example Output Format
```json
{
  "results": [
    {
      "claim_ids": ["C1", "C2"],
      "status": "UNSUPPORTED",
      "status_reasoning": "Reviewer 2 specifically questions the phosphorylation data, stating 'the in vitro assay does not demonstrate physiological relevance' and requests in vivo validation."
    },
    {
      "claim_ids": ["C5", "C6"],
      "status": "SUPPORTED",
      "status_reasoning": "Reviewer 1 notes 'the microscopy data convincingly shows colocalization' and does not raise concerns about these findings."
    }
  ]
}
```

Please identify which claims reviewers address, group them into results, and evaluate based on reviewer commentary. Return ONLY valid JSON matching the schema above."""


def peer_review_group_claims_into_results(
    claims: List[LLMClaimV3], review_text: str
) -> Tuple[List[LLMResultV3], float]:
    """
    Stage 3: Extract results from peer review based on manuscript claims.

    Args:
        claims: List of extracted claims from Stage 1
        review_text: Full text of peer review

    Returns:
        Tuple of (list of results from reviewer perspective, processing time in seconds)

    Raises:
        ValueError: If LLM response is invalid or cannot be parsed
    """
    client = get_anthropic_client()
    start_time = time.time()

    # Convert claims to JSON for prompt
    claims_json = json.dumps(
        [
            {
                "claim_id": c.claim_id,
                "claim": c.claim,
                "claim_type": c.claim_type,
                "source_text": c.source_text,
                "evidence_type": c.evidence_type,
                "evidence_reasoning": c.evidence_reasoning,
            }
            for c in claims
        ],
        indent=2,
    )

    # Use simple string replacement to avoid issues with curly braces
    prompt = STAGE3_PROMPT_TEMPLATE.replace("$CLAIMS_JSON", claims_json).replace("$REVIEW_TEXT", review_text)

    try:
        message = client.messages.create(
            model=settings.anthropic_model,
            max_tokens=30000,  # Large limit for extensive peer review analysis
            temperature=0.0,
            messages=[{"role": "user", "content": prompt}],
        )

        response_text = message.content[0].text

        # Extract JSON from response (handle markdown code fences)
        json_text = extract_json_from_response(response_text)

        # Debug: Check if extraction worked
        if not json_text or not json_text.strip():
            raise ValueError(f"Failed to extract JSON from response. Response text: {response_text[:1000]}")

        # Parse JSON response
        try:
            response_data = json.loads(json_text)
            llm_response = LLMResultsResponseV3(**response_data)
        except json.JSONDecodeError as e:
            raise ValueError(f"Failed to parse LLM response as JSON: {e}\nExtracted JSON: {json_text[:500]}\nFull response: {response_text[:1000]}")
        except Exception as e:
            raise ValueError(f"Failed to validate LLM response: {e}\nExtracted JSON: {json_text[:500]}\nFull response: {response_text[:1000]}")

        processing_time = time.time() - start_time
        return llm_response.results, processing_time

    except Exception as e:
        raise ValueError(f"Stage 3 (Peer Review Result Grouping) failed: {str(e)}")


# ============================================================================
# STAGE 4: COMPARE RESULTS BETWEEN LLM AND PEER REVIEW
# ============================================================================

STAGE4_PROMPT_TEMPLATE = """You are a scientific concordance analysis expert. You have been given:
1. Results grouped by an LLM evaluator
2. Results grouped by peer reviewers

Your task is to compare these results and identify areas of agreement and disagreement.

# Concordance Analysis Guidelines

## Matching Strategy
1. Identify which LLM results and peer review results address the same or overlapping claims
2. Look for claim_ids that appear in both LLM and peer results
3. Results may address overlapping or completely different claims

## Agreement Status
- **agree**: Both LLM and reviewers have the same status evaluation (both SUPPORTED, both UNSUPPORTED, or both UNCERTAIN)
- **disagree**: LLM and reviewers have different status evaluations
- **disjoint**: One evaluator produced a result, but the other did not (one side has no result)

## Notes
Provide brief explanation of the comparison, especially for disagreements or disjoint cases.

# LLM Results

$LLM_RESULTS_JSON

# Peer Review Results

$PEER_RESULTS_JSON

## Example Output Format
```json
{
  "concordance": [
    {
      "llm_claim_ids": ["C1", "C2", "C3"],
      "peer_claim_ids": ["C1", "C2"],
      "llm_status": "SUPPORTED",
      "peer_status": "UNSUPPORTED",
      "agreement_status": "disagree",
      "notes": "Both address the phosphorylation findings (C1, C2), but LLM groups with C3 and finds evidence sufficient, while reviewers question physiological relevance."
    },
    {
      "llm_claim_ids": ["C5"],
      "peer_claim_ids": ["C5", "C6"],
      "llm_status": "SUPPORTED",
      "peer_status": "SUPPORTED",
      "agreement_status": "agree",
      "notes": "Both agree the microscopy data is convincing, though peer review groups C5 with related claim C6."
    }
  ]
}
```

Please compare the LLM and peer review results. Return ONLY valid JSON matching the schema above."""


def compare_results(
    llm_results: List[LLMResultV3], peer_results: List[LLMResultV3]
) -> Tuple[List[LLMResultsConcordanceRow], float]:
    """
    Stage 4: Compare results between LLM and peer review.

    Args:
        llm_results: Results from LLM evaluation (Stage 2)
        peer_results: Results from peer review (Stage 3)

    Returns:
        Tuple of (list of concordance rows, processing time in seconds)

    Raises:
        ValueError: If LLM response is invalid or cannot be parsed
    """
    client = get_anthropic_client()
    start_time = time.time()

    # Convert results to JSON for prompt
    llm_results_json = json.dumps(
        [
            {
                "claim_ids": r.claim_ids,
                "status": r.status,
                "status_reasoning": r.status_reasoning,
            }
            for r in llm_results
        ],
        indent=2,
    )

    peer_results_json = json.dumps(
        [
            {
                "claim_ids": r.claim_ids,
                "status": r.status,
                "status_reasoning": r.status_reasoning,
            }
            for r in peer_results
        ],
        indent=2,
    )

    # Use simple string replacement to avoid issues with curly braces
    prompt = STAGE4_PROMPT_TEMPLATE.replace("$LLM_RESULTS_JSON", llm_results_json).replace("$PEER_RESULTS_JSON", peer_results_json)

    try:
        message = client.messages.create(
            model=settings.anthropic_model,
            max_tokens=30000,  # Large limit for extensive concordance analysis
            temperature=0.0,
            messages=[{"role": "user", "content": prompt}],
        )

        response_text = message.content[0].text

        # Extract JSON from response (handle markdown code fences)
        json_text = extract_json_from_response(response_text)

        # Debug: Check if extraction worked
        if not json_text or not json_text.strip():
            raise ValueError(f"Failed to extract JSON from response. Response text: {response_text[:1000]}")

        # Parse JSON response
        try:
            response_data = json.loads(json_text)
            llm_response = LLMResultsConcordanceResponse(**response_data)
        except json.JSONDecodeError as e:
            raise ValueError(f"Failed to parse LLM response as JSON: {e}\nExtracted JSON: {json_text[:500]}\nFull response: {response_text[:1000]}")
        except Exception as e:
            raise ValueError(f"Failed to validate LLM response: {e}\nExtracted JSON: {json_text[:500]}\nFull response: {response_text[:1000]}")

        processing_time = time.time() - start_time
        return llm_response.concordance, processing_time

    except Exception as e:
        raise ValueError(f"Stage 4 (Results Concordance) failed: {str(e)}")


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================


def calculate_results_metrics(
    llm_results: List[LLMResultV3],
    peer_results: List[LLMResultV3],
    concordance: List[LLMResultsConcordanceRow],
) -> dict:
    """
    Calculate summary metrics for V3 workflow.

    Args:
        llm_results: LLM evaluation results
        peer_results: Peer review results
        concordance: Concordance analysis

    Returns:
        Dictionary with metrics including agreement rate
    """
    total_comparisons = len(concordance)
    agreements = sum(1 for row in concordance if row.agreement_status == "agree")
    disagreements = sum(1 for row in concordance if row.agreement_status == "disagree")
    disjoint = sum(1 for row in concordance if row.agreement_status == "disjoint")

    agreement_rate = (
        (agreements / total_comparisons * 100) if total_comparisons > 0 else 0.0
    )

    return {
        "total_comparisons": total_comparisons,
        "agreements": agreements,
        "disagreements": disagreements,
        "disjoint": disjoint,
        "agreement_rate": agreement_rate,
    }
