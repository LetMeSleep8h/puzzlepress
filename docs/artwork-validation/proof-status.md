# Physical proof status

One line per proof. Status is one of: not started, ordered but not received,
received but not inspected, inspected with findings, approved. Only the author
changes a status, from evidence (an order, a printed copy, a filled checklist).
PuzzlePress never orders, pays for or inspects a proof.

| Proof | What it is | Checklist | Status | Since | Evidence |
| --- | --- | --- | --- | --- | --- |
| Validation proof, no bleed | 41-page NOT FOR SALE interior and cover from the approved historical drawings (`tests/proof_project.py`), 8.5 x 11 in, white | [proof-checklist.md](proof-checklist.md) | not started | 2026-11-05 | none: not ordered |
| Full-bleed proof | A NOT FOR SALE bleed interior (`paperback-8.5x11-bleed`) with filled and contained drawings, recto and verso | [bleed-proof-checklist.md](bleed-proof-checklist.md) | not started | 2026-11-05 | none: not ordered |
| Release-candidate demo (Interval 10) | The technical demonstration package (docs/release-readiness.md) | proof-checklist.md and bleed-proof-checklist.md | not started | 2026-11-05 | none: not ordered |

Until a row reads "inspected with findings" or "approved", every print-quality
statement in this repository is digital evidence only.

## How to obtain a proof (the author, by hand)

1. Build the proof package: `python tests/proof_project.py docs/artwork-validation/approved.json ORIGINALS OUT`
   (ORIGINALS verified with `tests/artwork_fetch.py`), or produce the release-candidate
   demo in Studio.
2. In KDP, create a paperback draft (not published), choose the matching trim, paper,
   black ink and the bleed setting the package states, upload `interior.pdf` and
   `cover.pdf`, and review them in KDP's Previewer.
3. Order a printed proof from the draft yourself (KDP charges for it and marks proof
   copies as not for resale). Record "ordered but not received" with the date here.
4. When it arrives, record "received", then fill the checklist in daylight beside the
   PDF at 100 %, and record the outcome.
