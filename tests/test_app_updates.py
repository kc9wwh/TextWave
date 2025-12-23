"""Tests for app update checking functionality."""

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from pdf2mp3_gui import AppUpdateCheckThread, __version__


@pytest.mark.unit
def test_app_update_check_finds_release(qtbot, qapp):
    """Test app update check detects new GitHub release."""
    thread = AppUpdateCheckThread()

    with patch("urllib.request.urlopen") as mock_urlopen:
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps(
            {
                "tag_name": "v99.0.0",
                "html_url": "https://github.com/test/release",
                "assets": [
                    {
                        "name": "TextWave.dmg",
                        "browser_download_url": "https://example.com/TextWave.dmg",
                    }
                ],
            }
        ).encode()
        mock_urlopen.return_value.__enter__.return_value = mock_response

        with qtbot.waitSignal(thread.finished, timeout=3000) as blocker:
            thread.start()

        has_update, current, latest, url = blocker.args
        assert has_update == True
        assert current == __version__
        assert latest == "99.0.0"
        assert url == "https://example.com/TextWave.dmg"


@pytest.mark.unit
def test_app_update_check_parses_version_tag(qtbot, qapp):
    """Test that version tags with 'v' prefix are parsed correctly."""
    thread = AppUpdateCheckThread()

    with patch("urllib.request.urlopen") as mock_urlopen:
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps(
            {
                "tag_name": "v2.5.3",
                "html_url": "https://github.com/test/release",
                "assets": [],
            }
        ).encode()
        mock_urlopen.return_value.__enter__.return_value = mock_response

        with qtbot.waitSignal(thread.finished, timeout=3000) as blocker:
            thread.start()

        _, _, latest, _ = blocker.args
        assert latest == "2.5.3"  # 'v' prefix should be stripped


@pytest.mark.unit
def test_app_update_check_finds_dmg_asset(qtbot, qapp):
    """Test that DMG asset is found in release assets."""
    thread = AppUpdateCheckThread()

    with patch("urllib.request.urlopen") as mock_urlopen:
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps(
            {
                "tag_name": "v99.0.0",
                "html_url": "https://github.com/test/release",
                "assets": [
                    {
                        "name": "README.md",
                        "browser_download_url": "https://example.com/readme",
                    },
                    {
                        "name": "TextWave-99.0.0.dmg",
                        "browser_download_url": "https://example.com/app.dmg",
                    },
                ],
            }
        ).encode()
        mock_urlopen.return_value.__enter__.return_value = mock_response

        with qtbot.waitSignal(thread.finished, timeout=3000) as blocker:
            thread.start()

        _, _, _, url = blocker.args
        assert url == "https://example.com/app.dmg"


@pytest.mark.unit
def test_app_update_check_fallback_to_html_url(qtbot, qapp):
    """Test fallback to release page when no DMG asset found."""
    thread = AppUpdateCheckThread()

    with patch("urllib.request.urlopen") as mock_urlopen:
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps(
            {
                "tag_name": "v99.0.0",
                "html_url": "https://github.com/test/release/page",
                "assets": [],  # No assets
            }
        ).encode()
        mock_urlopen.return_value.__enter__.return_value = mock_response

        with qtbot.waitSignal(thread.finished, timeout=3000) as blocker:
            thread.start()

        _, _, _, url = blocker.args
        assert url == "https://github.com/test/release/page"


@pytest.mark.unit
def test_app_update_check_handles_api_error(qtbot, qapp):
    """Test that GitHub API errors are handled gracefully."""
    thread = AppUpdateCheckThread()

    with patch("urllib.request.urlopen") as mock_urlopen:
        mock_urlopen.side_effect = Exception("API Error")

        with qtbot.waitSignal(thread.finished, timeout=3000) as blocker:
            thread.start()

        has_update, current, latest, url = blocker.args
        assert has_update == False
        assert current == ""
        assert latest == ""
        assert url == ""
