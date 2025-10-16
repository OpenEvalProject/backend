import hashlib
import re


def extract_title_from_text(text: str) -> str:
    """
    Extract a title from the document text.

    Looks for common patterns:
    - "Title: ..." at the beginning
    - First non-empty line if it's reasonably short
    - First line that looks like a title

    Args:
        text: The full document text

    Returns:
        Extracted title or a default title
    """
    lines = [line.strip() for line in text.split('\n') if line.strip()]

    if not lines:
        return "Untitled Document"

    # Look for explicit "Title:" pattern
    for line in lines[:10]:  # Check first 10 lines
        if re.match(r'^Title:\s*(.+)', line, re.IGNORECASE):
            title = re.sub(r'^Title:\s*', '', line, flags=re.IGNORECASE)
            return title.strip()

    # Use first line if it's reasonably short (likely a title)
    first_line = lines[0]
    if len(first_line) < 200:  # Titles are typically short
        # Clean up common formatting
        title = first_line.strip('*#-_=')
        title = title.strip()
        if title:
            return title

    # Look for the first line that looks like a title
    # (short, no punctuation at the end, not all caps unless reasonable)
    for line in lines[:5]:
        if (len(line) < 200 and
            not line.endswith(('.', '!', '?', ',', ';', ':')) and
            (not line.isupper() or len(line) < 50)):
            return line.strip()

    # Fallback to first line truncated
    return lines[0][:100] + ("..." if len(lines[0]) > 100 else "")



def compute_content_hash(text: str) -> str:
    """
    Compute SHA256 hash of document text for duplicate detection.

    Args:
        text: The full document text

    Returns:
        SHA256 hash as hexadecimal string
    """
    # Normalize whitespace to handle minor formatting differences
    normalized = " ".join(text.split())

    # Compute SHA256 hash
    hash_obj = hashlib.sha256(normalized.encode("utf-8"))
    return hash_obj.hexdigest()

