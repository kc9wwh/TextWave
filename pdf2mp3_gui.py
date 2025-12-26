import asyncio
import json
import re
import subprocess
import sys
import urllib.request
import webbrowser
from pathlib import Path

__version__ = "0.6.0"


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
        QFileDialog,
        QHBoxLayout,
        QLabel,
        QMainWindow,
        QMessageBox,
        QProgressBar,
        QPushButton,
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

    def __init__(self, pdf_path, output_path):
        super().__init__()
        self.pdf_path = pdf_path
        self.output_path = output_path
        self.caffeinate_process = None

    def run(self):
        try:
            # Start caffeinate to prevent macOS sleep during conversion
            self.caffeinate_process = subprocess.Popen(
                ["caffeinate", "-di"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

            # Extract text
            self.status.emit("Extracting text from PDF...")
            text, total_pages = extract_and_clean_text(self.pdf_path)
            self.status.emit(
                f"Extracted {len(text):,} characters from {total_pages} pages"
            )

            # Convert to speech
            self.status.emit("Converting to speech...")

            def progress_callback(percent, msg):
                self.progress.emit(percent, msg)

            asyncio.run(text_to_speech_async(text, self.output_path, progress_callback))

            self.finished.emit(True, f"Successfully saved to:\n{self.output_path}")
        except Exception as e:
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

        # Start conversion thread
        self.thread = ConversionThread(self.pdf_path, output_path)
        self.thread.progress.connect(self.update_progress)
        self.thread.status.connect(self.update_status)
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
