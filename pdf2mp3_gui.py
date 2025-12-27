import asyncio
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.request
import webbrowser
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

__version__ = "0.7.0"


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
    from pydub import AudioSegment
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
        QGroupBox,
        QHBoxLayout,
        QLabel,
        QMainWindow,
        QMessageBox,
        QProgressBar,
        QPushButton,
        QSlider,
        QSpinBox,
        QTextEdit,
        QVBoxLayout,
        QWidget,
    )
except ImportError as e:
    missing = str(e).split("'")[1] if "'" in str(e) else "dependencies"
    print("Installing required dependencies...")
    packages = ["edge-tts", "pypdf", "PyQt6", "pydub"]
    subprocess.check_call([sys.executable, "-m", "pip", "install"] + packages)
    print("Dependencies installed. Please run the script again.\n")
    sys.exit(0)

# Microsoft Azure Neural Voice (Free via edge-tts)
VOICE = "en-US-AvaMultilingualNeural"


def chunk_text_by_sentences(text, target_size=1000):
    """
    Split text into ~1000 char chunks at sentence boundaries.
    Returns: List of (chunk_index, chunk_text) tuples
    """
    chunks = []
    sentences = re.split(r"(?<=[.!?])\s+", text)  # Split on sentence boundaries

    current_chunk = ""
    chunk_index = 0

    for sentence in sentences:
        if len(current_chunk) + len(sentence) > target_size and current_chunk:
            chunks.append((chunk_index, current_chunk.strip()))
            chunk_index += 1
            current_chunk = sentence
        else:
            current_chunk += " " + sentence

    if current_chunk:  # Add final chunk
        chunks.append((chunk_index, current_chunk.strip()))

    return chunks


class PreferencesDialog(QDialog):
    """Dialog for configuring user preferences."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.settings = QSettings("TextWave", "PDF2MP3")
        self.setWindowTitle("Preferences")
        self.setModal(True)
        self.setMinimumWidth(500)

        self.init_ui()
        self.load_preferences()

    def init_ui(self):
        layout = QVBoxLayout()

        # Performance Group
        perf_group = QGroupBox("Performance Settings")
        perf_layout = QFormLayout()

        # Concurrent Workers
        workers_layout = QHBoxLayout()
        self.workers_slider = QSlider(Qt.Orientation.Horizontal)
        self.workers_slider.setMinimum(1)
        self.workers_slider.setMaximum(10)
        self.workers_slider.setValue(3)
        self.workers_slider.setTickPosition(QSlider.TickPosition.TicksBelow)
        self.workers_slider.setTickInterval(1)
        self.workers_label = QLabel("3")
        self.workers_slider.valueChanged.connect(
            lambda v: self.workers_label.setText(str(v))
        )
        workers_layout.addWidget(self.workers_slider)
        workers_layout.addWidget(self.workers_label)

        perf_layout.addRow("Concurrent TTS Workers:", workers_layout)

        # Max Retries
        self.retries_spinbox = QSpinBox()
        self.retries_spinbox.setMinimum(0)
        self.retries_spinbox.setMaximum(10)
        self.retries_spinbox.setValue(3)
        perf_layout.addRow("Max Retries per Chunk:", self.retries_spinbox)

        perf_group.setLayout(perf_layout)
        layout.addWidget(perf_group)

        # Storage Group
        storage_group = QGroupBox("Storage Settings")
        storage_layout = QFormLayout()

        # Temp Folder
        temp_layout = QHBoxLayout()
        self.temp_folder_label = QLabel("System Default")
        self.temp_folder_path = None
        temp_browse_btn = QPushButton("Browse...")
        temp_browse_btn.clicked.connect(self.browse_temp_folder)
        temp_reset_btn = QPushButton("Reset")
        temp_reset_btn.clicked.connect(self.reset_temp_folder)
        temp_layout.addWidget(self.temp_folder_label, stretch=1)
        temp_layout.addWidget(temp_browse_btn)
        temp_layout.addWidget(temp_reset_btn)

        storage_layout.addRow("Temporary Files Directory:", temp_layout)
        storage_group.setLayout(storage_layout)
        layout.addWidget(storage_group)

        # Info Label
        info_label = QLabel(
            "ℹ️ Higher worker count = faster conversion but may hit API rate limits.\n"
            "Retries help handle temporary network issues."
        )
        info_label.setStyleSheet("color: #666; font-size: 12px; padding: 10px;")
        info_label.setWordWrap(True)
        layout.addWidget(info_label)

        # Dialog Buttons
        button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        button_box.accepted.connect(self.save_and_accept)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

        self.setLayout(layout)

    def browse_temp_folder(self):
        """Browse for temporary folder."""
        folder = QFileDialog.getExistingDirectory(
            self, "Select Temporary Files Directory"
        )
        if folder:
            self.temp_folder_path = folder
            self.temp_folder_label.setText(folder)

    def reset_temp_folder(self):
        """Reset temporary folder to system default."""
        self.temp_folder_path = None
        self.temp_folder_label.setText("System Default")

    def load_preferences(self):
        """Load preferences from QSettings."""
        workers = self.settings.value("concurrent_workers", 3, type=int)
        retries = self.settings.value("max_retries", 3, type=int)
        temp_folder = self.settings.value("temp_folder", None)

        self.workers_slider.setValue(workers)
        self.workers_label.setText(str(workers))
        self.retries_spinbox.setValue(retries)

        if temp_folder:
            self.temp_folder_path = temp_folder
            self.temp_folder_label.setText(temp_folder)

    def save_and_accept(self):
        """Save preferences and close dialog."""
        self.settings.setValue("concurrent_workers", self.workers_slider.value())
        self.settings.setValue("max_retries", self.retries_spinbox.value())
        self.settings.setValue("temp_folder", self.temp_folder_path)
        self.accept()


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

    def __init__(self, pdf_path, output_path, settings):
        super().__init__()
        self.pdf_path = pdf_path
        self.output_path = output_path
        self.settings = settings
        self.caffeinate_process = None
        self.paused = False
        self.conversion_start_time = None

        # Get user preferences
        self.concurrent_workers = settings.value("concurrent_workers", 3, type=int)
        self.max_retries = settings.value("max_retries", 3, type=int)
        temp_folder = settings.value("temp_folder", None)
        self.temp_base = temp_folder if temp_folder else tempfile.gettempdir()

    def get_state_hash(self):
        """Generate unique hash for this conversion."""
        hash_input = f"{self.pdf_path}_{self.output_path}"
        return hashlib.md5(hash_input.encode()).hexdigest()[:12]

    def get_state_file_path(self):
        """Get path to state file for this conversion."""
        state_hash = self.get_state_hash()
        return Path(self.temp_base) / f"textwave_state_{state_hash}.json"

    def get_temp_dir(self):
        """Get temporary directory for chunk files."""
        state_hash = self.get_state_hash()
        return Path(self.temp_base) / f"textwave_{state_hash}"

    def load_state(self):
        """Load existing state file if it exists."""
        state_file = self.get_state_file_path()
        if not state_file.exists():
            return None

        try:
            with open(state_file, "r") as f:
                state = json.load(f)

            # Validate state matches current conversion
            if state.get("pdf_path") != str(self.pdf_path):
                return None
            if state.get("output_path") != str(self.output_path):
                return None

            return state
        except Exception as e:
            self.status.emit(f"Warning: Could not load state file: {str(e)}")
            return None

    def save_state(self, state):
        """Save conversion state to file."""
        state_file = self.get_state_file_path()

        try:
            # Atomic write: write to temp file, then rename
            temp_file = state_file.with_suffix(".tmp")
            with open(temp_file, "w") as f:
                json.dump(state, f, indent=2)
            temp_file.replace(state_file)
        except Exception as e:
            self.status.emit(f"Warning: Could not save state: {str(e)}")

    def cleanup_state(self, state):
        """Clean up state file and temporary chunk files."""
        try:
            # Delete chunk files
            temp_dir = Path(state.get("temp_dir", self.get_temp_dir()))
            if temp_dir.exists():
                for chunk_file in temp_dir.glob("chunk_*.mp3"):
                    chunk_file.unlink()
                temp_dir.rmdir()

            # Delete state file
            state_file = self.get_state_file_path()
            if state_file.exists():
                state_file.unlink()
        except Exception as e:
            self.status.emit(f"Warning: Could not cleanup temp files: {str(e)}")

    def merge_chunks(self, chunk_files, output_path):
        """Concatenate chunk MP3 files into final output."""
        self.status.emit("Merging audio chunks...")

        try:
            # Load all chunks in order
            segments = []
            for i in sorted(chunk_files.keys(), key=int):
                chunk_path = chunk_files[str(i)]
                if not Path(chunk_path).exists():
                    raise Exception(f"Chunk file missing: {chunk_path}")
                segments.append(AudioSegment.from_mp3(chunk_path))

            # Concatenate
            if not segments:
                raise Exception("No audio segments to merge")

            final_audio = segments[0]
            for segment in segments[1:]:
                final_audio += segment

            # Export
            final_audio.export(output_path, format="mp3", bitrate="128k")

            self.status.emit(f"Saved final MP3: {output_path}")
        except Exception as e:
            raise Exception(f"Failed to merge audio chunks: {str(e)}")

    async def convert_chunk_async(self, chunk_idx, chunk_text, temp_dir):
        """Convert single chunk to MP3 with retry logic (async)."""
        output_file = temp_dir / f"chunk_{chunk_idx}.mp3"

        for attempt in range(self.max_retries):
            try:
                communicate = edge_tts.Communicate(chunk_text, VOICE)
                with open(output_file, "wb") as f:
                    async for data_chunk in communicate.stream():
                        if data_chunk["type"] == "audio":
                            f.write(data_chunk["data"])

                return {
                    "chunk_idx": chunk_idx,
                    "file": str(output_file),
                    "success": True,
                }

            except Exception as e:
                if attempt < self.max_retries - 1:
                    # Exponential backoff: 1s, 2s, 4s, 8s...
                    wait_time = 2**attempt
                    self.status.emit(
                        f"Chunk {chunk_idx} failed (attempt {attempt + 1}/{self.max_retries}), "
                        f"retrying in {wait_time}s..."
                    )
                    await asyncio.sleep(wait_time)
                else:
                    # Final failure
                    self.status.emit(
                        f"Chunk {chunk_idx} failed after {self.max_retries} attempts: {str(e)}"
                    )
                    return {
                        "chunk_idx": chunk_idx,
                        "file": None,
                        "success": False,
                        "error": str(e),
                    }

    def convert_chunk(self, chunk_idx, chunk_text, state):
        """Wrapper to run async conversion in thread."""
        temp_dir = Path(state["temp_dir"])
        result = asyncio.run(self.convert_chunk_async(chunk_idx, chunk_text, temp_dir))

        if result["success"]:
            # Update progress
            completed = len(state["completed_chunks"]) + 1
            total = state["total_chunks"]
            progress_pct = int((completed / total) * 100)

            # Calculate ETA
            if self.conversion_start_time:
                elapsed = time.time() - self.conversion_start_time
                if progress_pct > 0:
                    total_time = elapsed / (progress_pct / 100)
                    remaining = total_time - elapsed
                    eta = f"ETA: {int(remaining // 60)}m {int(remaining % 60)}s"
                    self.progress.emit(
                        progress_pct, f"Chunk {completed}/{total} - {eta}"
                    )
                else:
                    self.progress.emit(progress_pct, f"Chunk {completed}/{total}")
            else:
                self.progress.emit(progress_pct, f"Chunk {completed}/{total}")

        return result

    def run(self):
        state = None
        try:
            # Start caffeinate to prevent macOS sleep during conversion
            self.caffeinate_process = subprocess.Popen(
                ["caffeinate", "-di"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

            # Load existing state (if resuming)
            state = self.load_state()

            if state:
                self.status.emit(
                    f"Resuming conversion ({len(state['completed_chunks'])}/{state['total_chunks']} chunks completed)..."
                )
            else:
                # Create new state
                state = {
                    "pdf_path": str(self.pdf_path),
                    "output_path": str(self.output_path),
                    "total_chunks": 0,
                    "completed_chunks": [],
                    "chunk_files": {},
                    "paused": False,
                    "created_at": datetime.now().isoformat(),
                    "temp_dir": str(self.get_temp_dir()),
                }

            # Extract text (skip if resuming with text in state)
            if not state.get("full_text"):
                self.status.emit("Extracting text from PDF...")
                text, total_pages = extract_and_clean_text(self.pdf_path)
                self.status.emit(
                    f"Extracted {len(text):,} characters from {total_pages} pages"
                )
                state["full_text"] = text
            else:
                text = state["full_text"]
                self.status.emit("Using cached extracted text...")

            # Create temp directory if needed
            temp_dir = Path(state["temp_dir"])
            temp_dir.mkdir(parents=True, exist_ok=True)

            # Chunk the text
            if state["total_chunks"] == 0:
                chunks = chunk_text_by_sentences(text)
                state["total_chunks"] = len(chunks)
                self.status.emit(f"Split into {len(chunks)} chunks for conversion")
                self.save_state(state)
            else:
                chunks = chunk_text_by_sentences(text)

            # Filter out completed chunks
            pending_chunks = [
                c for c in chunks if c[0] not in state["completed_chunks"]
            ]

            if not pending_chunks:
                self.status.emit("All chunks already converted, merging...")
            else:
                # Convert chunks in parallel
                self.status.emit(
                    f"Converting {len(pending_chunks)} chunks using {self.concurrent_workers} workers..."
                )

                with ThreadPoolExecutor(
                    max_workers=self.concurrent_workers
                ) as executor:
                    futures = {}

                    # Submit all pending chunks
                    for chunk_idx, chunk_text in pending_chunks:
                        if self.paused:
                            break
                        future = executor.submit(
                            self.convert_chunk, chunk_idx, chunk_text, state
                        )
                        futures[future] = chunk_idx

                    # Process completed chunks
                    failed_chunks = []
                    for future in as_completed(futures):
                        if self.paused:
                            self.status.emit("Paused. Progress saved.")
                            state["paused"] = True
                            self.save_state(state)
                            self.finished.emit(
                                False, "Conversion paused. You can resume later."
                            )
                            return

                        result = future.result()

                        if result["success"]:
                            # Mark chunk as completed
                            state["completed_chunks"].append(result["chunk_idx"])
                            state["chunk_files"][str(result["chunk_idx"])] = result[
                                "file"
                            ]
                            self.save_state(state)
                        else:
                            failed_chunks.append(result["chunk_idx"])

                    # Check for failures
                    if failed_chunks:
                        raise Exception(
                            f"Failed to convert {len(failed_chunks)} chunks: {failed_chunks[:5]}..."
                        )

            # Merge all chunk MP3s into final output
            if not self.paused:
                self.merge_chunks(state["chunk_files"], self.output_path)
                self.cleanup_state(state)
                self.finished.emit(True, f"Successfully saved to:\n{self.output_path}")

        except Exception as e:
            if state:
                self.save_state(state)
            self.finished.emit(False, f"Error: {str(e)}")
        finally:
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
        self.init_ui()

        # Check for orphaned conversions on startup
        self.detect_orphaned_conversions()

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

        # Menu Bar
        menubar = self.menuBar()
        file_menu = menubar.addMenu("File")

        preferences_action = file_menu.addAction("Preferences...")
        preferences_action.triggered.connect(self.show_preferences)

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

        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)

        # Pause/Resume button
        self.pause_btn = QPushButton("Pause")
        self.pause_btn.clicked.connect(self.toggle_pause)
        self.pause_btn.setVisible(False)  # Hidden until conversion starts
        self.pause_btn.setStyleSheet("""
            QPushButton {
                padding: 10px;
                font-size: 14px;
                background-color: #FF9800;
                color: white;
                border-radius: 5px;
            }
            QPushButton:hover:enabled {
                background-color: #F57C00;
            }
            QPushButton:disabled {
                background-color: #cccccc;
            }
        """)
        layout.addWidget(self.pause_btn)

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

        # Apply initial theme
        self.apply_theme()

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

    def detect_orphaned_conversions(self):
        """Detect incomplete conversions and prompt user to resume."""
        temp_folder = self.settings.value("temp_folder", None)
        temp_base = temp_folder if temp_folder else tempfile.gettempdir()
        temp_dir = Path(temp_base)

        # Find all state files
        state_files = list(temp_dir.glob("textwave_state_*.json"))

        if not state_files:
            return

        # Check each state file
        for state_file in state_files:
            try:
                # Check if file is old enough (>5 min = likely orphaned)
                file_age = time.time() - state_file.stat().st_mtime
                if file_age < 300:  # Skip recent files (< 5 min)
                    continue

                # Load state
                with open(state_file, "r") as f:
                    state = json.load(f)

                pdf_path = state.get("pdf_path")
                output_path = state.get("output_path")
                completed = len(state.get("completed_chunks", []))
                total = state.get("total_chunks", 0)

                if total == 0:
                    continue

                percentage = int((completed / total) * 100)

                # Prompt user to resume
                response = QMessageBox.question(
                    self,
                    "Resume Conversion?",
                    f"Found incomplete conversion:\n\n"
                    f"PDF: {Path(pdf_path).name}\n"
                    f"Progress: {completed}/{total} chunks ({percentage}%)\n\n"
                    f"Would you like to resume this conversion?",
                    QMessageBox.StandardButton.Yes
                    | QMessageBox.StandardButton.No
                    | QMessageBox.StandardButton.Ignore,
                )

                if response == QMessageBox.StandardButton.Yes:
                    # Resume conversion
                    self.pdf_path = pdf_path
                    self.set_pdf(pdf_path)
                    # Auto-start conversion with same output path
                    self.auto_resume_conversion(output_path)
                    break  # Only handle one at a time
                elif response == QMessageBox.StandardButton.No:
                    # Delete state file
                    state_file.unlink()
                    # Clean up temp dir
                    temp_conv_dir = Path(state.get("temp_dir"))
                    if temp_conv_dir.exists():
                        for chunk_file in temp_conv_dir.glob("chunk_*.mp3"):
                            chunk_file.unlink()
                        temp_conv_dir.rmdir()
                # Ignore means leave it for later

            except Exception as e:
                # Skip corrupted state files
                continue

    def auto_resume_conversion(self, output_path):
        """Automatically resume a conversion without asking for output path."""
        if not self.pdf_path:
            return

        # Disable UI during conversion
        self.convert_btn.setEnabled(False)
        self.select_btn.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)
        self.pause_btn.setVisible(True)
        self.pause_btn.setEnabled(True)
        self.pause_btn.setText("Pause")
        self.status_text.setVisible(True)
        self.status_text.clear()

        # Start conversion thread
        self.thread = ConversionThread(self.pdf_path, output_path, self.settings)
        self.thread.progress.connect(self.update_progress)
        self.thread.status.connect(self.update_status)
        self.thread.finished.connect(self.conversion_finished)
        self.conversion_start_time = time.time()
        self.thread.conversion_start_time = self.conversion_start_time
        self.thread.start()

    def show_preferences(self):
        """Show the preferences dialog."""
        dialog = PreferencesDialog(self)
        dialog.exec()

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

    def toggle_pause(self):
        """Toggle pause/resume for the conversion."""
        if hasattr(self, "thread") and self.thread.isRunning():
            if self.thread.paused:
                # Resume
                self.thread.paused = False
                self.pause_btn.setText("Pause")
                self.status_text.append("⏯️ Resuming conversion...")
            else:
                # Pause
                self.thread.paused = True
                self.pause_btn.setText("Resuming...")
                self.pause_btn.setEnabled(False)  # Disable until pause completes
                self.status_text.append("⏸️ Pausing after current chunk...")

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
        self.pause_btn.setVisible(True)  # Show pause button
        self.pause_btn.setEnabled(True)
        self.pause_btn.setText("Pause")
        self.status_text.setVisible(True)
        self.status_text.clear()

        # Start conversion thread
        self.thread = ConversionThread(self.pdf_path, output_path, self.settings)
        self.thread.progress.connect(self.update_progress)
        self.thread.status.connect(self.update_status)
        self.thread.finished.connect(self.conversion_finished)
        self.conversion_start_time = time.time()
        self.thread.conversion_start_time = self.conversion_start_time
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
        self.pause_btn.setVisible(False)  # Hide pause button when done

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
