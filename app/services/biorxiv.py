import re
from typing import Dict, Tuple

import requests
from pypdf import PdfReader


def parse_biorxiv_url(url: str) -> Tuple[str, str]:
    """
    Parse bioRxiv URL and extract DOI and version.

    Args:
        url: bioRxiv URL like https://www.biorxiv.org/content/10.1101/2024.01.01.123456v1

    Returns:
        Tuple of (doi, version)
    """
    pattern = r"biorxiv\.org/content/(10\.\d+/\d+\.\d+\.\d+\.\d+)(v\d+)?"
    match = re.search(pattern, url)

    if not match:
        raise ValueError("Invalid bioRxiv URL format")

    doi = match.group(1)
    version = match.group(2) or "v1"

    return doi, version


def get_pdf_url(doi: str, version: str) -> str:
    """Get PDF URL from DOI and version"""
    # Remove 'v' from version
    version_num = version.replace("v", "")
    return f"https://www.biorxiv.org/content/{doi}{version}.full.pdf"


def fetch_biorxiv_paper(url: str) -> Tuple[str, str]:
    """
    Fetch and extract text from a bioRxiv paper using AWS S3.

    Args:
        url: bioRxiv paper URL

    Returns:
        Tuple of (full_text, source_reference)
    """
    from app.services.s3_fetcher import fetch_biorxiv_from_s3

    # Parse URL to get DOI
    doi, version = parse_biorxiv_url(url)

    # Fetch from S3 and parse XML to markdown
    try:
        markdown_text, source_reference = fetch_biorxiv_from_s3(doi)
        return markdown_text, source_reference
    except ValueError as e:
        # If S3 fetch fails, provide helpful error
        raise ValueError(
            f"Unable to fetch paper from bioRxiv S3: {str(e)}. "
            "Please download the PDF manually and upload it using the file upload option."
        )


def get_biorxiv_metadata(doi: str) -> Dict:
    """
    Get paper metadata from bioRxiv API.
    
    Args:
        doi: The DOI (e.g., "10.1101/2023.12.11.571168")
    
    Returns:
        Dictionary with paper metadata
    """
    api_url = f"https://api.biorxiv.org/details/biorxiv/{doi}"
    
    try:
        response = requests.get(api_url, timeout=10)
        response.raise_for_status()
        data = response.json()
        
        if data.get("messages", [{}])[0].get("status") == "ok" and data.get("collection"):
            # Get the latest version
            latest = data["collection"][-1]
            return {
                "title": latest.get("title"),
                "authors": latest.get("authors"),
                "abstract": latest.get("abstract"),
                "doi": latest.get("doi"),
                "date": latest.get("date"),
                "version": latest.get("version"),
                "category": latest.get("category"),
            }
        else:
            raise ValueError("Paper not found in bioRxiv")
            
    except requests.exceptions.RequestException as e:
        raise ValueError(f"Failed to fetch paper metadata from bioRxiv API: {str(e)}")


def validate_and_get_paper_info(url: str) -> Tuple[Dict, str]:
    """
    Validate bioRxiv URL and get paper metadata.
    
    Args:
        url: bioRxiv paper URL
    
    Returns:
        Tuple of (metadata dict, download instructions)
    """
    # Parse URL to get DOI
    doi, version = parse_biorxiv_url(url)
    
    # Get metadata from API
    metadata = get_biorxiv_metadata(doi)
    
    # Generate PDF download URL
    pdf_url = get_pdf_url(doi, f"v{version}" if not version.startswith('v') else version)
    
    # Create instructions
    instructions = (
        f"To analyze this paper, please:\n\n"
        f"1. Download the PDF from: {pdf_url}\n"
        f"2. Go back to the submission page\n"
        f"3. Switch to 'Upload File' tab\n"
        f"4. Upload the downloaded PDF\n\n"
        f"(bioRxiv blocks automated downloads due to bot protection)"
    )
    
    return metadata, instructions
