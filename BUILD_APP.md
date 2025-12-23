# Building TextWave

This guide covers how to build and distribute TextWave as a macOS application.

## Quick Start for Users

Download the latest release from GitHub:
- **DMG Installer**: `TextWave-{version}.dmg` - Drag to Applications folder
- **Direct App**: `TextWave.app.zip` - Extract and run directly

## For Developers

### Option 1: Run from Source (Development)

```bash
# Install dependencies
python3 -m pip install -r requirements-test.txt

# Run the GUI
python3 pdf2mp3_gui.py
```

The app will auto-install runtime dependencies (PyQt6, edge-tts, pypdf) on first run if missing.

### Option 2: Build Locally

#### Prerequisites

```bash
# Install py2app
python3 -m pip install py2app edge-tts pypdf PyQt6
```

#### Build the .app Bundle

```bash
# Clean previous builds
rm -rf build dist

# Build
python3 setup.py py2app
```

The app will be created in `dist/TextWave.app`

#### Test the Built App

```bash
# Run directly
open dist/TextWave.app

# Or copy to Applications
cp -r dist/TextWave.app /Applications/
```

#### Create a DMG (Optional)

```bash
# Using the build script
.github/scripts/create-dmg.sh 0.5.2

# Or manually with hdiutil
hdiutil create -volname "TextWave" -srcfolder dist/TextWave.app -ov -format UDZO TextWave.dmg
```

## Automated Release Process (Recommended)

TextWave uses GitHub Actions for automated building and releasing.

### How to Release a New Version

1. **Update the version** in `pdf2mp3_gui.py`:
   ```python
   __version__ = "0.5.3"  # Increment version
   ```

2. **Commit and push to main**:
   ```bash
   git add pdf2mp3_gui.py
   git commit -m "Bump version to 0.5.3"
   git push origin main
   ```

3. **GitHub Actions automatically**:
   - Checks if version tag exists
   - Builds the macOS app
   - Creates DMG installer
   - Creates .app.zip
   - Creates GitHub release with tag `v0.5.3`
   - Attaches both DMG and .app.zip to release

### CI/CD Pipeline

**PR Testing** (`.github/workflows/pr-tests.yml`):
- Runs on every PR and push to main
- Linting with flake8
- Full test suite with coverage
- Test builds the app
- Uploads coverage to Codecov

**Release Build** (`.github/workflows/release.yml`):
- Triggers on push to main (excludes markdown changes)
- Extracts version from `__version__`
- Only builds if version tag doesn't exist
- Creates professional DMG with Applications folder shortcut
- Auto-publishes GitHub release

## Project Structure

```
TextWave/
├── pdf2mp3_gui.py          # Main application code
├── setup.py                # py2app build configuration
├── textwave.icns           # macOS app icon
├── textwave_logo.png       # Logo image
├── requirements-test.txt   # Test dependencies
├── tests/                  # Test suite
│   ├── test_pdf_extraction.py
│   ├── test_version_checking.py
│   ├── test_app_updates.py
│   ├── test_gui_components.py
│   └── test_integration.py
└── .github/
    ├── workflows/
    │   ├── pr-tests.yml    # PR testing workflow
    │   └── release.yml     # Release workflow
    └── scripts/
        ├── build-app.sh    # Build script
        └── create-dmg.sh   # DMG creation script
```

## Testing

See [TESTING.md](TESTING.md) for detailed testing documentation.

### Run Tests Locally

```bash
# Install test dependencies
python3 -m pip install -r requirements-test.txt

# Run all tests
python3 -m pytest

# Run with coverage
python3 -m pytest --cov=pdf2mp3_gui --cov-report=html
open htmlcov/index.html
```

## How to Use the App

1. **Launch the app** (double-click TextWave.app)
2. **Drag & drop a PDF** into the window (or click "Select PDF")
3. **Click "Convert to MP3"**
4. **Choose where to save** the MP3 file
5. **Wait** for conversion (progress bar shows status)
6. **Done!** The MP3 is saved and ready to use

## Features

- Simple drag-and-drop interface
- Clean, branded TextWave interface
- Progress bar with status updates
- Auto-installs dependencies on first run
- Shows file size and completion percentage
- Uses high-quality Microsoft Azure voice (free via edge-tts)
- Automatic update notifications
- Sleep prevention during conversion

## Build Configuration

The `setup.py` file configures the py2app build:

- **App Bundle Name**: TextWave
- **Bundle ID**: com.textwave.converter
- **Icon**: textwave.icns (automatically included if present)
- **Packages**: PyQt6, edge-tts, pypdf
- **Version**: Extracted from `__version__` in pdf2mp3_gui.py
- **High Resolution**: Enabled for Retina displays

## Troubleshooting

### "Permission denied" when opening .app

```bash
xattr -cr /Applications/TextWave.app
```

### App won't open

Try running from terminal to see error messages:

```bash
open -a TextWave
# Or run the binary directly:
/Applications/TextWave.app/Contents/MacOS/TextWave
```

### Build fails locally

```bash
# Clean and retry
rm -rf build dist
python3 setup.py py2app
```

### Dependencies not found in built app

The app should bundle all dependencies. If issues occur, verify they're listed in setup.py:

```python
OPTIONS = {
    "packages": ["edge_tts", "pypdf", "PyQt6"],
    ...
}
```

## Distribution

### For End Users

Direct them to the [latest GitHub release](https://github.com/yourusername/TextWave/releases/latest):

1. Download `TextWave-{version}.dmg`
2. Open the DMG
3. Drag TextWave to Applications folder
4. Launch from Applications

### For Developers

1. Clone the repository
2. Install dependencies: `pip3 install -r requirements-test.txt`
3. Run tests: `pytest`
4. Run from source: `python3 pdf2mp3_gui.py`
5. Build: `python3 setup.py py2app`

## Requirements

- **Development**: Python 3.11+, macOS 10.15+
- **Built App**: macOS 10.15+, internet connection for TTS
- **Building**: py2app, PyQt6, edge-tts, pypdf
