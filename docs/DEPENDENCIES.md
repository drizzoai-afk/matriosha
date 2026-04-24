# Dependency Requirements

This document defines runtime dependencies used by Matriosha and referenced by the `matriosha init` setup flow.

## Python Version

- Required Python version: **>= 3.9**
- Recommended for this repository: Python 3.11 (aligned with current development tooling).

## System Packages

### `tesseract-ocr`
- Purpose: OCR extraction for images and scanned PDFs.
- Used by semantic decoding paths that need text extraction from non-text-native sources.

### `poppler-utils`
- Purpose: PDF rendering and conversion utilities.
- Used when conversion or page rendering workflows are required for richer PDF processing.

### `libmagic1`
- Purpose: file-type detection via libmagic.
- Enables robust MIME inference for content routing and decoder selection.

## Python Packages

- Python package dependencies are maintained in the repository root `requirements.txt`.
- The `matriosha init` command should validate and, when permitted, install missing Python dependencies from that file.

## Platform-Specific Installation Notes

### Ubuntu / Debian

```bash
sudo apt-get update
sudo apt-get install -y tesseract-ocr poppler-utils libmagic1
python3 -m pip install -r requirements.txt
```

### macOS (Homebrew)

```bash
brew install tesseract poppler libmagic
python3 -m pip install -r requirements.txt
```

### Other Linux / Unix Systems

- Install equivalents of:
  - Tesseract OCR
  - Poppler utilities
  - libmagic runtime/library
- Use your system package manager (e.g., `dnf`, `yum`, `pacman`, `zypper`) and then install Python requirements via pip.

### Windows

- Install Tesseract OCR and Poppler binaries from their official distribution channels.
- Ensure executables are available on `PATH`.
- Install Python dependencies with:

```bash
py -m pip install -r requirements.txt
```

## Troubleshooting

### `tesseract` not found
- Symptom: OCR-related commands fail with missing executable errors.
- Fix:
  1. Install `tesseract-ocr` (or platform equivalent).
  2. Confirm with `tesseract --version`.
  3. Add Tesseract binary location to `PATH` if needed.

### `libmagic`/MIME detection errors
- Symptom: file type detection fails or `python-magic` raises shared-library errors.
- Fix:
  1. Install `libmagic1` (or equivalent package containing libmagic).
  2. Reinstall Python dependencies: `python3 -m pip install -r requirements.txt`.

### PDF conversion/rendering failures
- Symptom: PDF extraction/conversion tools fail at runtime.
- Fix:
  1. Install `poppler-utils` (or Poppler equivalent).
  2. Verify with `pdftoppm -v` or `pdfinfo -v`.

### Python dependency conflicts
- Symptom: pip resolver errors or incompatible package versions.
- Fix:
  1. Use a clean virtual environment.
  2. Upgrade pip/setuptools/wheel.
  3. Re-run `pip install -r requirements.txt`.

### Permission issues during installation
- Symptom: package installation fails due to permission denied.
- Fix:
  1. Prefer virtual environments for Python dependencies.
  2. For system packages, use elevated privileges as appropriate (`sudo`).
  3. Re-run `matriosha init` after permissions are corrected.
