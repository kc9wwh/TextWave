"""
Setup script to create a standalone macOS .app bundle for TextWave

Usage:
    python3 setup.py py2app
"""

import os
import sys

from setuptools import setup

# Import version from main file
sys.path.insert(0, os.path.dirname(__file__))
from pdf2mp3_gui import __version__

APP = ["pdf2mp3_gui.py"]

# Include logo files in the app bundle
DATA_FILES = []
if os.path.exists("textwave_logo.png"):
    DATA_FILES.append("textwave_logo.png")
if os.path.exists("textwave_logo.svg"):
    DATA_FILES.append("textwave_logo.svg")

# Check if icon file exists
icon_file = "textwave.icns" if os.path.exists("textwave.icns") else None

OPTIONS = {
    "argv_emulation": False,
    "packages": ["edge_tts", "pypdf", "PyQt6"],
    "iconfile": icon_file,
    "plist": {
        "CFBundleName": "TextWave",
        "CFBundleDisplayName": "TextWave",
        "CFBundleGetInfoString": "Convert PDF files to MP3 audio",
        "CFBundleIdentifier": "com.textwave.converter",
        "CFBundleVersion": __version__,
        "CFBundleShortVersionString": __version__,
        "NSHumanReadableCopyright": "2025",
        "NSHighResolutionCapable": True,
    },
}

setup(
    app=APP,
    name="TextWave",
    data_files=DATA_FILES,
    options={"py2app": OPTIONS},
    setup_requires=["py2app"],
)
