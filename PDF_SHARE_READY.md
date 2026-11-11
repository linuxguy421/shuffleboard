# Share-ready PDF layout

This branch updates the tournament results PDF to match the official share-ready summary design.

## Apply the change

From the repo root on this branch:

```bash
python3 apply_pdf_share_ready.py
git add sb.py apply_pdf_share_ready.py PDF_SHARE_READY.md
git commit -m "Restyle PDF export to share-ready official summary layout"
```

Or apply the unified diff:

```bash
git apply pdf_share_ready.patch
```

## What changes

- Tournament name header (`TOURNAMENT_DISPLAY_NAME`)
- Official summary subtitle with date
- Champions card (place, wins, losses, win rate)
- Metrics strip: teams, players, matches, total time, avg match time
- Body: Final Standings | Match Breakdown, Scoring | Notes
- Match history table styling
- Footer: name · generated timestamp · version

## Test

1. Run a tournament (or open a completed replay)
2. Export PDF
3. Compare to the share-ready example
