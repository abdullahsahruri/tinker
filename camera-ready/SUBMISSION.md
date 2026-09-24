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

## Known issues NOT fixed

These are real and will be permanent once published. None blocks upload.

- **`main.tex:267`** — `\mathbb{1}` in the neuron equation renders as a wrong
  glyph (amsfonts has no blackboard-bold digits). Needs `\mathds{1}` (dsfont),
  `\mathbbm{1}` (bbm), or `\mathbf{1}`.
- **`main.tex:331`** — `~700` renders as a non-breaking space, so the text reads
  "1.3 K flops, 700 of them" and loses the "about". Needs `$\sim$700`.
- **`main.tex:265, 288, 306`** — `\paragraph{Neuron function.}` prints as
  "a) Neuron function.:" — IEEEtran adds the colon, so the trailing period
  double-punctuates. Three occurrences.
- Table I reports sign-off as "DRC / LVS / antenna" but §IV-B text claims four
  clean checks including KLayout XOR.
- Mixed British/American spelling (`synthesises`/`synthesized`,
  `vectorised` in text vs `vectorized` in Table I, `binarisation`,
  `optimisation`, `behavioural`).
- Disclosure items from the full review: the 1.98 mW unbucketed remainder in
  §V-B's power enumeration (Fig. 5 plots it as "Other", the text does not
  mention it); the `u_tile` bucket including the Wishbone wrapper; the 47-of-1210
  interior-net activity match rate; the power VCD coming from the Phase-3.5 7×7
  workload rather than the deployed 14×14 network; and Table III's 73.81 MHz
  slow-corner tile Fmax against the 100 MHz claim.
