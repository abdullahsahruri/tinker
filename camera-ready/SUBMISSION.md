# SOCC 2026 camera-ready — submission steps

Regenerate everything with `make dist`. Output lands in `submission/`:

| File | What it is |
|---|---|
| `socc2026_tinker_camera_ready.pdf` | the paper — **run through PDF eXpress before uploading** |
| `socc2026_tinker_camera_ready_source.zip` | self-contained LaTeX sources (`main.tex`, `refs.bib`, `main.bbl`, `tables/`, `figures/`) |

The archive ships `main.bbl` (publishers do not run BibTeX) and its
`\graphicspath` points at its own `figures/` copy. `make dist` compiles the
archive standalone and fails if it does not match the upload PDF's page count.

## Blocking — do these first

1. **Copyright notice.** `main.tex` still has the `\IEEEpubid` block commented
   out, just after `\begin{document}`. Paste the ISBN/copyright line from the
   acceptance e-mail, uncomment, `make dist` again. A camera-ready PDF without
   it will be rejected. Placement is pre-verified: it sets at the foot of page 1
   column 1 and the paper stays at 6 pages.
2. **Author e-mails.** `abdullah.sahruri1@louisiana.edu` and
   `martin.margala@louisiana.edu` were inferred from the institution, never
   confirmed. Fix or confirm before upload — these get published.
3. **Author list and order.** Currently Sahruri, Margala.

## Upload sequence

1. Fix the three items above, `make dist`.
2. **IEEE PDF eXpress** — create/validate against the SOCC 2026 conference ID
   from the acceptance e-mail. Upload `socc2026_tinker_camera_ready.pdf`;
   download the eXpress-approved PDF it returns.
3. **Upload the eXpress-approved PDF** to the submission site, not the local
   build. Rename to the paper ID if the site asks for it.
4. **eIEEE Copyright Form (eCF)** — sign; affiliations must match the paper.
   *Done 2026-08-01* (receipt: `CopyrightReceipt (3).pdf` in Downloads).
5. **Source archive** — upload `..._source.zip` only if the site asks for
   sources.
6. **Registration** — at least one author must be registered for the paper to
   appear in the proceedings.

## Pre-verified mechanics

Checked on the current build; re-check after any edit.

- 6 pages (`make` hard-fails above 6).
- US Letter, 612 × 792 pt.
- All fonts embedded, no Type 3.
- Figures: 5 vector, 1 raster (`fig3_layout.pdf`, 300 dpi).
- No undefined citations or references; no overfull boxes.
- 21 references, all cited.
- No LLM-tooling strings (`make` fails if any appear).

## Known issues — resolved 2026-09-24

All fixed in `main.tex` / `tables/` / `../paper/figures/fig4_power_breakdown.py`;
still 6 pages, no overfull boxes. The pre-fix bundle is kept in
`submission-2026-08-01/` (likely the version uploaded with the eCF).

- `\mathbb{1}` → `\mathbf{1}`; `~700` → `$\sim$700`; `\paragraph` double
  punctuation (already fixed before this pass).
- Table I sign-off row now lists DRC / LVS / XOR / antenna (4 checks),
  matching §V-B; columns made ragged-right.
- Spelling unified to American (IEEE style).
- §VI-B now discloses: the 1.98 mW (4.2 %) unbucketed remainder ("Other" in
  Fig. 6); the tile bucket includes its Wishbone wrapper; 47 of 1 210 interior
  VCD signals matched (≤ ~5 % combinational under-count); the activity trace is
  the 7×7 deployment's testbench on the byte-identical netlist.
- §VI-D now states neither standalone tile meets 100 MHz at the slow corner
  (73.81 / 77.51 MHz); 100 MHz holds at TT.
- Fig. 6: removed the 47.21 x-tick that collided with "40"; "Other" no longer
  shares GPIO's color.
- To stay at 6 pages: dropped the sign-off recap in §VII (repeated in §V-B,
  abstract, conclusion) and the last sentence of §II-B (restated §III-B).

Still open: the ISBN/copyright line (blocking item 1) and the acknowledgment
TODO — neither can be filled without the acceptance e-mail / grant info.
