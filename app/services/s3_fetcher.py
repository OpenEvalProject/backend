"""
AWS S3 service for fetching bioRxiv articles.

Downloads .meca files from bioRxiv's requester-pays S3 bucket and extracts content.
"""

import os
import zipfile
from datetime import datetime
from io import BytesIO
from typing import Tuple

import boto3
import requests
from botocore.config import Config


# bioRxiv S3 bucket configuration
BIORXIV_BUCKET = "biorxiv-src-monthly"


def get_s3_client():
    """
    Create S3 client with requester-pays configuration.

    Returns:
        boto3 S3 client
    """
    config = Config(
        signature_version='s3v4',
        s3={'addressing_style': 'path'}
    )
    return boto3.client('s3', config=config)


def get_paper_metadata_from_api(doi: str) -> dict:
    """
    Get paper metadata from bioRxiv API.

    Args:
        doi: DOI like "10.1101/2023.12.11.571168"

    Returns:
        Dictionary with metadata including 'date' field

    Raises:
        ValueError: If API call fails or paper not found
    """
    api_url = f"https://api.biorxiv.org/details/biorxiv/{doi}"

    try:
        response = requests.get(api_url, timeout=10)
        response.raise_for_status()
        data = response.json()

        if data.get("messages", [{}])[0].get("status") == "ok" and data.get("collection"):
            # Get the latest version
            latest = data["collection"][-1]
            return latest
        else:
            raise ValueError(f"Paper not found in bioRxiv API: {doi}")

    except requests.exceptions.RequestException as e:
        raise ValueError(f"Failed to fetch paper metadata from bioRxiv API: {str(e)}")


def construct_s3_path_from_date(doi: str, date_str: str) -> str:
    """
    Construct S3 path based on paper date.

    Papers from December 2018 onward are in Current_Content/Month_Year/ folders.

    Args:
        doi: DOI like "10.1101/2023.12.11.571168"
        date_str: Date string from API (YYYY-MM-DD format)

    Returns:
        S3 key path like "Current_Content/December_2023/10.1101_2023.12.11.571168.meca"

    Raises:
        ValueError: If date is before December 2018 (not in monthly folders)
    """
    # Parse date
    date = datetime.strptime(date_str, "%Y-%m-%d")

    # Check if date is December 2018 or later
    cutoff_date = datetime(2018, 12, 1)
    if date < cutoff_date:
        raise ValueError(
            f"Paper date {date_str} is before December 2018. "
            "Papers before this date are in Back_Content batches with GUID filenames."
        )

    # Construct folder name: Month_Year (e.g., "December_2023")
    month_name = date.strftime("%B")  # Full month name
    year = date.strftime("%Y")
    folder = f"{month_name}_{year}"

    # Construct filename: DOI with / replaced by _
    filename = doi.replace('/', '_') + '.meca'

    # Full S3 path
    s3_path = f"Current_Content/{folder}/{filename}"

    return s3_path


def find_meca_file(s3_client, doi: str) -> str:
    """
    Find .meca file in S3 bucket using API metadata to construct path.

    Args:
        s3_client: boto3 S3 client
        doi: DOI like "10.1101/2023.12.11.571168"

    Returns:
        Full S3 key path to .meca file

    Raises:
        ValueError: If file not found or paper date is before December 2018
    """
    # Get paper metadata from API to get the date
    metadata = get_paper_metadata_from_api(doi)
    date_str = metadata.get('date')

    if not date_str:
        raise ValueError(f"No date found in API metadata for DOI {doi}")

    # Construct S3 path based on date
    s3_path = construct_s3_path_from_date(doi, date_str)

    # Verify file exists
    try:
        s3_client.head_object(
            Bucket=BIORXIV_BUCKET,
            Key=s3_path,
            RequestPayer='requester'
        )
        return s3_path
    except s3_client.exceptions.ClientError as e:
        error_code = e.response.get('Error', {}).get('Code', '')
        if error_code == '404':
            raise ValueError(
                f"File not found at expected path: {s3_path}. "
                f"The file may have a different naming convention or be in a batch folder."
            )
        raise ValueError(f"Error accessing S3 file {s3_path}: {str(e)}")


def download_meca_file(doi: str) -> BytesIO:
    """
    Download .meca file from S3 bucket.

    Args:
        doi: DOI like "10.1101/2023.12.11.571168"

    Returns:
        BytesIO buffer with .meca file contents

    Raises:
        ValueError: If download fails
    """
    s3_client = get_s3_client()

    # Find the file
    s3_key = find_meca_file(s3_client, doi)

    # Download with requester-pays
    try:
        response = s3_client.get_object(
            Bucket=BIORXIV_BUCKET,
            Key=s3_key,
            RequestPayer='requester'
        )
        return BytesIO(response['Body'].read())
    except Exception as e:
        raise ValueError(f"Failed to download .meca file from S3: {str(e)}")


def extract_xml_from_meca(meca_buffer: BytesIO) -> str:
    """
    Extract XML content from .meca file.

    .meca files are ZIP archives containing XML and other files.

    Args:
        meca_buffer: BytesIO buffer with .meca file contents

    Returns:
        XML content as string

    Raises:
        ValueError: If extraction fails
    """
    try:
        with zipfile.ZipFile(meca_buffer, 'r') as zip_ref:
            # Find XML file in archive (usually in content/ folder)
            xml_files = [f for f in zip_ref.namelist() if f.endswith('.xml') and 'content/' in f]

            if not xml_files:
                # Fallback: find any XML file
                xml_files = [f for f in zip_ref.namelist() if f.endswith('.xml')]

            if not xml_files:
                raise ValueError("No XML file found in .meca archive")

            # Read the first XML file
            xml_content = zip_ref.read(xml_files[0])
            return xml_content.decode('utf-8')

    except zipfile.BadZipFile:
        raise ValueError(".meca file is not a valid ZIP archive")
    except Exception as e:
        raise ValueError(f"Failed to extract XML from .meca file: {str(e)}")


def fetch_biorxiv_from_s3(doi: str) -> Tuple[str, str]:
    """
    Fetch bioRxiv article from S3 and parse to markdown.

    IMPORTANT LIMITATION: The bioRxiv S3 bucket uses GUID filenames (not DOI-based names).
    This function currently raises an error explaining the limitation.

    For bulk processing, you should:
    1. Use app.services.s3_index.build_month_index() to create a DOI→filename mapping
    2. Store the index locally
    3. Use the index to look up filenames before calling this function

    For individual papers, fall back to manual download instructions.

    Args:
        doi: DOI like "10.1101/2023.12.11.571168"

    Returns:
        Tuple of (markdown_text, source_reference)

    Raises:
        ValueError: Always raises with explanation of limitation
    """
    # Check if we have a local index
    from app.services.s3_index import lookup_filename_in_index

    filename = lookup_filename_in_index(doi)
    if filename:
        # We have the filename in our index
        # Import here to avoid circular dependency
        from app.services.jats_parser import parse_jats_xml_string

        # Download .meca file using the known filename
        # Need to still determine which month folder it's in...
        # This would require storing month info in the index
        raise ValueError(
            "Index-based S3 fetch not yet implemented. "
            "The bioRxiv S3 bucket uses GUID filenames that require an index to map DOIs."
        )

    # No index available - explain limitation
    raise ValueError(
        "Cannot fetch from S3: bioRxiv S3 bucket uses GUID filenames, not DOI-based names. "
        "To enable S3 fetching, you must first build an index by scanning .meca files. "
        "See app.services.s3_index.build_month_index() for details. "
        "For individual papers, use manual download instead."
    )
