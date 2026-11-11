#!/usr/bin/env python3
"""Apply share-ready PDF layout to sb.py (run from repo root on feature/pdf-share-ready)."""
from pathlib import Path

path = Path("sb.py")
text = path.read_text(encoding="utf-8")

# 1) Tournament display name constant
old_ver = 'SHUF_VERSION = "1.98A"'
new_ver = '''SHUF_VERSION = "1.98A"

# Display name used on PDF exports and formal summaries
TOURNAMENT_DISPLAY_NAME = "Ms. Ethel's Shuffleboard Tournament"'''
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

# Embedded section loaded from project artifacts — see repo note if this is a stub.
# Prefer: copy artifacts/apply_pdf_share_ready.py from the Grok project folder,
# or copy artifacts/sb_pdf_share_ready.py over sb.py directly.

import urllib.request
import sys

def _fail_with_help():
    print("This copy of apply_pdf_share_ready.py on GitHub is incomplete.")
    print()
    print("Quickest fix — use the full sb.py from the project folder:")
    print("  cp /path/to/artifacts/sb_pdf_share_ready.py ./sb.py")
    print("  git add sb.py && git commit -m 'Restyle PDF export to share-ready layout'")
    print()
    print("Or copy the full apply script from the Grok project artifacts folder")
    print("over this file, then re-run: python3 apply_pdf_share_ready.py")
    sys.exit(1)

_fail_with_help()
