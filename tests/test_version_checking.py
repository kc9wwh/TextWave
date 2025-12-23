"""Tests for edge-tts version checking functionality."""

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from pdf2mp3_gui import VersionCheckThread


@pytest.mark.unit
def test_version_check_finds_update(qtbot, qapp):
    """Test version check detects when an update is available."""
    thread = VersionCheckThread()

    with patch("urllib.request.urlopen") as mock_urlopen:
        with patch("subprocess.run") as mock_run:
            # Mock pip show output
            mock_run.return_value = MagicMock(
                returncode=0, stdout="Name: edge-tts\nVersion: 6.0.0\n"
            )

            # Mock PyPI response with newer version
            mock_response = MagicMock()
            mock_response.read.return_value = json.dumps(
                {"info": {"version": "99.0.0"}}
            ).encode()
            mock_urlopen.return_value.__enter__.return_value = mock_response

            with qtbot.waitSignal(thread.finished, timeout=3000) as blocker:
                thread.start()

            has_update, installed, latest = blocker.args
            assert has_update == True
            assert installed == "6.0.0"
            assert latest == "99.0.0"


@pytest.mark.unit
def test_version_check_no_update(qtbot, qapp):
    """Test version check when no update is available."""
    thread = VersionCheckThread()

    with patch("urllib.request.urlopen") as mock_urlopen:
        with patch("subprocess.run") as mock_run:
            # Mock pip show output
            mock_run.return_value = MagicMock(
                returncode=0, stdout="Name: edge-tts\nVersion: 6.1.0\n"
            )

            # Mock PyPI response with same version
            mock_response = MagicMock()
            mock_response.read.return_value = json.dumps(
                {"info": {"version": "6.1.0"}}
            ).encode()
            mock_urlopen.return_value.__enter__.return_value = mock_response

            with qtbot.waitSignal(thread.finished, timeout=3000) as blocker:
                thread.start()

            has_update, installed, latest = blocker.args
            assert has_update == False
            assert installed == "6.1.0"
            assert latest == "6.1.0"


@pytest.mark.unit
def test_version_check_handles_network_error(qtbot, qapp):
    """Test version check handles network errors gracefully."""
    thread = VersionCheckThread()

    with patch("urllib.request.urlopen") as mock_urlopen:
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0, stdout="Name: edge-tts\nVersion: 6.1.0\n"
            )

            # Simulate network error
            mock_urlopen.side_effect = Exception("Network error")

            with qtbot.waitSignal(thread.finished, timeout=3000) as blocker:
                thread.start()

            has_update, installed, latest = blocker.args
            # Should return False on error
            assert has_update == False
            assert installed == ""
            assert latest == ""


@pytest.mark.unit
def test_version_check_handles_pip_error(qtbot, qapp):
    """Test version check handles pip errors gracefully."""
    thread = VersionCheckThread()

    with patch("subprocess.run") as mock_run:
        # Mock pip failing
        mock_run.return_value = MagicMock(returncode=1)

        with qtbot.waitSignal(thread.finished, timeout=3000) as blocker:
            thread.start()

        has_update, installed, latest = blocker.args
        assert has_update == False
        assert installed == ""
        assert latest == ""
