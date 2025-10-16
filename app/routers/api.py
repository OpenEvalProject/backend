from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status

from app.database import get_db
from app.dependencies import get_current_user
from app.models import (
    AnalyzeResponse,
    ErrorResponse,
    PaperResponse,
    PapersListResponse,
    PaperSummary,
    PaperResponseV3,
    ClaimV3,
    ResultV3,
    ResultsConcordance,
)
from app.services.pdf_extractor import extract_text_from_pdf, extract_text_from_txt
from app.services.text_utils import compute_content_hash, extract_title_from_text
from app.services.verification_v3 import (
    extract_claims,
    llm_group_claims_into_results,
    peer_review_group_claims_into_results,
    compare_results,
    calculate_results_metrics,
)
from app.services.db_helpers_v3 import (
    save_claims_v3,
    save_results_v3,
    save_results_concordance,
    get_paper_with_v3_analysis,
)

router = APIRouter(prefix="/api", tags=["api"])


@router.get("/papers", response_model=PapersListResponse)
async def list_papers():
    """List all processed papers with summary metrics"""
    with get_db() as conn:
        cursor = conn.cursor()

        query = """
            SELECT
                p.id,
                p.title,
                p.source_type,
                p.source_reference,
                p.processed_at,
                u.name as submitted_by,
                a.total_claims,
                a.supported_count,
                a.unsupported_count,
                a.uncertain_count,
                a.verification_score
            FROM papers p
            JOIN users u ON p.user_id = u.id
            JOIN analysis_summary a ON p.id = a.paper_id
            ORDER BY p.processed_at DESC
        """

        cursor.execute(query)
        results = cursor.fetchall()

        papers = [
            PaperSummary(
                id=row["id"],
                title=row["title"],
                source_type=row["source_type"],
                source_reference=row["source_reference"],
                verification_score=row["verification_score"],
                total_claims=row["total_claims"],
                supported_count=row["supported_count"],
                unsupported_count=row["unsupported_count"],
                uncertain_count=row["uncertain_count"],
                processed_at=row["processed_at"],
                submitted_by=row["submitted_by"],
            )
            for row in results
        ]

        return PapersListResponse(papers=papers, total_count=len(papers))


@router.get("/papers/{paper_id}", response_model=PaperResponseV3)
async def get_paper(paper_id: int):
    """Get detailed V3 analysis for a specific paper"""
    with get_db() as conn:
        paper_response = get_paper_with_v3_analysis(conn, paper_id)

        if not paper_response:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Paper not found"
            )

        return paper_response


@router.post("/analyze", response_model=AnalyzeResponse)
async def analyze_paper(
    user: dict = Depends(get_current_user),
    manuscript_file: UploadFile = File(...),
    reviews_file: UploadFile = File(...),  # Now required
    title: Optional[str] = Form(None),
):
    """
    Analyze a paper for claim verification with V3 results-based workflow.
    Accepts:
    - manuscript_file: Required manuscript file (.txt or .pdf)
    - reviews_file: Required peer review file (.txt or .pdf)
    - title: Optional paper title
    """
    import json as json_lib

    user_id = user["user_id"]

    from app.config import settings

    max_size = settings.max_file_size_mb * 1024 * 1024

    # Helper function to extract text from uploaded file
    async def extract_text_from_upload(file: UploadFile) -> str:
        from io import BytesIO

        contents = await file.read()
        if len(contents) > max_size:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=f"File {file.filename} exceeds maximum of {settings.max_file_size_mb}MB",
            )

        # Create a BytesIO object from the contents for PDF/TXT extraction
        file_bytes = BytesIO(contents)

        if file.filename.endswith(".pdf"):
            try:
                return extract_text_from_pdf(file_bytes)
            except ValueError as e:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=f"Error extracting PDF {file.filename}: {str(e)}",
                )
        elif file.filename.endswith(".txt"):
            try:
                return extract_text_from_txt(file_bytes)
            except ValueError as e:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=f"Error extracting TXT {file.filename}: {str(e)}",
                )
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"File {file.filename} must be .txt or .pdf",
            )

    # Extract manuscript text
    manuscript_text = await extract_text_from_upload(manuscript_file)

    # Extract reviews text
    reviews_text = await extract_text_from_upload(reviews_file)

    # Extract title from document if not provided
    paper_title = title if title else extract_title_from_text(manuscript_text)

    source_type = "file_upload"
    source_reference = manuscript_file.filename

    # Check for duplicate content using hash
    content_hash = compute_content_hash(manuscript_text)

    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM papers WHERE content_hash = ?", (content_hash,))
        existing_paper = cursor.fetchone()

        if existing_paper:
            # Paper already exists, return existing analysis
            existing_paper_id = existing_paper["id"]
            return AnalyzeResponse(
                status="success",
                paper_id=existing_paper_id,
                message="This paper has already been analyzed. Redirecting to existing results.",
                redirect_url=f"/paper.html?id={existing_paper_id}",
            )

    # ========================================================================
    # V3 4-STAGE WORKFLOW - Results-based approach
    # ========================================================================

    total_processing_time = 0.0

    # STAGE 1: Extract claims from manuscript
    try:
        print("Stage 1: Extracting atomic factual claims...")
        llm_claims, stage1_time = extract_claims(manuscript_text)
        total_processing_time += stage1_time
        print(f"Extracted {len(llm_claims)} claims in {stage1_time:.2f}s")
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Stage 1 (Claim Extraction): {str(e)}",
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Stage 1 error: {str(e)}",
        )

    # STAGE 2: LLM groups claims into results
    try:
        print("Stage 2: LLM grouping claims into results...")
        llm_results, stage2_time = llm_group_claims_into_results(
            manuscript_text,
            llm_claims
        )
        total_processing_time += stage2_time
        print(f"LLM created {len(llm_results)} results in {stage2_time:.2f}s")
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Stage 2 (LLM Result Grouping): {str(e)}",
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Stage 2 error: {str(e)}",
        )

    # STAGE 3: Peer review groups claims into results
    try:
        print("Stage 3: Peer review grouping claims into results...")
        peer_results, stage3_time = peer_review_group_claims_into_results(
            llm_claims,
            reviews_text
        )
        total_processing_time += stage3_time
        print(f"Peer review created {len(peer_results)} results in {stage3_time:.2f}s")
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Stage 3 (Peer Review Result Grouping): {str(e)}",
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Stage 3 error: {str(e)}",
        )

    # STAGE 4: Compare results between LLM and peer review
    try:
        print("Stage 4: Comparing results...")
        concordance_rows, stage4_time = compare_results(
            llm_results,
            peer_results
        )
        total_processing_time += stage4_time
        print(f"Created {len(concordance_rows)} concordance comparisons in {stage4_time:.2f}s")
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Stage 4 (Results Comparison): {str(e)}",
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Stage 4 error: {str(e)}",
        )

    # ========================================================================
    # CALCULATE METRICS
    # ========================================================================

    # Calculate metrics from V3 workflow
    metrics = calculate_results_metrics(llm_results, peer_results, concordance_rows)

    # Use agreement rate as verification score
    verification_score = metrics["agreement_rate"]

    # Count status from LLM results for summary
    supported_count = sum(1 for result in llm_results if result.status == "SUPPORTED")
    unsupported_count = sum(1 for result in llm_results if result.status == "UNSUPPORTED")
    uncertain_count = sum(1 for result in llm_results if result.status == "UNCERTAIN")

    # ========================================================================
    # SAVE TO DATABASE
    # ========================================================================

    with get_db() as conn:
        cursor = conn.cursor()

        # Insert paper
        cursor.execute(
            """
            INSERT INTO papers (user_id, title, source_type, source_reference, full_text, content_hash, document_length, processed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user_id,
                paper_title,
                source_type,
                source_reference,
                manuscript_text,
                content_hash,
                len(manuscript_text),
                datetime.utcnow(),
            ),
        )
        paper_id = cursor.lastrowid

        # Save claims and get database IDs
        claims_to_save = [
            ClaimV3(
                claim_id=claim.claim_id,
                claim=claim.claim,
                claim_type=claim.claim_type,
                source_text=claim.source_text,
                evidence_type=claim.evidence_type,
                evidence_reasoning=claim.evidence_reasoning
            )
            for claim in llm_claims
        ]
        claim_db_ids = save_claims_v3(conn, paper_id, claims_to_save)

        # Add database IDs to claims
        for claim, db_id in zip(claims_to_save, claim_db_ids):
            claim.id = db_id

        # Save LLM results
        llm_results_to_save = [
            ResultV3(
                claim_ids=result.claim_ids,
                status=result.status,
                status_reasoning=result.status_reasoning
            )
            for result in llm_results
        ]
        llm_result_db_ids = save_results_v3(conn, paper_id, llm_results_to_save, source="LLM")

        # Save peer review results
        peer_results_to_save = [
            ResultV3(
                claim_ids=result.claim_ids,
                status=result.status,
                status_reasoning=result.status_reasoning
            )
            for result in peer_results
        ]
        peer_result_db_ids = save_results_v3(conn, paper_id, peer_results_to_save, source="PEER_REVIEW")

        # Save concordance (with database IDs for results)
        concordance_to_save = []
        for i, row in enumerate(concordance_rows):
            # Try to find matching result IDs based on claim_ids
            # This is a simplified approach - may need refinement
            llm_result_id = llm_result_db_ids[i] if i < len(llm_result_db_ids) else None
            peer_result_id = peer_result_db_ids[i] if i < len(peer_result_db_ids) else None

            concordance = ResultsConcordance(
                llm_result_id=llm_result_id,
                peer_result_id=peer_result_id,
                llm_claim_ids=row.llm_claim_ids,
                peer_claim_ids=row.peer_claim_ids,
                llm_status=row.llm_status,
                peer_status=row.peer_status,
                agreement_status=row.agreement_status,
                notes=row.notes
            )
            concordance_to_save.append(concordance)

        save_results_concordance(conn, paper_id, concordance_to_save)

        # Insert analysis summary
        cursor.execute(
            """
            INSERT INTO analysis_summary
            (paper_id, total_claims, supported_count, unsupported_count, uncertain_count, verification_score, processing_time_seconds)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                paper_id,
                len(claims_to_save),
                supported_count,
                unsupported_count,
                uncertain_count,
                verification_score,
                total_processing_time,
            ),
        )

        conn.commit()

    print(f"Total processing time: {total_processing_time:.2f}s")
    print(f"Verification score (agreement rate): {verification_score:.2f}%")

    return AnalyzeResponse(
        status="success",
        paper_id=paper_id,
        message="Paper analyzed successfully",
        redirect_url=f"/paper.html?id={paper_id}",
    )
