"""
S3 index builder for bioRxiv papers.

The bioRxiv S3 bucket uses GUID filenames, not DOI-based names. This module provides
utilities to build and maintain a DOI→filename index by scanning .meca files.
"""

import json
import os
import zipfile
from io import BytesIO
from typing import Dict, List, Optional

import boto3
from botocore.config import Config
from lxml import etree

from app.services.s3_fetcher import BIORXIV_BUCKET, get_s3_client


def extract_doi_from_manifest(manifest_xml: str) -> Optional[str]:
    """
    Extract DOI from manifest.xml content.

    Args:
        manifest_xml: Content of manifest.xml

    Returns:
        DOI string or None if not found
    """
    try:
        root = etree.fromstring(manifest_xml.encode('utf-8'))
        # Look for doi element in manifest
        # Manifest structure: <manifest><item><doi>10.1101/xxx</doi></item></manifest>
        doi_elem = root.find('.//doi')
        if doi_elem is not None and doi_elem.text:
            return doi_elem.text.strip()
        return None
    except Exception as e:
        print(f"Error parsing manifest: {e}")
        return None


def build_month_index(year: int, month_name: str, max_files: Optional[int] = None) -> Dict[str, str]:
    """
    Build DOI→filename index for a given month by scanning .meca files.

    WARNING: This downloads all .meca files in the month folder. For a typical month
    with ~4000 papers at ~20MB each, this is ~80GB of data transfer (~$7.20 at $0.09/GB).

    Args:
        year: Year (e.g., 2024)
        month_name: Month name (e.g., "January")
        max_files: Optional limit on number of files to process (for testing)

    Returns:
        Dictionary mapping DOI to S3 filename (GUID.meca)
    """
    s3_client = get_s3_client()
    folder = f"Current_Content/{month_name}_{year}/"

    print(f"Building index for {folder}...")
    print("WARNING: This will download all .meca files in the folder!")

    # List all .meca files in folder
    try:
        response = s3_client.list_objects_v2(
            Bucket=BIORXIV_BUCKET,
            Prefix=folder,
            RequestPayer='requester'
        )
    except Exception as e:
        raise ValueError(f"Failed to list S3 bucket contents: {str(e)}")

    if 'Contents' not in response:
        return {}

    files = [obj['Key'] for obj in response['Contents'] if obj['Key'].endswith('.meca')]

    if max_files:
        files = files[:max_files]

    print(f"Found {len(files)} .meca files to process")

    index = {}
    for i, s3_key in enumerate(files, 1):
        filename = os.path.basename(s3_key)
        print(f"Processing {i}/{len(files)}: {filename}", end='\r')

        try:
            # Download .meca file
            response = s3_client.get_object(
                Bucket=BIORXIV_BUCKET,
                Key=s3_key,
                RequestPayer='requester'
            )
            meca_content = BytesIO(response['Body'].read())

            # Extract manifest.xml
            with zipfile.ZipFile(meca_content, 'r') as zip_ref:
                try:
                    manifest_xml = zip_ref.read('manifest.xml').decode('utf-8')
                    doi = extract_doi_from_manifest(manifest_xml)
                    if doi:
                        index[doi] = filename
                except KeyError:
                    # No manifest.xml in this archive
                    pass

        except Exception as e:
            print(f"\nError processing {filename}: {e}")
            continue

    print(f"\nIndexed {len(index)} papers")
    return index


def save_index(index: Dict[str, str], filepath: str):
    """Save index to JSON file."""
    with open(filepath, 'w') as f:
        json.dump(index, f, indent=2)


def load_index(filepath: str) -> Dict[str, str]:
    """Load index from JSON file."""
    if not os.path.exists(filepath):
        return {}
    with open(filepath, 'r') as f:
        return json.load(f)


def get_default_index_path() -> str:
    """Get default path for index file."""
    return os.path.join(os.path.dirname(__file__), '../../data/biorxiv_index.json')


def lookup_filename_in_index(doi: str, index_path: Optional[str] = None) -> Optional[str]:
    """
    Look up filename for DOI in local index.

    Args:
        doi: DOI like "10.1101/2023.12.11.571168"
        index_path: Path to index file (defaults to standard location)

    Returns:
        Filename (GUID.meca) or None if not found
    """
    if index_path is None:
        index_path = get_default_index_path()

    index = load_index(index_path)
    return index.get(doi)
