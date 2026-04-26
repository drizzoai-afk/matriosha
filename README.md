# Matriosha

Matriosha API service.

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
