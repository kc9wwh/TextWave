"""Tests for GUI components and interactions."""

import pytest
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))

from pdf2mp3_gui import PDF2MP3App, get_resource_path


@pytest.mark.gui
def test_main_window_creation(qtbot, qapp):
    """Test that main window initializes correctly."""
    window = PDF2MP3App()
    qtbot.addWidget(window)
    
    assert window.windowTitle() == "TextWave"
    assert window.convert_btn.isEnabled() == False
    assert window.select_btn.isEnabled() == True
    assert window.progress_bar.isVisible() == False


@pytest.mark.gui
def test_pdf_selection_enables_convert_button(qtbot, qapp, tmp_path):
    """Test that selecting a PDF enables the convert button."""
    window = PDF2MP3App()
    qtbot.addWidget(window)
    
    # Create a test PDF path
    pdf_path = str(tmp_path / "test.pdf")
    
    # Simulate PDF selection
    window.set_pdf(pdf_path)
    
    assert window.convert_btn.isEnabled() == True
    assert "test.pdf" in window.drop_label.text()


@pytest.mark.unit
def test_resource_path_resolution_dev(tmp_path):
    """Test resource path resolution returns Path or None."""
    # Test that the function exists and returns proper types
    result = get_resource_path("textwave_logo.png")
    # Should return Path if exists, None otherwise
    assert result is None or isinstance(result, Path)


@pytest.mark.unit
def test_resource_path_resolution_nonexistent():
    """Test resource path resolution for non-existent file."""
    result = get_resource_path("nonexistent_file.xyz")
    assert result is None


@pytest.mark.gui
def test_update_banner_dismissed(qtbot, qapp):
    """Test that update banner can be dismissed."""
    window = PDF2MP3App()
    qtbot.addWidget(window)
    
    # Set up mock update data
    window.installed_version = "1.0.0"
    window.latest_version = "2.0.0"
    window.update_banner = window.create_update_banner()
    
    # Dismiss the banner
    window.dismiss_update_banner()
    
    assert window.update_dismissed == True
    assert window.update_banner.isVisible() == False


@pytest.mark.gui
def test_app_update_banner_creation(qtbot, qapp):
    """Test that app update banner creates correctly."""
    window = PDF2MP3App()
    qtbot.addWidget(window)
    
    window.app_current_version = "1.0.0"
    window.app_latest_version = "2.0.0"
    
    banner = window.create_app_update_banner()
    
    # Verify banner was created and is a QWidget
    assert banner is not None
    from PyQt6.QtWidgets import QWidget
    assert isinstance(banner, QWidget)
