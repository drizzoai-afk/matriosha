# Matriosha Dependency Matrix

`matriosha init` (P6.9) validates and optionally installs runtime dependencies required by semantic decoding paths.

## Supported Platforms

- Ubuntu **20.04+** (APT)
- Debian **10+** (APT)
- macOS **11+** (Homebrew)
- Other platforms are detected but treated as unsupported for automatic installation; manual guidance is provided.

## Python Runtime Requirement

- Required Python version: **>= 3.11**

## System Dependencies

| Canonical dependency | Purpose | Ubuntu/Debian package | macOS (brew) |
|---|---|---|---|
| `tesseract-ocr` | OCR for image/scanned document extraction | `tesseract-ocr` | `tesseract` |
| `poppler-utils` | PDF tooling (`pdfinfo`, `pdftotext`, `pdftoppm`) | `poppler-utils` | `poppler` |
| `libmagic1` | MIME/file-type detection support | `libmagic1` | `libmagic` |

## Python Dependencies

- Python dependencies are sourced from repository `requirements.txt`.
- `matriosha init` only installs Python packages that are present in that file.

## Init Command Behavior

1. Generate system report (`get_system_report`) with OS, Python, system-package, and Python-package status.
2. Present missing dependencies.
3. Prompt per dependency for approval (system + Python).
4. Install approved dependencies only.
5. Verify each installation.
6. Write:
   - setup attempt log: `~/.matriosha/setup.log`
   - final report: `~/.matriosha/init_report.md`

### Non-Interactive / CI

Use one of the following flags to bypass prompts:

```bash
matriosha init --yes
matriosha init --auto-approve
```

If missing dependencies are detected without those flags in non-TTY mode, command exits with actionable guidance.

## Safety Constraints

- System package allowlist: `tesseract-ocr`, `poppler-utils`, `libmagic1`
- Python package allowlist: packages from `requirements.txt`
- Installation timeout: **300 seconds** per attempt
- No arbitrary shell command execution

## Manual Fallback Commands

### Ubuntu / Debian

```bash
sudo apt-get update
sudo apt-get install -y tesseract-ocr poppler-utils libmagic1
python -m pip install -r requirements.txt
```

### macOS

```bash
brew install tesseract poppler libmagic
python -m pip install -r requirements.txt
```

If your platform is unsupported, install equivalent packages via your package manager and re-run `matriosha init`.

## Semantic interpreter support

Matriosha recall returns bounded agent-ready semantic JSON.

Rich built-in extraction currently supports:

- `.txt`
- `.md`, `.markdown`
- `.json`
- `.csv`, `.tsv`
- `.pdf`
- `.png`, `.jpg`, `.jpeg`, `.bmp`, `.gif`, `.webp`, `.tiff`, `.tif`
- `.docx`
- `.xlsx`

Legacy or proprietary formats such as `.doc`, `.odt`, `.xls`, `.msg`, `.dwg`, and archives such as `.zip`, `.tar`, `.gz` are handled as safe binary fallback envelopes unless a dedicated decoder plugin is installed.

Fallback envelopes are still valid interpreter output. They preserve safe metadata, bounded previews, and warnings, but they do not claim full text/table extraction.
