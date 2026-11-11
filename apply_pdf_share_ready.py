#!/usr/bin/env python3
"""Apply share-ready PDF layout to sb.py (run from repo root)."""
from pathlib import Path
import textwrap

path = Path("sb.py")
text = path.read_text(encoding="utf-8")

old_ver = 'SHUF_VERSION = "1.98A"'
new_ver = (
    'SHUF_VERSION = "1.98A"\n\n'
    '# Display name used on PDF exports and formal summaries\n'
    'TOURNAMENT_DISPLAY_NAME = "Ms. Ethel\'s Shuffleboard Tournament"'
)
if "TOURNAMENT_DISPLAY_NAME" not in text:
    if old_ver not in text:
        raise SystemExit("Could not find SHUF_VERSION line to update")
    text = text.replace(old_ver, new_ver, 1)

start_token = "def _build_pdf_styles():"
end_token = "\ndef display_final_rankings(champion):"
if start_token not in text:
    raise SystemExit("Could not find _build_pdf_styles")
if end_token not in text:
    raise SystemExit("Could not find display_final_rankings")

# Download the full section from the committed sb_pdf blob is not available.
# Instead embed via companion file pdf_export_section.py if present.
section_path = Path(__file__).with_name("pdf_export_section.py")
if not section_path.exists():
    raise SystemExit(
        "Missing pdf_export_section.py next to this script.\n"
        "Pull the latest feature/pdf-share-ready branch after it is updated."
    )
new_section = section_path.read_text(encoding="utf-8")
if not new_section.startswith("def _build_pdf_styles"):
    raise SystemExit("pdf_export_section.py does not look like the PDF section")

start = text.index(start_token)
end = text.index(end_token)
text = text[:start] + new_section + text[end:]
path.write_text(text, encoding="utf-8")
print("Applied share-ready PDF layout to sb.py")
print("Export PDF from a completed tournament to verify.")
