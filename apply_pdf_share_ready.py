#!/usr/bin/env python3
"""Apply share-ready PDF layout to sb.py (run from repo root on feature/pdf-share-ready)."""
from pathlib import Path

path = Path("sb.py")
text = path.read_text(encoding="utf-8")

# 1) Tournament display name constant
old_ver = 'SHUF_VERSION = "1.98A"'
new_ver = 'SHUF_VERSION = "1.98A"\n\n# Display name used on PDF exports and formal summaries\nTOURNAMENT_DISPLAY_NAME = "Ms. Ethel\'s Shuffleboard Tournament"'
if "TOURNAMENT_DISPLAY_NAME" not in text:
    if old_ver not in text:
        raise SystemExit("Could not find SHUF_VERSION line to update")
    text = text.replace(old_ver, new_ver, 1)

# 2) Replace PDF generation section
start_token = "def _build_pdf_styles():"
end_token = "\ndef display_final_rankings(champion):"
if start_token not in text:
    raise SystemExit("Could not find _build_pdf_styles")
if end_token not in text:
    raise SystemExit("Could not find display_final_rankings")

print("NOTE: Full section is in artifacts/apply_pdf_share_ready.py on the project machine.")
print("Copy that file over this placeholder, then re-run.")
raise SystemExit(1)
