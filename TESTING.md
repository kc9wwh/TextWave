# TextWave Testing & CI/CD Documentation

## Test Suite Overview

TextWave includes a comprehensive test suite with unit tests, integration tests, and GUI tests covering all major functionality.

### Test Coverage Areas

1. **PDF Extraction** (`test_pdf_extraction.py`)
   - Text extraction from valid PDFs
   - Page number removal
   - Page count accuracy
   - Error handling

2. **Version Checking** (`test_version_checking.py`)
   - edge-tts update detection
   - PyPI API integration
   - Network error handling
   - Version comparison logic

3. **App Updates** (`test_app_updates.py`)
   - GitHub release checking
   - Version tag parsing
   - DMG asset detection
   - API error handling

4. **GUI Components** (`test_gui_components.py`)
   - Window initialization
   - Button state management
   - Banner creation and dismissal
   - Resource path resolution

5. **Integration Tests** (`test_integration.py`)
   - Sleep prevention (caffeinate)
   - Thread lifecycle management
   - Signal emission
   - Error recovery

## Running Tests Locally

### Install Test Dependencies

```bash
python3 -m pip install -r requirements-test.txt
```

### Run All Tests

```bash
python3 -m pytest
```

### Run Specific Test Categories

```bash
# Unit tests only
python3 -m pytest -m unit

# Integration tests only
python3 -m pytest -m integration

# GUI tests only
python3 -m pytest -m gui

# Specific test file
python3 -m pytest tests/test_pdf_extraction.py -v
```

### Generate Coverage Report

```bash
# Terminal report
python3 -m pytest --cov=pdf2mp3_gui --cov-report=term-missing

# HTML report (opens in browser)
python3 -m pytest --cov=pdf2mp3_gui --cov-report=html
open htmlcov/index.html
```

## CI/CD Pipeline

### PR Testing Workflow

**Trigger:** Every pull request to `main` branch

**Steps:**
1. Checkout code
2. Set up Python 3.11
3. Install dependencies
4. Run linting (flake8)
5. Run test suite with coverage
6. Upload coverage to Codecov
7. Test app builds successfully

**Location:** `.github/workflows/pr-tests.yml`

### Release Workflow

**Trigger:** Push to `main` branch (excludes markdown and docs)

**Steps:**
1. Extract version from `__version__` in code
2. Check if version tag already exists
3. If new version:
   - Build macOS .app bundle
   - Create DMG installer
   - Create .app.zip for direct download
   - Create GitHub release with assets
   - Auto-tag with version number

**Location:** `.github/workflows/release.yml`

## Release Process

### Automated Release

1. **Update version** in `pdf2mp3_gui.py`:
   ```python
   __version__ = "1.0.1"  # Increment version
   ```

2. **Commit and push to main**:
   ```bash
   git add pdf2mp3_gui.py
   git commit -m "Bump version to 1.0.1"
   git push origin main
   ```

3. **GitHub Actions automatically**:
   - Builds the app
   - Creates DMG
   - Creates release with tag `v1.0.1`
   - Attaches both DMG and .app.zip

### Manual Build (Local Testing)

```bash
# Build app
.github/scripts/build-app.sh

# Create DMG
.github/scripts/create-dmg.sh 1.0.0

# Result:
# - dist/TextWave.app
# - dist/TextWave.app.zip
# - TextWave-1.0.0.dmg
```

## Build Scripts

### `build-app.sh`

- Cleans previous builds
- Runs `python setup.py py2app`
- Creates .app.zip for distribution
- Verifies build succeeded

### `create-dmg.sh`

- Uses `create-dmg` if available (better UI)
- Falls back to `hdiutil` (macOS built-in)
- Creates professional installer DMG
- Includes Applications folder shortcut

## Test Best Practices

1. **Mock External Calls**: All network requests and subprocess calls should be mocked
2. **Use Fixtures**: Leverage pytest fixtures for common setup (sample PDFs, QApplication)
3. **Test Isolation**: Each test should be independent
4. **Signal Testing**: Use `qtbot.waitSignal()` for Qt thread testing
5. **Coverage Goals**: Aim for 80%+ coverage on core functionality

## Continuous Integration

### GitHub Actions Runners

- **Platform:** macOS-latest
- **Python:** 3.11
- **Test Duration:** ~3-5 minutes
- **Build Duration:** ~5-10 minutes

### Coverage Reporting

Coverage reports are automatically uploaded to Codecov (if configured) and can be viewed:
- In PR comments
- On Codecov dashboard
- In local HTML reports

## Troubleshooting

### Tests Fail Locally

```bash
# Ensure dependencies are installed
python3 -m pip install -r requirements-test.txt

# Clear pytest cache
python3 -m pytest --cache-clear

# Run with verbose output
python3 -m pytest -vv
```

### CI Build Fails

1. Check GitHub Actions logs
2. Verify version is properly incremented
3. Ensure all tests pass locally first
4. Check that scripts are executable

### DMG Creation Fails

- GitHub runners may not have `create-dmg` installed
- Workflow falls back to `hdiutil` automatically
- Both methods produce valid DMGs

## Future Enhancements

- [ ] Add performance benchmarks
- [ ] Add screenshot tests
- [ ] Add accessibility tests
- [ ] Expand edge case coverage
- [ ] Add mutation testing
