from io import BytesIO
from typing import BinaryIO

from pypdf import PdfReader


def extract_text_from_pdf(file: BinaryIO) -> str:
    """
    Extract text from a PDF file.

    Args:
        file: File-like object containing PDF data

    Returns:
        Extracted text from all pages
    """
    try:
        reader = PdfReader(file)

        text_parts = []
        for page in reader.pages:
            text = page.extract_text()
            if text:
                text_parts.append(text)

        full_text = "\n\n".join(text_parts)

        if not full_text.strip():
            raise ValueError("No text could be extracted from the PDF")

        return full_text

    except Exception as e:
        raise ValueError(f"Error extracting text from PDF: {str(e)}")


def extract_text_from_txt(file: BinaryIO) -> str:
    """
    Extract text from a .txt file.

    Args:
        file: File-like object containing text data

    Returns:
        File contents as string
    """
    try:
        content = file.read()

        # Try to decode as UTF-8
        if isinstance(content, bytes):
            text = content.decode("utf-8")
        else:
            text = content

        if not text.strip():
            raise ValueError("File is empty")

        return text

    except UnicodeDecodeError:
        raise ValueError("File encoding is not UTF-8")
    except Exception as e:
        raise ValueError(f"Error reading text file: {str(e)}")
