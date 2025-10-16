import json
import time
from typing import List, Tuple

from anthropic import Anthropic, APIError

from app.config import settings
from app.models import (
    LLMAnalysisResponse,
    LLMClaim,
    LLMPaperClaimsResponse,
    LLMPaperClaim,
    LLMEvaluationsResponse,
    LLMEvaluationResult,
    LLMReviewClaimsResponse,
    LLMReviewClaim,
    LLMConcordanceResponse,
    LLMConcordanceRow,
)


MANUSCRIPT_CLAIM_EXTRACTION_PROMPT = """You are a CRITICAL BUT FAIR scientific reviewer analyzing a manuscript for publication.

<instructions>
Your task is to:
1. Extract all verifiable factual claims from the manuscript text
2. For each claim, identify the source text where it appears
3. Classify each claim by its evidence basis
4. Critically evaluate if each claim is SUPPORTED, UNSUPPORTED, or UNCERTAIN

IMPORTANT: You can ONLY verify claims based on:
- Internal consistency (comparing claims against other content within the manuscript)
- General knowledge (well-established scientific facts that are universally accepted)

You do NOT have access to external papers, databases, raw data, or domain-specific expertise.
Therefore, most claims will appropriately be marked as UNCERTAIN pending external verification.
</instructions>

<claim_definition>
A scientific claim is an ATOMIC VERIFIABLE STATEMENT expressing a finding about one aspect of a scientific entity or process.

Valid claim examples:
- "The R0 of the novel coronavirus is 2.5"
- "Aerosolized coronavirus droplets can travel at least 6 feet"
- "Droplets can remain in the air for 3 hours"

Do NOT include:
- Opinion-based statements
- Compound claims (split them into separate atomic claims)
- Purely speculative statements without basis
</claim_definition>

<evidence_basis>
Classify each claim's evidence basis as ONE of:

- DATA: Grounded in THIS paper's experimental or observational data
- CITATION: Grounded in external cited work
- KNOWLEDGE: Grounded in well-established facts
- INFERENCE: Grounded in logical reasoning from data or knowledge
- SPECULATION: Grounded in hypothesis or prediction not yet verified
</evidence_basis>

<verification_criteria>
SUPPORTED - Only if you can definitively verify using internal consistency or general knowledge:
- KNOWLEDGE claims with universally accepted facts
- INFERENCE claims with sound logical reasoning and stated premises
- Claims consistently supported by multiple parts of the manuscript
- Methodological descriptions clearly stated in the manuscript

UNSUPPORTED - Only if you can definitively identify a problem:
- Internal contradictions within the manuscript
- INFERENCE claims with demonstrable logical errors
- Claims contradicting well-established scientific knowledge
- Clear overstatement of what the manuscript presents

UNCERTAIN - For claims requiring external verification (MOST CLAIMS):
- DATA claims (cannot verify experimental results or statistical analysis)
- CITATION claims (cannot verify cited work)
- Quantitative claims (cannot verify without raw data)
- Any claim requiring tools, external information, or domain expertise

BE REALISTIC: Most scientific claims require external verification. A high UNCERTAIN rate (60-80%) is expected and appropriate.
</verification_criteria>

<output_format>
Return ONLY a JSON object with this structure (no other text before or after):

{
  "claims": [
    {
      "claim": "String describing the atomic factual claim",
      "source_text": "The excerpt from the manuscript where this claim appears (keep it concise, 1-2 sentences max)",
      "status": "SUPPORTED|UNSUPPORTED|UNCERTAIN",
      "evidence": "Brief explanation of verification reasoning (1-2 sentences)",
      "evidence_basis": "DATA|CITATION|KNOWLEDGE|INFERENCE|SPECULATION",
      "reference_claims": null,
      "reference_rationale": null
    }
  ]
}

IMPORTANT: For manuscript claims, always set reference_claims to null and reference_rationale to null.
</output_format>

<manuscript>
"""


CLAIM_EXTRACTION_WITH_REFERENCES_PROMPT = """You are a CRITICAL BUT FAIR scientific reviewer analyzing scientific text.

<context>
You will be provided with:
1. A JSON array of previously extracted claims with their claim_id values (from another document, such as a manuscript or peer review)
2. New text to analyze (such as peer reviews or author responses)

Your task: Extract NEW claims from the provided text and identify which (if any) of the previously extracted claims each new claim references.
</context>

<instructions>
1. Extract all atomic factual claims from the new text
2. For each claim, identify the source text where it appears
3. Classify each claim by its evidence basis
4. Evaluate if each claim is SUPPORTED, UNSUPPORTED, or UNCERTAIN
5. Identify which previous claims (by claim_id) each new claim references
6. Explain why/how the new claim references those previous claims
</instructions>

<claim_definition>
A scientific claim is an ATOMIC VERIFIABLE STATEMENT expressing a finding, critique, suggestion, or response about one aspect of a scientific entity or process.

Valid claim examples:
- "The statistical analysis in Figure 2 is incorrect" (reviewer critique)
- "We have revised the statistical analysis to use a more appropriate test" (author response)
- "The sample size is too small to support the conclusions" (reviewer critique)
- "We acknowledge the limitation and have added discussion of the sample size" (author response)

Do NOT include:
- Non-specific statements (e.g., "This is a good paper")
- Compound claims (split them into separate atomic claims)
- Editorial comments without factual content
</claim_definition>

<evidence_basis>
Classify each claim's evidence basis as ONE of:

- DATA: Grounded in experimental or observational data
- CITATION: Grounded in external cited work
- KNOWLEDGE: Grounded in well-established facts
- INFERENCE: Grounded in logical reasoning from data or knowledge
- SPECULATION: Grounded in hypothesis or prediction not yet verified
</evidence_basis>

<verification_status>
Classify each claim as:
- SUPPORTED: The claim is well-supported by evidence or logic
- UNSUPPORTED: The claim contradicts evidence or has logical flaws
- UNCERTAIN: The claim cannot be verified with available information
</verification_status>

<reference_tracking>
For each extracted claim:
1. Identify if it references any previously extracted claims
2. List the claim_id values of ALL referenced claims in the "reference_claims" array
3. Provide a brief explanation in "reference_rationale" describing how/why this claim references those claims

A claim references another claim when it:
- Directly responds to or addresses the referenced claim
- Critiques or evaluates the referenced claim
- Builds upon or extends the referenced claim
- Acknowledges or incorporates the referenced claim
- Provides evidence for or against the referenced claim

If a claim does NOT reference any previous claims:
- Set "reference_claims" to an empty array []
- Set "reference_rationale" to null
</reference_tracking>

<output_format>
Return ONLY a JSON object with this structure (no other text before or after):

{
  "claims": [
    {
      "claim": "String describing the atomic factual claim",
      "source_text": "The excerpt from the text where this claim appears (keep it concise, 1-2 sentences max)",
      "status": "SUPPORTED|UNSUPPORTED|UNCERTAIN",
      "evidence": "Brief explanation of verification reasoning (1-2 sentences)",
      "evidence_basis": "DATA|CITATION|KNOWLEDGE|INFERENCE|SPECULATION",
      "reference_claims": [1, 5, 12],
      "reference_rationale": "This claim directly addresses claims 1, 5, and 12 by providing a revised analysis methodology"
    }
  ]
}
</output_format>

<previous_claims>
{previous_claims}
</previous_claims>

<text_to_analyze>
{new_text}
</text_to_analyze>
"""


def count_tokens(text: str) -> int:
    """
    Rough approximation of token count.
    1 token ≈ 4 characters for English text.
    """
    return len(text) // 4


def verify_claims(full_text: str) -> Tuple[List[LLMClaim], float]:
    """
    Use LLM to extract and verify claims from manuscript.

    Args:
        full_text: The complete manuscript text

    Returns:
        Tuple of (list of claims, processing time in seconds)

    Raises:
        ValueError: If text is too long or LLM returns invalid response
    """
    # Check token count
    token_count = count_tokens(full_text)
    if token_count > settings.max_tokens:
        raise ValueError(
            f"Document exceeds maximum length of {settings.max_tokens} tokens "
            f"(estimated {token_count} tokens)"
        )

    start_time = time.time()

    # Initialize Anthropic client
    client = Anthropic(api_key=settings.llm_api_key)

    # Prepare the prompt with proper XML tag closure
    full_prompt = MANUSCRIPT_CLAIM_EXTRACTION_PROMPT + full_text + "\n</manuscript>"

    # Call the LLM with extended timeout and retry logic
    max_retries = 3
    retry_delay = 2  # seconds

    for attempt in range(max_retries):
        try:
            response = client.messages.create(
                model=settings.llm_model,
                max_tokens=16000,
                temperature=0,
                messages=[{"role": "user", "content": full_prompt}],
                timeout=600.0,  # 10 minute timeout
            )
            break  # Success, exit retry loop
        except APIError as e:
            if "overloaded" in str(e).lower() and attempt < max_retries - 1:
                print(f"API overloaded, retrying in {retry_delay} seconds... (attempt {attempt + 1}/{max_retries})")
                time.sleep(retry_delay)
                retry_delay *= 2  # Exponential backoff
                continue
            else:
                raise  # Re-raise if not overloaded or out of retries
    else:
        raise ValueError("Failed after maximum retries")

    # Extract the response text
    response_text = response.content[0].text

    # Parse JSON response
    try:
        # Remove markdown code fences if present
        if "```" in response_text:
            # Find content between code fences
            start_marker = response_text.find("```")
            if start_marker != -1:
                # Skip past the opening fence and optional "json" language identifier
                content_start = response_text.find("\n", start_marker) + 1
                # Find closing fence
                end_marker = response_text.find("```", content_start)
                if end_marker != -1:
                    response_text = response_text[content_start:end_marker].strip()

        # Try to extract JSON if there's extra text
        json_start = response_text.find("{")
        json_end = response_text.rfind("}") + 1
        if json_start != -1 and json_end > json_start:
            json_text = response_text[json_start:json_end]
        else:
            json_text = response_text

        response_data = json.loads(json_text)
        analysis = LLMAnalysisResponse(**response_data)
    except (json.JSONDecodeError, ValueError) as e:
        # Log the actual response for debugging
        print(f"Failed to parse LLM response. Error: {e}")
        print(f"Response text (first 500 chars): {response_text[:500]}")
        raise ValueError(
            f"LLM returned invalid JSON: {str(e)}. Response preview: {response_text[:200]}"
        )

    processing_time = time.time() - start_time

    if not analysis.claims:
        raise ValueError("LLM did not extract any claims from the document")

    return analysis.claims, processing_time


def calculate_verification_score(claims: List[LLMClaim]) -> Tuple[int, int, int, float]:
    """
    Calculate verification metrics from claims.

    Args:
        claims: List of claims with status

    Returns:
        Tuple of (supported_count, unsupported_count, uncertain_count, verification_score)
    """
    supported = sum(1 for c in claims if c.status == "SUPPORTED")
    unsupported = sum(1 for c in claims if c.status == "UNSUPPORTED")
    uncertain = sum(1 for c in claims if c.status == "UNCERTAIN")

    # Score is supported / (supported + unsupported), excluding uncertain claims
    verifiable = supported + unsupported
    score = (supported / verifiable * 100) if verifiable > 0 else 0.0

    return supported, unsupported, uncertain, score


def calculate_evidence_basis_breakdown(claims: List[LLMClaim]) -> dict:
    """
    Calculate verification metrics per evidence basis type.

    Args:
        claims: List of claims with status and evidence_basis

    Returns:
        Dictionary with evidence basis types as keys and metrics as values
    """
    from collections import defaultdict

    breakdown = defaultdict(
        lambda: {
            "total": 0,
            "supported": 0,
            "unsupported": 0,
            "uncertain": 0,
            "score": 0.0,
        }
    )

    for claim in claims:
        basis = claim.evidence_basis or "UNKNOWN"
        breakdown[basis]["total"] += 1

        if claim.status == "SUPPORTED":
            breakdown[basis]["supported"] += 1
        elif claim.status == "UNSUPPORTED":
            breakdown[basis]["unsupported"] += 1
        elif claim.status == "UNCERTAIN":
            breakdown[basis]["uncertain"] += 1

    # Calculate scores for each basis
    for basis, metrics in breakdown.items():
        verifiable = metrics["supported"] + metrics["unsupported"]
        metrics["score"] = (
            (metrics["supported"] / verifiable * 100) if verifiable > 0 else 0.0
        )

    return dict(breakdown)


def extract_claims_with_references(
    new_text: str, previous_claims: List[LLMClaim], claim_id_offset: int = 0
) -> Tuple[List[LLMClaim], float]:
    """
    Extract claims from new text and identify references to previous claims.

    Args:
        new_text: The text to extract claims from (e.g., peer reviews or responses)
        previous_claims: List of previously extracted claims to reference
        claim_id_offset: Starting ID offset for the previous claims

    Returns:
        Tuple of (list of new claims with references, processing time in seconds)

    Raises:
        ValueError: If text is too long or LLM returns invalid response
    """
    # Check token count
    print("counting tokens")
    token_count = count_tokens(new_text)
    if token_count > settings.max_tokens:
        raise ValueError(
            f"Document exceeds maximum length of {settings.max_tokens} tokens "
            f"(estimated {token_count} tokens)"
        )

    start_time = time.time()
    print("initializing anthropic")
    # Initialize Anthropic client
    client = Anthropic(api_key=settings.llm_api_key)
    print("adding ids to claims")
    # Format previous claims as a structured list with explicit IDs for the LLM
    previous_claims_list = []
    for i, claim in enumerate(previous_claims):
        claim_id = claim_id_offset + i + 1
        previous_claims_list.append({"claim_id": claim_id, "claim": claim.claim})

    previous_claims_text = json.dumps(previous_claims_list, indent=2)
    print("formatting prompt")
    # Prepare the prompt - use replace to avoid issues with curly braces in text
    full_prompt = CLAIM_EXTRACTION_WITH_REFERENCES_PROMPT.replace(
        "{previous_claims}", previous_claims_text
    ).replace("{new_text}", new_text)
    print("Prompt length:", len(full_prompt))
    # Call the LLM with extended timeout and retry logic
    max_retries = 3
    retry_delay = 2  # seconds

    for attempt in range(max_retries):
        try:
            response = client.messages.create(
                model=settings.llm_model,
                max_tokens=32000,
                temperature=0,
                messages=[{"role": "user", "content": full_prompt}],
                timeout=600.0,  # 10 minute timeout
            )
            print("Response received")
            break  # Success, exit retry loop
        except APIError as e:
            if "overloaded" in str(e).lower() and attempt < max_retries - 1:
                print(f"API overloaded, retrying in {retry_delay} seconds... (attempt {attempt + 1}/{max_retries})")
                time.sleep(retry_delay)
                retry_delay *= 2  # Exponential backoff
                continue
            else:
                raise  # Re-raise if not overloaded or out of retries
    else:
        raise ValueError("Failed after maximum retries")

    # Extract the response text
    response_text = response.content[0].text
    print("Response text received, length:", len(response_text))

    # Parse JSON response
    try:
        # Remove markdown code fences if present
        if "```" in response_text:
            # Find content between code fences
            start_marker = response_text.find("```")
            if start_marker != -1:
                # Skip past the opening fence and optional "json" language identifier
                content_start = response_text.find("\n", start_marker) + 1
                # Find closing fence
                end_marker = response_text.find("```", content_start)
                if end_marker != -1:
                    response_text = response_text[content_start:end_marker].strip()

        # Try to extract JSON if there's extra text
        json_start = response_text.find("{")
        json_end = response_text.rfind("}") + 1
        if json_start != -1 and json_end > json_start:
            json_text = response_text[json_start:json_end]
        else:
            json_text = response_text

        response_data = json.loads(json_text)
        analysis = LLMAnalysisResponse(**response_data)
    except (json.JSONDecodeError, ValueError) as e:
        # Log the actual response for debugging
        print(f"Failed to parse LLM response. Error: {e}")
        print(f"Response text (first 500 chars): {response_text[:500]}")
        raise ValueError(
            f"LLM returned invalid JSON: {str(e)}. Response preview: {response_text[:200]}"
        )

    processing_time = time.time() - start_time

    if not analysis.claims:
        raise ValueError("LLM did not extract any claims from the document")

    return analysis.claims, processing_time
