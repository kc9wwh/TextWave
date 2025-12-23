"""Pytest configuration and fixtures for TextWave tests."""

import sys
from pathlib import Path

import pytest
from PyQt6.QtWidgets import QApplication
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas


@pytest.fixture(scope="session")
def qapp():
    """Create QApplication for GUI tests."""
    # Check if QApplication already exists
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    yield app


@pytest.fixture
def sample_pdf(tmp_path):
    """Create a sample PDF for testing."""
    pdf_path = tmp_path / "sample.pdf"

    # Create a simple PDF with reportlab
    c = canvas.Canvas(str(pdf_path), pagesize=letter)

    # Page 1
    c.drawString(100, 750, "Test PDF Content")
    c.drawString(100, 730, "This is a test document for TextWave.")
    c.drawString(100, 710, "It contains multiple lines of text.")
    c.drawString(300, 100, "1")  # Page number (should be removed)
    c.showPage()

    # Page 2
    c.drawString(100, 750, "Second Page")
    c.drawString(100, 730, "More content here.")
    c.drawString(300, 100, "2")  # Page number (should be removed)
    c.showPage()

    c.save()

    return str(pdf_path)


@pytest.fixture
def sample_pdf_with_page_numbers(tmp_path):
    """Create a PDF with obvious page numbers for testing removal."""
    pdf_path = tmp_path / "sample_numbered.pdf"

    c = canvas.Canvas(str(pdf_path), pagesize=letter)

    for i in range(1, 4):
        c.drawString(100, 750, f"Page {i} Content")
        c.drawString(100, 730, "Some text on this page.")
        # Page number in footer
        c.drawString(300, 50, str(i))
        # Page label
        c.drawString(50, 50, f"Page {i}")
        c.showPage()

    c.save()

    return str(pdf_path)
