"""
JATS XML parser for scientific articles.

Parses JATS (Journal Article Tag Suite) XML format and converts to markdown,
including author affiliations with ROR links, inline citation links,
figure reference links, and ORCID IDs.

This module uses the jats library for parsing JATS XML files.
"""

from pathlib import Path
from typing import Optional

from jats import convert_to_markdown, parse_jats_xml as jats_parse_jats_xml


def parse_jats_xml(xml_path: str, manifest_path: Optional[str] = None) -> str:
    """
    Parse JATS XML file and convert to markdown.

    Args:
        xml_path: Path to XML file
        manifest_path: Optional path to manifest.xml for resolving figure paths.

    Returns:
        Markdown formatted text with:
        - ROR links for affiliations
        - Inline citation links to DOIs
        - Figure reference links to image URLs
        - ORCID links for authors
    """
    xml_path_obj = Path(xml_path)
    manifest_path_obj = Path(manifest_path) if manifest_path else None

    # Parse using jats library
    article = jats_parse_jats_xml(xml_path_obj, manifest_path=manifest_path_obj)

    # Convert to markdown
    markdown = convert_to_markdown(article)

    return markdown


def parse_jats_xml_string(xml_string: str, manifest_path: Optional[str] = None) -> str:
    """
    Parse JATS XML string and convert to markdown.

    Args:
        xml_string: XML content as string
        manifest_path: Optional path to manifest.xml for resolving figure paths

    Returns:
        Markdown formatted text
    """
    # For string input, we need to write to a temp file first
    import tempfile
    with tempfile.NamedTemporaryFile(mode='w', suffix='.xml', delete=False) as f:
        f.write(xml_string)
        temp_path = f.name
    
    try:
        result = parse_jats_xml(temp_path, manifest_path)
        return result
    finally:
        import os
        os.unlink(temp_path)
