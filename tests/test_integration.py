"""Integration tests for TextWave."""

import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from pdf2mp3_gui import ConversionThread, PDF2MP3App


@pytest.mark.integration
def test_caffeinate_starts_and_stops(qtbot, tmp_path):
    """Test that caffeinate subprocess starts and stops correctly."""
    pdf_path = str(tmp_path / "test.pdf")
    output_path = str(tmp_path / "output.mp3")

    thread = ConversionThread(pdf_path, output_path)
    with patch("subprocess.Popen") as mock_popen:
        mock_process = MagicMock()
        mock_popen.return_value = mock_process

        # Mock PDF extraction and TTS to avoid actual processing
        with patch("pdf2mp3_gui.extract_and_clean_text", return_value=("test text", 1)):
            with patch("asyncio.run"):
                thread.run()

        # Verify caffeinate was started with correct args
        mock_popen.assert_called_once_with(
            ["caffeinate", "-di"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )

        # Verify caffeinate was stopped
        mock_process.terminate.assert_called_once()


@pytest.mark.integration
def test_caffeinate_cleanup_on_error(qtbot, tmp_path):
    """Test that caffeinate is stopped even if conversion fails."""
    pdf_path = str(tmp_path / "test.pdf")
    output_path = str(tmp_path / "output.mp3")

    thread = ConversionThread(pdf_path, output_path)

    with patch("subprocess.Popen") as mock_popen:
        mock_process = MagicMock()
        mock_popen.return_value = mock_process

        # Mock extraction to raise an error
        with patch(
            "pdf2mp3_gui.extract_and_clean_text", side_effect=Exception("Test error")
        ):
            thread.run()

        # Verify caffeinate was still stopped despite error
        mock_process.terminate.assert_called_once()


@pytest.mark.integration
@pytest.mark.gui
def test_app_close_cleans_up_threads(qtbot, qapp):
    """Test that closeEvent is implemented and handles cleanup."""
    from PyQt6.QtGui import QCloseEvent
    
    # Patch thread creation to avoid real network calls
    with patch('pdf2mp3_gui.VersionCheckThread'):
        with patch('pdf2mp3_gui.AppUpdateCheckThread'):
            window = PDF2MP3App()
            qtbot.addWidget(window)
            
            # Verify closeEvent method exists
            assert hasattr(window, 'closeEvent')
            
            # Create and trigger close event
            event = QCloseEvent()
            window.closeEvent(event)
            
            # Event should be accepted
            assert event.isAccepted()


@pytest.mark.integration
def test_conversion_thread_emits_signals(qtbot, tmp_path):
    """Test that conversion thread emits proper signals."""
    pdf_path = str(tmp_path / "test.pdf")
    output_path = str(tmp_path / "output.mp3")

    thread = ConversionThread(pdf_path, output_path)

    # Track emitted signals
    status_messages = []

    def capture_status(msg):
        status_messages.append(msg)

    thread.status.connect(capture_status)

    with patch("subprocess.Popen", return_value=MagicMock()):
        with patch("pdf2mp3_gui.extract_and_clean_text", return_value=("test text", 1)):
            with patch("asyncio.run"):
                with qtbot.waitSignal(thread.finished, timeout=3000):
                    thread.start()

    # Verify status messages were emitted
    assert len(status_messages) > 0
    assert any("Extracting" in msg for msg in status_messages)
