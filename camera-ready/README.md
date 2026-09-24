# Camera-ready tree — IEEE SOCC 2026 (TINKER)

De-anonymized copy of the paper. The review version stays frozen under
`../paper/`.

```
camera-ready/
  main.tex     de-anonymized copy of ../paper/main.tex (authors, copyright hook)
  tables/      snapshot of ../paper/tables
  refs.bib     snapshot of ../paper/refs.bib
  Makefile     build + camera-ready gates (`make`)
```

Figures are **not** copied — `\graphicspath{{../paper/figures/}}` keeps
`../paper/figures` the single source. `make figures` forwards to
`make -C ../paper figures`.

## Build

```bash
make            # pdflatex → bibtex → pdflatex ×2, then the checks below
make figures    # rebuild shared figures in ../paper/figures first
```

`make` fails the build above 6 pages or if any LLM-tooling string reaches the
PDF, warns if the PDF still looks anonymized, and notes unresolved
`TODO(camera-ready)` markers.

## What changed vs. the review version

| | review (`../paper`) | camera-ready (here) |
|---|---|---|
| `\author` | commented out entirely | Sahruri, Margala + affiliation + e-mails |
| `\IEEEoverridecommandlockouts` | absent | added (needed by `\IEEEpubid`) |
| copyright notice | none | `\IEEEpubid` hook, commented, placement verified |
| acknowledgments | none | commented template |
| `\graphicspath` | `figures/` | `../paper/figures/` |

Body text, tables and `refs.bib` are otherwise identical to the review copy;
reviewer-driven revisions go here, not in `../paper/`.

**Page budget:** 6/6 with the author block in place. A realistic copyright line
was test-built and it still fits — but there is no slack, so re-run `make`
after any edit.

## Pre-upload checklist

- [ ] **Author block** — confirm order, spelling, and that
      `abdullah.sahruri1@louisiana.edu` / `martin.margala@louisiana.edu` are the
      addresses you want printed (inferred from the institution, not verified).
- [ ] **Copyright notice** — paste the ISBN line from the acceptance e-mail into
      the `\IEEEpubid` block just after `\begin{document}` and uncomment.
- [ ] **Acknowledgments** — uncomment and fill grant/sponsor text before the
      bibliography, or delete. No LLM tooling acknowledgment (`make` fails if
      one appears).
- [ ] **Reviewer comments** — address each; keep a response letter if SOCC asks.
- [ ] **Self-citations** — `refs.bib` currently contains none. If reviewers
      asked for TLG-lineage additions from your own work, add them with real
      author fields now.
- [ ] **Page limit** — 6 pages; `make` hard-fails above that.
- [ ] **IEEE PDF eXpress** — upload the eXpress-approved PDF, not the local
      pdflatex output. Note `main.tex` does not load `hyperref`, so the PDF
      carries no Title/Author metadata; add it only if SOCC requires it, and
      re-check the page count afterwards.
- [ ] **Copyright form** — eCF signed; affiliations must match the paper.
