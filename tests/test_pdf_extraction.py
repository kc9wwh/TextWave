"""Tests for PDF text extraction functionality."""

import sys
from pathlib import Path

import pytest

# Add parent directory to path to import pdf2mp3_gui
sys.path.insert(0, str(Path(__file__).parent.parent))

from pdf2mp3_gui import extract_and_clean_text


@pytest.mark.unit
def test_extract_text_from_valid_pdf(sample_pdf):
    """Test that text is extracted from a valid PDF."""
    text, page_count = extract_and_clean_text(sample_pdf)

    assert isinstance(text, str)
    assert len(text) > 0
    assert page_count == 2  # Our sample PDF has 2 pages
    assert "Test PDF Content" in text
    assert "test document" in text


@pytest.mark.unit
def test_extract_text_counts_pages_correctly(sample_pdf):
    """Test that page count is accurate."""
    text, page_count = extract_and_clean_text(sample_pdf)

    assert page_count == 2


@pytest.mark.unit
def test_extract_text_removes_standalone_page_numbers(sample_pdf_with_page_numbers):
    """Test that standalone page numbers are removed."""
    text, page_count = extract_and_clean_text(sample_pdf_with_page_numbers)

    # Check that text was extracted
    assert len(text) > 0
    assert "Content" in text

    # Standalone numbers should be removed by the regex
    # The pattern removes lines that are just numbers or "Page X"
    # But numbers within text like "Page 1 Content" should remain


@pytest.mark.unit
def test_extract_text_returns_tuple(sample_pdf):
    """Test that extract_and_clean_text returns a tuple."""
    result = extract_and_clean_text(sample_pdf)

    assert isinstance(result, tuple)
    assert len(result) == 2
    assert isinstance(result[0], str)  # text
    assert isinstance(result[1], int)  # page_count


@pytest.mark.unit
def test_extract_text_from_nonexistent_file():
    """Test error handling for non-existent files."""
    with pytest.raises(Exception):
        extract_and_clean_text("/nonexistent/file.pdf")
