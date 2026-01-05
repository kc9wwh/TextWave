import asyncio
import json
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
import webbrowser
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import List, Optional

__version__ = "0.7.0"


@dataclass
class ConversionState:
    """Persistent state for resumable conversions."""

    pdf_path: str
    output_path: str
    total_chunks: int
    chunks_completed: int
    completed_chunk_files: List[str]
    chunk_size: int
    parallel_streams: int
    temp_dir: str
    started_at: str
    pdf_name: str  # For display in banner

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, data):
        return cls(**data)


def get_resource_path(filename):
    """Get the path to a resource file, works in both dev and bundled app."""
    # Try py2app bundle location first (Resources folder)
    if getattr(sys, "frozen", False):
        # Running in a bundle
        bundle_dir = (
            Path(sys._MEIPASS)
            if hasattr(sys, "_MEIPASS")
            else Path(sys.executable).parent.parent / "Resources"
        )
        resource_path = bundle_dir / filename
        if resource_path.exists():
            return resource_path

    # Fall back to development location (same directory as script)
    dev_path = Path(__file__).parent / filename
    if dev_path.exists():
        return dev_path

    return None


# Auto-install dependencies if missing
try:
    import edge_tts
    from pypdf import PdfReader
    from PyQt6.QtCore import QEvent, QSettings, Qt, QThread, pyqtSignal
    from PyQt6.QtGui import QDragEnterEvent, QDropEvent, QPixmap

    try:
        from PyQt6.QtSvgWidgets import QSvgWidget

        SVG_AVAILABLE = True
    except ImportError:
        SVG_AVAILABLE = False
    from PyQt6.QtWidgets import (
        QApplication,
        QDialog,
        QDialogButtonBox,
        QFileDialog,
        QFormLayout,
        QHBoxLayout,
        QLabel,
        QLineEdit,
        QMainWindow,
        QMessageBox,
        QProgressBar,
        QPushButton,
        QSpinBox,
        QTextEdit,
        QVBoxLayout,
        QWidget,
    )
except ImportError as e:
    missing = str(e).split("'")[1] if "'" in str(e) else "dependencies"
    print("Installing required dependencies...")
    packages = ["edge-tts", "pypdf", "PyQt6"]
    subprocess.check_call([sys.executable, "-m", "pip", "install"] + packages)
    print("Dependencies installed. Please run the script again.\n")
    sys.exit(0)

# Microsoft Azure Neural Voice (Free via edge-tts)
VOICE = "en-US-AvaMultilingualNeural"


def chunk_text_by_sentences(text: str, max_chars: int = 2000) -> List[str]:
    """Split text into chunks at sentence boundaries.

    Args:
        text: Full PDF text
        max_chars: Target chunk size (default 2000 for ~13s processing)

    Returns:
        List of text chunks, each ending at sentence boundary
    """
    # Split on sentence endings: . ! ? followed by space/newline
    sentence_pattern = r"(?<=[.!?])\s+"
    sentences = re.split(sentence_pattern, text)

    chunks = []
    current_chunk = ""

    for sentence in sentences:
        # If adding sentence exceeds max, start new chunk
        if len(current_chunk) + len(sentence) > max_chars and current_chunk:
            chunks.append(current_chunk.strip())
            current_chunk = sentence
        else:
            current_chunk += " " + sentence if current_chunk else sentence

    if current_chunk:
        chunks.append(current_chunk.strip())

    return chunks


def get_state_file_path() -> Path:
    """Get path to the conversion state file."""
    app_support = Path.home() / "Library" / "Application Support" / "TextWave"
    app_support.mkdir(parents=True, exist_ok=True)
    return app_support / "conversion_state.json"


def save_conversion_state(state: ConversionState):
    """Save conversion state to persistent storage."""
    state_file = get_state_file_path()
    with open(state_file, "w") as f:
        json.dump(state.to_dict(), f, indent=2)


def load_conversion_state() -> Optional[ConversionState]:
    """Load conversion state from persistent storage."""
    state_file = get_state_file_path()
    if not state_file.exists():
        return None

    try:
        with open(state_file, "r") as f:
            data = json.load(f)
        return ConversionState.from_dict(data)
    except Exception:
        return None


def delete_conversion_state():
    """Delete the saved conversion state."""
    state_file = get_state_file_path()
    if state_file.exists():
        state_file.unlink()


def extract_and_clean_text(pdf_path):
    reader = PdfReader(pdf_path)
    total_pages = len(reader.pages)
    full_text = ""

    page_number_pattern = re.compile(r"^\s*(page\s*)?\d+\s*$", re.IGNORECASE)

    for idx, page in enumerate(reader.pages, 1):
        text = page.extract_text()
        if text:
            lines = text.split("\n")
            cleaned_lines = []
            for line in lines:
                if page_number_pattern.match(line):
                    continue
                cleaned_lines.append(line)

            page_text = " ".join(cleaned_lines)
            full_text += page_text + " "

    return full_text, total_pages


async def text_to_speech_async(text, output_file, progress_callback):
    char_count = len(text)
    estimated_mb = char_count / 2870

    try:
        communicate = edge_tts.Communicate(text, VOICE)
        total_bytes = 0

        with open(output_file, "wb") as f:
            async for chunk in communicate.stream():
                if chunk["type"] == "audio":
                    f.write(chunk["data"])
                    total_bytes += len(chunk["data"])
                    mb = total_bytes / (1024 * 1024)
                    percentage = min((mb / estimated_mb) * 100, 99.9)
                    progress_callback(
                        int(percentage), f"{mb:.2f} MB / ~{estimated_mb:.1f} MB"
                    )

        final_mb = total_bytes / (1024 * 1024)
        progress_callback(100, f"Complete! {final_mb:.2f} MB")
    except Exception as e:
        error_msg = str(e)
        if "401" in error_msg or "Unauthorized" in error_msg or "403" in error_msg:
            raise Exception(
                "Edge TTS service connection failed.\n\n"
                "Possible solutions:\n"
                "1. Update edge-tts: Run 'pip3 install --upgrade edge-tts' in Terminal\n"
                "2. Check your internet connection\n"
                "3. Try again in a few minutes (temporary API issue)\n"
                "4. Restart the app\n\n"
                f"Technical details: {error_msg}"
            )
        else:
            raise


class VersionCheckThread(QThread):
    finished = pyqtSignal(
        bool, str, str
    )  # has_update, installed_version, latest_version

    def run(self):
        try:
            # Get installed version
            result = subprocess.run(
                [sys.executable, "-m", "pip", "show", "edge-tts"],
                capture_output=True,
                text=True,
                timeout=5,
            )

            if result.returncode != 0:
                self.finished.emit(False, "", "")
                return

            installed_version = None
            for line in result.stdout.split("\n"):
                if line.startswith("Version:"):
                    installed_version = line.split(":", 1)[1].strip()
                    break

            if not installed_version:
                self.finished.emit(False, "", "")
                return

            # Get latest version from PyPI
            with urllib.request.urlopen(
                "https://pypi.org/pypi/edge-tts/json", timeout=5
            ) as response:
                data = json.loads(response.read().decode())
                latest_version = data["info"]["version"]

            # Compare versions
            has_update = installed_version != latest_version
            self.finished.emit(has_update, installed_version, latest_version)

        except Exception:
            # Silently fail - don't interrupt the app for version check issues
            self.finished.emit(False, "", "")


class UpdateThread(QThread):
    status = pyqtSignal(str)
    finished = pyqtSignal(bool, str)

    def run(self):
        try:
            self.status.emit("Updating edge-tts...")
            result = subprocess.run(
                [sys.executable, "-m", "pip", "install", "--upgrade", "edge-tts"],
                capture_output=True,
                text=True,
                timeout=60,
            )

            if result.returncode == 0:
                self.finished.emit(True, "edge-tts updated successfully!")
            else:
                error_msg = result.stderr if result.stderr else "Update failed"
                self.finished.emit(False, f"Update failed: {error_msg}")

        except subprocess.TimeoutExpired:
            self.finished.emit(False, "Update timed out. Please try again.")
        except Exception as e:
            self.finished.emit(False, f"Update error: {str(e)}")


class PreferencesDialog(QDialog):
    """Preferences dialog for configuring conversion settings."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("TextWave Preferences")
        self.setModal(True)
        self.setMinimumWidth(450)

        # Load current settings
        self.settings = QSettings("TextWave", "PDF2MP3")

        # Create form layout
        layout = QFormLayout()
        self.setLayout(layout)

        # Chunk size setting
        self.chunk_size_spin = QSpinBox()
        self.chunk_size_spin.setRange(500, 10000)
        self.chunk_size_spin.setSingleStep(500)
        self.chunk_size_spin.setValue(self.settings.value("chunk_size", 2000, type=int))
        self.chunk_size_spin.setSuffix(" characters")
        layout.addRow("Chunk Size:", self.chunk_size_spin)

        # Help text for chunk size
        chunk_help = QLabel(
            "Smaller chunks = faster pause response, more API calls\n"
            "Larger chunks = fewer API calls, slower pause response\n"
            "Recommended: 2000-4000 characters"
        )
        chunk_help.setStyleSheet("font-size: 11px; color: gray; padding-left: 20px;")
        chunk_help.setWordWrap(True)
        layout.addRow("", chunk_help)

        # Parallel streams setting
        self.parallel_spin = QSpinBox()
        self.parallel_spin.setRange(1, 10)
        self.parallel_spin.setValue(
            self.settings.value("parallel_streams", 3, type=int)
        )
        self.parallel_spin.setSuffix(" streams")
        layout.addRow("Parallel Streams:", self.parallel_spin)

        # Help text for parallel streams
        parallel_help = QLabel(
            "More streams = faster conversion, higher API rate risk\n"
            "Fewer streams = slower conversion, safer\n"
            "Recommended: 2-5 streams"
        )
        parallel_help.setStyleSheet("font-size: 11px; color: gray; padding-left: 20px;")
        parallel_help.setWordWrap(True)
        layout.addRow("", parallel_help)

        # Temp directory setting
        temp_layout = QHBoxLayout()
        self.temp_dir_edit = QLineEdit()
        self.temp_dir_edit.setText(
            self.settings.value("temp_directory", tempfile.gettempdir(), type=str)
        )
        self.temp_dir_edit.setReadOnly(True)
        temp_layout.addWidget(self.temp_dir_edit)

        browse_btn = QPushButton("Browse...")
        browse_btn.clicked.connect(self.browse_temp_dir)
        temp_layout.addWidget(browse_btn)

        temp_widget = QWidget()
        temp_widget.setLayout(temp_layout)
        layout.addRow("Temp Directory:", temp_widget)

        # Help text for temp directory
        temp_help = QLabel(
            "Location for temporary audio chunk files during conversion\n"
            "Requires sufficient disk space for large PDFs"
        )
        temp_help.setStyleSheet("font-size: 11px; color: gray; padding-left: 20px;")
        temp_help.setWordWrap(True)
        layout.addRow("", temp_help)

        # Buttons
        button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
            | QDialogButtonBox.StandardButton.RestoreDefaults
        )
        button_box.accepted.connect(self.save_settings)
        button_box.rejected.connect(self.reject)
        button_box.button(
            QDialogButtonBox.StandardButton.RestoreDefaults
        ).clicked.connect(self.restore_defaults)
        layout.addRow(button_box)

    def browse_temp_dir(self):
        """Open directory picker for temp directory."""
        current = self.temp_dir_edit.text()
        directory = QFileDialog.getExistingDirectory(
            self, "Select Temporary Directory", current
        )
        if directory:
            self.temp_dir_edit.setText(directory)

    def save_settings(self):
        """Save settings and close dialog."""
        self.settings.setValue("chunk_size", self.chunk_size_spin.value())
        self.settings.setValue("parallel_streams", self.parallel_spin.value())
        self.settings.setValue("temp_directory", self.temp_dir_edit.text())
        self.accept()

    def restore_defaults(self):
        """Restore default settings."""
        self.chunk_size_spin.setValue(2000)
        self.parallel_spin.setValue(3)
        self.temp_dir_edit.setText(tempfile.gettempdir())


async def process_single_chunk(
    chunk_text: str, voice: str, output_file: Path, progress_callback=None
) -> Path:
    """Process a single text chunk to MP3.

    Args:
        chunk_text: Text to convert
        voice: TTS voice name
        output_file: Path to save MP3
        progress_callback: Optional callback for progress updates

    Returns:
        Path to generated MP3 file
    """
    communicate = edge_tts.Communicate(chunk_text, voice)

    with open(output_file, "wb") as f:
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                f.write(chunk["data"])

    if progress_callback:
        progress_callback()

    return output_file


async def process_chunk_batch(
    chunks: List[str],
    voice: str,
    output_dir: Path,
    start_idx: int,
    progress_callback=None,
) -> List[Path]:
    """Process multiple chunks in parallel using asyncio.gather.

    Args:
        chunks: List of text chunks to process
        voice: TTS voice name
        output_dir: Temporary directory for chunk files
        start_idx: Starting index for naming files
        progress_callback: Optional callback for progress updates

    Returns:
        List of paths to generated MP3 files
    """
    tasks = []
    for i, chunk in enumerate(chunks):
        output_file = output_dir / f"chunk_{start_idx + i:04d}.mp3"
        tasks.append(process_single_chunk(chunk, voice, output_file, progress_callback))

    return await asyncio.gather(*tasks)


class AppUpdateCheckThread(QThread):
    finished = pyqtSignal(
        bool, str, str, str
    )  # has_update, current_version, latest_version, download_url

    def run(self):
        try:
            # Get current version
            current_version = __version__

            # Query GitHub API for latest release
            with urllib.request.urlopen(
                "https://api.github.com/repos/kc9wwh/TextWave/releases/latest",
                timeout=5,
            ) as response:
                data = json.loads(response.read().decode())

                latest_version = data["tag_name"].lstrip("v")

                # Find .dmg or .app.zip asset
                download_url = None
                for asset in data.get("assets", []):
                    name = asset["name"].lower()
                    if name.endswith(".dmg") or name.endswith(".app.zip"):
                        download_url = asset["browser_download_url"]
                        break

                # If no asset found, use release page URL
                if not download_url:
                    download_url = data["html_url"]

                # Compare versions (simple string comparison)
                has_update = (
                    current_version != latest_version
                    and latest_version > current_version
                )
                self.finished.emit(
                    has_update, current_version, latest_version, download_url
                )

        except Exception:
            # Silently fail - don't interrupt the app for update check issues
            self.finished.emit(False, "", "", "")


class ConversionThread(QThread):
    progress = pyqtSignal(int, str)
    status = pyqtSignal(str)
    finished = pyqtSignal(bool, str)
    paused = pyqtSignal(bool)  # True when paused, False when resumed

    def __init__(
        self, pdf_path, output_path, resume_state: Optional[ConversionState] = None
    ):
        super().__init__()
        self.pdf_path = pdf_path
        self.output_path = output_path
        self.caffeinate_process = None
        self.resume_state = resume_state

        # Pause/Resume state
        self._pause_requested = threading.Event()
        self._is_paused = False
        self._state_lock = threading.Lock()
        self._cancel_requested = False

    def run(self):
        temp_dir = None
        conversion_state = None
        try:
            # Start caffeinate to prevent macOS sleep during conversion
            self.caffeinate_process = subprocess.Popen(
                ["caffeinate", "-di"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

            # Check if resuming
            if self.resume_state:
                self.status.emit("📂 Resuming previous conversion...")
                temp_dir = Path(self.resume_state.temp_dir)
                chunk_size = self.resume_state.chunk_size
                parallel_streams = self.resume_state.parallel_streams
                chunks_completed = self.resume_state.chunks_completed
                total_chunks = self.resume_state.total_chunks
                chunk_files = [Path(f) for f in self.resume_state.completed_chunk_files]

                # Re-extract and chunk text (needed for remaining chunks)
                text, _ = extract_and_clean_text(self.pdf_path)
                chunks = chunk_text_by_sentences(text, max_chars=chunk_size)

                self.status.emit(
                    f"Resuming from chunk {chunks_completed + 1}/{total_chunks}"
                )
                start_chunk = chunks_completed

                conversion_state = self.resume_state
            else:
                # Extract text
                self.status.emit("Extracting text from PDF...")
                text, total_pages = extract_and_clean_text(self.pdf_path)
                self.status.emit(
                    f"Extracted {len(text):,} characters from {total_pages} pages"
                )

                # Get settings from QSettings
                settings = QSettings("TextWave", "PDF2MP3")
                chunk_size = settings.value("chunk_size", 2000, type=int)
                parallel_streams = settings.value("parallel_streams", 3, type=int)
                temp_dir_path = settings.value(
                    "temp_directory", tempfile.gettempdir(), type=str
                )

                # Chunk text
                self.status.emit("Preparing text chunks...")
                chunks = chunk_text_by_sentences(text, max_chars=chunk_size)
                total_chunks = len(chunks)
                self.status.emit(f"Created {total_chunks} chunks for processing")

                # Create persistent temp directory
                temp_dir = Path(temp_dir_path) / f"textwave_{int(time.time())}"
                temp_dir.mkdir(parents=True, exist_ok=True)

                chunk_files = []
                chunks_completed = 0
                start_chunk = 0

                # Create initial state
                conversion_state = ConversionState(
                    pdf_path=self.pdf_path,
                    output_path=self.output_path,
                    total_chunks=total_chunks,
                    chunks_completed=0,
                    completed_chunk_files=[],
                    chunk_size=chunk_size,
                    parallel_streams=parallel_streams,
                    temp_dir=str(temp_dir),
                    started_at=datetime.now().isoformat(),
                    pdf_name=Path(self.pdf_path).name,
                )

            # Process in parallel batches
            batch_size = parallel_streams
            for batch_start in range(start_chunk, total_chunks, batch_size):
                # Check pause before each batch
                self._check_pause_state()
                if self._cancel_requested:
                    raise Exception("Conversion cancelled by user")

                # Get batch of chunks
                batch_end = min(batch_start + batch_size, total_chunks)
                batch = chunks[batch_start:batch_end]

                # Process batch in parallel
                self.status.emit(
                    f"Converting chunks {batch_start + 1}-{batch_end} of {total_chunks}..."
                )

                def progress_callback():
                    nonlocal chunks_completed
                    chunks_completed += 1
                    percentage = int((chunks_completed / total_chunks) * 100)
                    self.progress.emit(
                        percentage, f"{chunks_completed}/{total_chunks} chunks"
                    )

                batch_files = asyncio.run(
                    process_chunk_batch(
                        batch, VOICE, temp_dir, batch_start, progress_callback
                    )
                )
                chunk_files.extend(batch_files)

                # Save state after each batch
                conversion_state = ConversionState(
                    pdf_path=self.pdf_path,
                    output_path=self.output_path,
                    total_chunks=total_chunks,
                    chunks_completed=chunks_completed,
                    completed_chunk_files=[str(f) for f in chunk_files],
                    chunk_size=chunk_size,
                    parallel_streams=parallel_streams,
                    temp_dir=str(temp_dir),
                    started_at=conversion_state.started_at
                    if conversion_state
                    else datetime.now().isoformat(),
                    pdf_name=Path(self.pdf_path).name,
                )
                save_conversion_state(conversion_state)

                # Rate limit: 1.5s delay between batches
                if batch_end < total_chunks:
                    time.sleep(1.5)

            # Concatenate MP3 files
            self.status.emit("Merging audio files...")
            self.progress.emit(99, "Finalizing...")
            self._concatenate_mp3_files(chunk_files, self.output_path)

            self.progress.emit(100, "Complete!")
            self.finished.emit(True, f"Successfully saved to:\n{self.output_path}")

            # Delete saved state on successful completion
            delete_conversion_state()

            # Cleanup temp files on success
            if temp_dir and temp_dir.exists():
                try:
                    shutil.rmtree(temp_dir)
                except Exception:
                    pass  # Ignore cleanup errors

        except Exception as e:
            self.finished.emit(False, f"Error: {str(e)}")
        finally:
            # Cleanup temp files only on explicit cancellation
            if temp_dir and temp_dir.exists() and self._cancel_requested:
                try:
                    shutil.rmtree(temp_dir)
                    delete_conversion_state()
                except Exception:
                    pass  # Ignore cleanup errors

            # Always stop caffeinate when conversion completes or fails
            self.stop_caffeinate()

    def stop_caffeinate(self):
        """Stop the caffeinate process to allow macOS to sleep again."""
        if self.caffeinate_process:
            try:
                self.caffeinate_process.terminate()
                self.caffeinate_process.wait(timeout=2)
            except Exception:
                try:
                    self.caffeinate_process.kill()
                except Exception:
                    pass
            self.caffeinate_process = None

    def _check_pause_state(self):
        """Check if pause requested and wait until resumed."""
        if self._pause_requested.is_set():
            with self._state_lock:
                self._is_paused = True

            # Emit pause state to GUI
            self.paused.emit(True)

            # Wait until pause is cleared
            while self._pause_requested.is_set():
                time.sleep(0.1)
                if self._cancel_requested:
                    break

            with self._state_lock:
                self._is_paused = False

            self.paused.emit(False)

    def request_pause(self):
        """Request pause (thread-safe, called from GUI thread)."""
        self._pause_requested.set()

    def request_resume(self):
        """Resume from pause (thread-safe)."""
        self._pause_requested.clear()

    def request_cancel(self):
        """Cancel conversion entirely."""
        self._cancel_requested = True
        self._pause_requested.clear()  # Unblock if paused

    def _has_ffmpeg(self) -> bool:
        """Check if ffmpeg is available."""
        try:
            subprocess.run(
                ["ffmpeg", "-version"], capture_output=True, check=True, timeout=5
            )
            return True
        except (
            subprocess.CalledProcessError,
            FileNotFoundError,
            subprocess.TimeoutExpired,
        ):
            return False

    def _concatenate_mp3_files(self, chunk_files: List[Path], output_path: str):
        """Concatenate MP3 files into single output file."""
        if not chunk_files:
            raise Exception("No chunk files to concatenate")

        # If only one chunk, just copy it
        if len(chunk_files) == 1:
            shutil.copy(chunk_files[0], output_path)
            return

        # Try ffmpeg first (better quality)
        if self._has_ffmpeg():
            try:
                self._concat_with_ffmpeg(chunk_files, output_path)
                return
            except Exception as e:
                self.status.emit(
                    f"ffmpeg failed ({str(e)}), using binary concatenation..."
                )

        # Fallback: binary concatenation
        self._concat_binary(chunk_files, output_path)

    def _concat_with_ffmpeg(self, chunk_files: List[Path], output_path: str):
        """Use ffmpeg concat demuxer for seamless merging."""
        # Create concat file list
        concat_file = chunk_files[0].parent / "concat_list.txt"
        with open(concat_file, "w") as f:
            for chunk in chunk_files:
                # Escape single quotes in path for ffmpeg
                escaped_path = str(chunk.absolute()).replace("'", "'\\''")
                f.write(f"file '{escaped_path}'\n")

        # Run ffmpeg
        result = subprocess.run(
            [
                "ffmpeg",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(concat_file),
                "-c",
                "copy",  # No re-encoding
                "-y",  # Overwrite output file
                output_path,
            ],
            capture_output=True,
            timeout=60,
        )

        if result.returncode != 0:
            raise Exception(f"ffmpeg error: {result.stderr.decode()}")

    def _concat_binary(self, chunk_files: List[Path], output_path: str):
        """Simple binary concatenation (works for MP3 format)."""
        with open(output_path, "wb") as outfile:
            for chunk_file in chunk_files:
                with open(chunk_file, "rb") as infile:
                    outfile.write(infile.read())


class PDF2MP3App(QMainWindow):
    def __init__(self):
        super().__init__()
        self.settings = QSettings("TextWave", "PDF2MP3")
        self.pdf_path = None
        self.update_banner = None
        self.update_dismissed = False
        self.installed_version = ""
        self.latest_version = ""
        self.app_update_banner = None
        self.app_update_dismissed = False
        self.app_current_version = ""
        self.app_latest_version = ""
        self.app_download_url = ""
        self.resume_banner = None
        self.resume_state = None
        self.init_ui()

    def get_theme_colors(self):
        """Get color palette based on system theme."""
        app = QApplication.instance()
        is_dark = app.styleHints().colorScheme() == Qt.ColorScheme.Dark

        if is_dark:
            return {
                "window_bg": "#1e1e1e",
                "subtitle_color": "#aaaaaa",
                "drop_bg": "#2d2d2d",
                "drop_border": "#00BCD4",
                "drop_text": "#e0e0e0",
                "log_bg": "#121212",
                "log_text": "#e0e0e0",
                "log_border": "#333333",
                "banner_update_bg": "#0D47A1",
                "banner_update_border": "#00BCD4",
                "banner_app_bg": "#1B5E20",
                "banner_app_border": "#4CAF50",
                "dismiss_btn": "#aaaaaa",
                "dismiss_btn_hover": "#ffffff",
            }
        else:
            return {
                "window_bg": "#f0f0f0",
                "subtitle_color": "#666",
                "drop_bg": "#f5f5f5",
                "drop_border": "#00BCD4",
                "drop_text": "#000000",
                "log_bg": "#ffffff",
                "log_text": "#000000",
                "log_border": "#cccccc",
                "banner_update_bg": "#E3F2FD",
                "banner_update_border": "#00BCD4",
                "banner_app_bg": "#E8F5E9",
                "banner_app_border": "#4CAF50",
                "dismiss_btn": "#666",
                "dismiss_btn_hover": "#000",
            }

    def apply_theme(self):
        """Apply current theme colors to all widgets."""
        colors = self.get_theme_colors()

        # Main Window
        if self.centralWidget():
            self.centralWidget().setStyleSheet(
                f"background-color: {colors['window_bg']};"
            )

        # Subtitle
        if hasattr(self, "subtitle_label"):
            self.subtitle_label.setStyleSheet(f"""
                QLabel {{
                    font-size: 14px;
                    color: {colors["subtitle_color"]};
                    padding-bottom: 15px;
                    padding-top: 5px;
                }}
            """)

        # Drop Label
        if hasattr(self, "drop_label"):
            self.drop_label.setStyleSheet(f"""
                QLabel {{
                    border: 3px dashed {colors["drop_border"]};
                    border-radius: 10px;
                    padding: 50px;
                    font-size: 18px;
                    background-color: {colors["drop_bg"]};
                    color: {colors["drop_text"]};
                }}
            """)

        # Log Window
        if hasattr(self, "status_text"):
            self.status_text.setStyleSheet(f"""
                QTextEdit {{
                    background-color: {colors["log_bg"]};
                    color: {colors["log_text"]};
                    border: 1px solid {colors["log_border"]};
                    border-radius: 4px;
                }}
            """)

        # Update Banners if they exist
        if self.update_banner:
            self.update_banner_style(self.update_banner, colors, "update")
        if self.app_update_banner:
            self.update_banner_style(self.app_update_banner, colors, "app")

    def update_banner_style(self, banner, colors, type_):
        """Helper to update banner styles."""
        bg = colors[f"banner_{type_}_bg"]
        border = colors[f"banner_{type_}_border"]

        # Apply style to the banner container
        banner.setStyleSheet(f"""
            QWidget {{
                background-color: {bg};
                border: 1px solid {border};
                border-radius: 5px;
            }}
        """)

        # Update dismiss button color
        for btn in banner.findChildren(QPushButton):
            if btn.text() == "×":
                btn.setStyleSheet(f"""
                    QPushButton {{
                        background: transparent;
                        border: none;
                        font-size: 20px;
                        font-weight: bold;
                        color: {colors["dismiss_btn"]};
                        padding: 0px 5px;
                    }}
                    QPushButton:hover {{
                        color: {colors["dismiss_btn_hover"]};
                    }}
                """)
            # Ensure update/download buttons keep their specific styling if needed,
            # but they usually have their own inline style.
            # We should verify if apply_theme overwrites them.
            # The banner.setStyleSheet might affect children if using QWidget selector without ID.
            # The current implementation sets style on the banner widget itself.

    def changeEvent(self, event):
        if event.type() == QEvent.Type.PaletteChange:
            self.apply_theme()
        super().changeEvent(event)

    def init_ui(self):
        self.setWindowTitle("TextWave")
        self.setGeometry(100, 100, 700, 600)

        # Menu bar
        menubar = self.menuBar()

        # File menu
        file_menu = menubar.addMenu("File")

        preferences_action = file_menu.addAction("Preferences...")
        preferences_action.setShortcut("Cmd+,")
        preferences_action.triggered.connect(self.show_preferences)

        file_menu.addSeparator()

        quit_action = file_menu.addAction("Quit")
        quit_action.setShortcut("Cmd+Q")
        quit_action.triggered.connect(self.close)

        # Central widget
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        layout = QVBoxLayout()
        central_widget.setLayout(layout)

        # Logo image (use SVG if available, otherwise PNG)
        logo_svg_path = get_resource_path("textwave_logo.svg")
        logo_png_path = get_resource_path("textwave_logo.png")

        if SVG_AVAILABLE and logo_svg_path:
            logo_widget = QSvgWidget(str(logo_svg_path))
            logo_widget.setFixedSize(280, 280)
            layout.addWidget(logo_widget, alignment=Qt.AlignmentFlag.AlignCenter)
        elif logo_png_path:
            logo_label = QLabel()
            logo_label.setStyleSheet("background-color: transparent;")
            pixmap = QPixmap(str(logo_png_path))
            scaled_pixmap = pixmap.scaled(
                280,
                280,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            logo_label.setPixmap(scaled_pixmap)
            logo_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(logo_label)

        # Subtitle (logo already contains "TextWave" text)
        self.subtitle_label = QLabel("Convert PDFs to MP3 Audio")
        self.subtitle_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.subtitle_label)

        # Drop area label
        self.drop_label = QLabel(
            "📄 Drag & Drop PDF Here\n\nor click 'Select PDF' below"
        )
        self.drop_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.drop_label.setAcceptDrops(True)
        self.drop_label.dragEnterEvent = self.drag_enter_event
        self.drop_label.dropEvent = self.drop_event
        layout.addWidget(self.drop_label)

        # Select PDF button
        self.select_btn = QPushButton("Select PDF")
        self.select_btn.clicked.connect(self.select_pdf)
        self.select_btn.setStyleSheet("QPushButton { padding: 10px; font-size: 14px; }")
        layout.addWidget(self.select_btn)

        # Convert button
        self.convert_btn = QPushButton("Convert to MP3")
        self.convert_btn.clicked.connect(self.convert)
        self.convert_btn.setEnabled(False)
        self.convert_btn.setStyleSheet("""
            QPushButton {
                padding: 15px;
                font-size: 16px;
                font-weight: bold;
                background-color: #00BCD4;
                color: white;
                border-radius: 5px;
            }
            QPushButton:disabled {
                background-color: #cccccc;
            }
            QPushButton:hover:enabled {
                background-color: #0097A7;
            }
        """)
        layout.addWidget(self.convert_btn)

        # Pause button (hidden by default, shown during conversion)
        self.pause_btn = QPushButton("Pause")
        self.pause_btn.clicked.connect(self.toggle_pause)
        self.pause_btn.setVisible(False)
        self.pause_btn.setStyleSheet("""
            QPushButton {
                padding: 10px;
                font-size: 14px;
                background-color: #FF9800;
                color: white;
                border-radius: 5px;
            }
            QPushButton:hover {
                background-color: #F57C00;
            }
        """)
        layout.addWidget(self.pause_btn)

        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)

        # Status text
        self.status_text = QTextEdit()
        self.status_text.setReadOnly(True)
        self.status_text.setMaximumHeight(100)
        self.status_text.setVisible(False)
        layout.addWidget(self.status_text)

        # Start version check in background
        self.version_check_thread = VersionCheckThread()
        self.version_check_thread.finished.connect(self.version_check_complete)
        self.version_check_thread.start()

        # Start app update check in background
        self.app_update_check_thread = AppUpdateCheckThread()
        self.app_update_check_thread.finished.connect(self.app_update_check_complete)
        self.app_update_check_thread.start()

        # Check for incomplete conversion on startup
        self.check_resume_state()

        # Apply initial theme
        self.apply_theme()

    def check_resume_state(self):
        """Check for saved conversion state and show resume banner if found."""
        self.resume_state = load_conversion_state()
        if self.resume_state:
            # Verify temp directory and PDF still exist
            temp_dir = Path(self.resume_state.temp_dir)
            pdf_path = Path(self.resume_state.pdf_path)

            if temp_dir.exists() and pdf_path.exists():
                # Create and show resume banner
                self.resume_banner = self.create_resume_banner(self.resume_state)

                # Insert at top of layout
                central_widget = self.centralWidget()
                if central_widget:
                    layout = central_widget.layout()
                    if layout:
                        layout.insertWidget(0, self.resume_banner)
            else:
                # State is invalid, clean it up
                if temp_dir.exists():
                    try:
                        shutil.rmtree(temp_dir)
                    except Exception:
                        pass
                delete_conversion_state()
                self.resume_state = None

    def show_preferences(self):
        """Show preferences dialog."""
        dialog = PreferencesDialog(self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            # Settings are saved in dialog.save_settings()
            # Show confirmation
            self.status_text.setVisible(True)
            self.status_text.append(
                "✓ Preferences saved. Changes will apply to next conversion."
            )

    def toggle_pause(self):
        """Handle pause/resume button click."""
        if hasattr(self, "thread") and self.thread.isRunning():
            if self.thread._is_paused or self.thread._pause_requested.is_set():
                # Resume
                self.thread.request_resume()
                self.pause_btn.setText("Pause")
                self.status_text.append("⏯️ Resuming conversion...")
            else:
                # Pause
                self.thread.request_pause()
                self.pause_btn.setText("Resume")
                self.status_text.append("⏸️ Pausing (finishing current chunk)...")

    def handle_pause_state(self, is_paused: bool):
        """Update UI when pause state changes."""
        if is_paused:
            self.pause_btn.setText("Resume")
            self.status_text.append("⏸️ Paused")
        else:
            self.pause_btn.setText("Pause")

    def create_update_banner(self):
        """Create the update notification banner widget."""
        colors = self.get_theme_colors()
        banner = QWidget()
        banner.setStyleSheet(f"""
            QWidget {{
                background-color: {colors["banner_update_bg"]};
                border: 1px solid {colors["banner_update_border"]};
                border-radius: 5px;
                padding: 10px;
            }}
        """)

        banner_layout = QHBoxLayout()
        banner_layout.setContentsMargins(10, 10, 10, 10)
        banner.setLayout(banner_layout)

        # Info icon
        icon_label = QLabel("ℹ️")
        icon_label.setStyleSheet(
            "font-size: 20px; background: transparent; border: none;"
        )
        banner_layout.addWidget(icon_label)

        # Update message
        message_label = QLabel(
            f"edge-tts update available: {self.installed_version} → {self.latest_version}"
        )
        message_label.setStyleSheet(
            "background: transparent; border: none; font-size: 13px;"
        )
        banner_layout.addWidget(message_label, stretch=1)

        # Update button
        update_btn = QPushButton("Update Now")
        update_btn.setStyleSheet("""
            QPushButton {
                background-color: #00BCD4;
                color: white;
                border: none;
                border-radius: 3px;
                padding: 8px 15px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #0097A7;
            }
            QPushButton:disabled {
                background-color: #cccccc;
            }
        """)
        update_btn.clicked.connect(self.perform_update)
        banner_layout.addWidget(update_btn)

        # Dismiss button
        dismiss_btn = QPushButton("×")
        dismiss_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                border: none;
                font-size: 20px;
                font-weight: bold;
                color: {colors["dismiss_btn"]};
                padding: 0px 5px;
            }}
            QPushButton:hover {{
                color: {colors["dismiss_btn_hover"]};
            }}
        """)
        dismiss_btn.clicked.connect(self.dismiss_update_banner)
        banner_layout.addWidget(dismiss_btn)

        return banner

    def dismiss_update_banner(self):
        """Hide the update banner for this session."""
        if self.update_banner:
            self.update_banner.setVisible(False)
            self.update_dismissed = True

    def perform_update(self):
        """Start the edge-tts update process."""
        if not self.update_banner:
            return

        # Disable update button
        update_btn = self.update_banner.findChild(
            QPushButton, "", Qt.FindChildOption.FindDirectChildrenOnly
        )
        if update_btn:
            for btn in self.update_banner.findChildren(QPushButton):
                if btn.text() == "Update Now":
                    btn.setEnabled(False)
                    btn.setText("Updating...")
                    break

        # Show status
        self.status_text.setVisible(True)
        self.status_text.clear()
        self.status_text.append("Starting edge-tts update...")

        # Start update thread
        self.update_thread = UpdateThread()
        self.update_thread.status.connect(self.update_status)
        self.update_thread.finished.connect(self.update_finished)
        self.update_thread.start()

    def update_finished(self, success, message):
        """Handle update completion."""
        self.status_text.append(message)

        if success:
            # Remove the banner permanently
            if self.update_banner:
                self.update_banner.setVisible(False)
                self.update_banner.deleteLater()
                self.update_banner = None

            # Show success message
            QMessageBox.information(
                self,
                "Update Complete",
                "edge-tts has been updated successfully!\n\n"
                "You can now use the latest version.",
            )
        else:
            # Re-enable update button on failure
            if self.update_banner:
                for btn in self.update_banner.findChildren(QPushButton):
                    if "Updating" in btn.text():
                        btn.setEnabled(True)
                        btn.setText("Update Now")
                        break

            # Show error message
            QMessageBox.warning(
                self,
                "Update Failed",
                f"{message}\n\n"
                "You can try updating manually:\n"
                "pip install --upgrade edge-tts",
            )

    def version_check_complete(self, has_update, installed_version, latest_version):
        """Handle version check completion."""
        if has_update and not self.update_dismissed:
            self.installed_version = installed_version
            self.latest_version = latest_version

            # Create and show update banner
            self.update_banner = self.create_update_banner()

            # Insert at top of layout (position 0)
            central_widget = self.centralWidget()
            if central_widget:
                layout = central_widget.layout()
                if layout:
                    layout.insertWidget(0, self.update_banner)

    def create_app_update_banner(self):
        """Create the app update notification banner widget."""
        colors = self.get_theme_colors()
        banner = QWidget()
        banner.setStyleSheet(f"""
            QWidget {{
                background-color: {colors["banner_app_bg"]};
                border: 1px solid {colors["banner_app_border"]};
                border-radius: 5px;
                padding: 10px;
            }}
        """)

        banner_layout = QHBoxLayout()
        banner_layout.setContentsMargins(10, 10, 10, 10)
        banner.setLayout(banner_layout)

        # Info icon
        icon_label = QLabel("🔔")
        icon_label.setStyleSheet(
            "font-size: 20px; background: transparent; border: none;"
        )
        banner_layout.addWidget(icon_label)

        # Update message
        message_label = QLabel(
            f"TextWave update available: {self.app_current_version} → {self.app_latest_version}"
        )
        message_label.setStyleSheet(
            "background: transparent; border: none; font-size: 13px;"
        )
        banner_layout.addWidget(message_label, stretch=1)

        # Download button
        download_btn = QPushButton("Download Update")
        download_btn.setStyleSheet("""
            QPushButton {
                background-color: #4CAF50;
                color: white;
                border: none;
                border-radius: 3px;
                padding: 8px 15px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #45a049;
            }
        """)
        download_btn.clicked.connect(self.open_app_download)
        banner_layout.addWidget(download_btn)

        # Dismiss button
        dismiss_btn = QPushButton("×")
        dismiss_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                border: none;
                font-size: 20px;
                font-weight: bold;
                color: {colors["dismiss_btn"]};
                padding: 0px 5px;
            }}
            QPushButton:hover {{
                color: {colors["dismiss_btn_hover"]};
            }}
        """)
        dismiss_btn.clicked.connect(self.dismiss_app_update_banner)
        banner_layout.addWidget(dismiss_btn)

        return banner

    def dismiss_app_update_banner(self):
        """Hide the app update banner for this session."""
        if self.app_update_banner:
            self.app_update_banner.setVisible(False)
            self.app_update_dismissed = True

    def open_app_download(self):
        """Open the app download URL in the default browser."""
        if self.app_download_url:
            webbrowser.open(self.app_download_url)

    def create_resume_banner(self, resume_state: ConversionState):
        """Create the resume conversion banner widget."""
        colors = self.get_theme_colors()
        banner = QWidget()
        banner.setStyleSheet(f"""
            QWidget {{
                background-color: #FFF3E0;
                border: 1px solid #FF9800;
                border-radius: 5px;
                padding: 10px;
            }}
        """)

        banner_layout = QHBoxLayout()
        banner_layout.setContentsMargins(10, 10, 10, 10)
        banner.setLayout(banner_layout)

        # Info icon
        icon_label = QLabel("⏸️")
        icon_label.setStyleSheet(
            "font-size: 20px; background: transparent; border: none;"
        )
        banner_layout.addWidget(icon_label)

        # Resume message
        progress_pct = int(
            (resume_state.chunks_completed / resume_state.total_chunks) * 100
        )
        message_label = QLabel(
            f"Incomplete conversion found: {resume_state.pdf_name}\n"
            f"Progress: {resume_state.chunks_completed}/{resume_state.total_chunks} chunks ({progress_pct}%)"
        )
        message_label.setStyleSheet(
            "background: transparent; border: none; font-size: 13px; color: #333;"
        )
        banner_layout.addWidget(message_label, stretch=1)

        # Resume button
        resume_btn = QPushButton("Continue")
        resume_btn.setStyleSheet("""
            QPushButton {
                background-color: #FF9800;
                color: white;
                border: none;
                border-radius: 3px;
                padding: 8px 15px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #F57C00;
            }
        """)
        resume_btn.clicked.connect(self.resume_conversion)
        banner_layout.addWidget(resume_btn)

        # Discard button
        discard_btn = QPushButton("Discard")
        discard_btn.setStyleSheet("""
            QPushButton {
                background-color: #757575;
                color: white;
                border: none;
                border-radius: 3px;
                padding: 8px 15px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #616161;
            }
        """)
        discard_btn.clicked.connect(self.discard_resume_state)
        banner_layout.addWidget(discard_btn)

        return banner

    def resume_conversion(self):
        """Resume the incomplete conversion."""
        if self.resume_state:
            # Hide the banner
            if self.resume_banner:
                self.resume_banner.setVisible(False)

            # Start conversion with resume state
            self.pdf_path = self.resume_state.pdf_path

            # Update UI
            file_name = Path(self.pdf_path).name
            self.drop_label.setText(f"✅ Selected:\n{file_name}")
            self.convert_btn.setEnabled(True)

            # Start conversion immediately
            self.start_conversion_with_resume()

    def discard_resume_state(self):
        """Discard the saved resume state and cleanup."""
        if self.resume_state:
            # Delete temp directory
            temp_dir = Path(self.resume_state.temp_dir)
            if temp_dir.exists():
                try:
                    shutil.rmtree(temp_dir)
                except Exception:
                    pass

            # Delete state file
            delete_conversion_state()

            # Hide banner
            if self.resume_banner:
                self.resume_banner.setVisible(False)
                self.resume_banner.deleteLater()
                self.resume_banner = None

            self.resume_state = None
            self.status_text.setVisible(True)
            self.status_text.append("Previous conversion discarded.")

    def start_conversion_with_resume(self):
        """Start conversion with resume state."""
        # Show progress UI
        self.convert_btn.setEnabled(False)
        self.select_btn.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)
        self.status_text.setVisible(True)
        self.status_text.clear()

        # Show pause button
        self.pause_btn.setVisible(True)
        self.pause_btn.setText("Pause")
        self.pause_btn.setEnabled(True)

        # Start conversion thread with resume state
        self.thread = ConversionThread(
            self.resume_state.pdf_path,
            self.resume_state.output_path,
            resume_state=self.resume_state,
        )
        self.thread.progress.connect(self.update_progress)
        self.thread.status.connect(self.update_status)
        self.thread.paused.connect(self.handle_pause_state)
        self.thread.finished.connect(self.conversion_finished)
        self.thread.start()

        # Clear resume state after starting
        self.resume_state = None

    def app_update_check_complete(
        self, has_update, current_version, latest_version, download_url
    ):
        """Handle app update check completion."""
        if has_update and not self.app_update_dismissed:
            self.app_current_version = current_version
            self.app_latest_version = latest_version
            self.app_download_url = download_url

            # Create and show app update banner
            self.app_update_banner = self.create_app_update_banner()

            # Insert at top of layout (after edge-tts banner if present)
            central_widget = self.centralWidget()
            if central_widget:
                layout = central_widget.layout()
                if layout:
                    # Insert at position 1 if edge-tts banner exists, otherwise position 0
                    insert_pos = (
                        1
                        if self.update_banner and self.update_banner.isVisible()
                        else 0
                    )
                    layout.insertWidget(insert_pos, self.app_update_banner)

    def drag_enter_event(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            event.accept()
        else:
            event.ignore()

    def drop_event(self, event: QDropEvent):
        files = [u.toLocalFile() for u in event.mimeData().urls()]
        if files and files[0].lower().endswith(".pdf"):
            self.set_pdf(files[0])

    def select_pdf(self):
        # Get last input directory or default to Downloads
        default_dir = self.settings.value(
            "last_input_dir", str(Path.home() / "Downloads")
        )

        file_path, _ = QFileDialog.getOpenFileName(
            self, "Select PDF File", default_dir, "PDF Files (*.pdf)"
        )
        if file_path:
            # Save the directory for next time
            self.settings.setValue("last_input_dir", str(Path(file_path).parent))
            self.set_pdf(file_path)

    def set_pdf(self, path):
        self.pdf_path = path
        file_name = Path(path).name
        self.drop_label.setText(f"✅ Selected:\n{file_name}")
        self.convert_btn.setEnabled(True)
        self.status_text.clear()
        self.status_text.setVisible(False)
        self.progress_bar.setVisible(False)

    def convert(self):
        if not self.pdf_path:
            return

        # Ask where to save
        # Use last output directory if available, otherwise use input PDF's directory
        last_output_dir = self.settings.value("last_output_dir", None)
        if last_output_dir:
            default_path = Path(last_output_dir) / (Path(self.pdf_path).stem + ".mp3")
        else:
            default_path = Path(self.pdf_path).parent / (
                Path(self.pdf_path).stem + ".mp3"
            )

        output_path, _ = QFileDialog.getSaveFileName(
            self, "Save MP3 As", str(default_path), "MP3 Files (*.mp3)"
        )

        if not output_path:
            return

        # Save the output directory for next time
        self.settings.setValue("last_output_dir", str(Path(output_path).parent))

        # Disable UI during conversion
        self.convert_btn.setEnabled(False)
        self.select_btn.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)
        self.status_text.setVisible(True)
        self.status_text.clear()

        # Show pause button
        self.pause_btn.setVisible(True)
        self.pause_btn.setText("Pause")
        self.pause_btn.setEnabled(True)

        # Start conversion thread
        self.thread = ConversionThread(self.pdf_path, output_path)
        self.thread.progress.connect(self.update_progress)
        self.thread.status.connect(self.update_status)
        self.thread.paused.connect(self.handle_pause_state)
        self.thread.finished.connect(self.conversion_finished)
        self.thread.start()

    def update_progress(self, value, message):
        self.progress_bar.setValue(value)
        self.status_text.append(f"Progress: {message}")

    def update_status(self, message):
        self.status_text.append(message)

    def conversion_finished(self, success, message):
        self.status_text.append("\n" + message)
        self.convert_btn.setEnabled(True)
        self.select_btn.setEnabled(True)

        # Hide pause button when done
        self.pause_btn.setVisible(False)

        if success:
            self.progress_bar.setValue(100)

        # Ensure caffeinate is stopped
        if hasattr(self, "thread") and self.thread:
            self.thread.stop_caffeinate()

    def closeEvent(self, event):
        """Handle app close event - cleanup any running processes."""
        try:
            # Stop conversion thread and caffeinate
            if hasattr(self, "thread") and self.thread and self.thread.isRunning():
                # Cancel conversion and unblock if paused
                self.thread.request_cancel()

                if (
                    hasattr(self.thread, "caffeinate_process")
                    and self.thread.caffeinate_process
                ):
                    self.thread.stop_caffeinate()
                self.thread.requestInterruption()
                self.thread.quit()
                self.thread.wait(1000)

            # Disconnect and stop version check thread
            if hasattr(self, "version_check_thread") and self.version_check_thread:
                try:
                    self.version_check_thread.finished.disconnect()
                except Exception:
                    pass
                if self.version_check_thread.isRunning():
                    self.version_check_thread.requestInterruption()
                    self.version_check_thread.quit()
                    self.version_check_thread.wait(200)

            # Disconnect and stop app update check thread
            if (
                hasattr(self, "app_update_check_thread")
                and self.app_update_check_thread
            ):
                try:
                    self.app_update_check_thread.finished.disconnect()
                except Exception:
                    pass
                if self.app_update_check_thread.isRunning():
                    self.app_update_check_thread.requestInterruption()
                    self.app_update_check_thread.quit()
                    self.app_update_check_thread.wait(200)

            # Stop update thread if running
            if hasattr(self, "update_thread") and self.update_thread:
                try:
                    self.update_thread.status.disconnect()
                    self.update_thread.finished.disconnect()
                except Exception:
                    pass
                if self.update_thread.isRunning():
                    self.update_thread.requestInterruption()
                    self.update_thread.quit()
                    self.update_thread.wait(200)
        except Exception:
            pass  # Ignore any errors during cleanup

        event.accept()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = PDF2MP3App()
    window.show()
    sys.exit(app.exec())
