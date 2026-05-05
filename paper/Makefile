PAPER  := main
LATEX  := pdflatex -interaction=nonstopmode -halt-on-error
BIBTEX := bibtex

FIG_SRCS := $(wildcard figures/*.src.tex)
FIG_TIKZ_PDFS := $(FIG_SRCS:.src.tex=.pdf)
FIG_PY_PDFS   := figures/fig4_power_breakdown.pdf
FIG_PDFS      := $(FIG_TIKZ_PDFS) $(FIG_PY_PDFS)

.PHONY: all clean distclean figures

all: $(PAPER).pdf

# Build a TikZ figure PDF from its standalone source.
figures/%.pdf: figures/%.src.tex
	cd figures && $(LATEX) $*.src.tex >/dev/null
	mv figures/$*.src.pdf figures/$*.pdf
	rm -f figures/$*.src.aux figures/$*.src.log

# Build the matplotlib power-breakdown figure.
figures/fig4_power_breakdown.pdf: figures/fig4_power_breakdown.py
	cd figures && python3 fig4_power_breakdown.py >/dev/null

figures: $(FIG_PDFS)

# Two-pass build with bibtex in between for cross-references + bib.
$(PAPER).pdf: $(PAPER).tex refs.bib tables/*.tex $(FIG_PDFS)
	$(LATEX) $(PAPER).tex
	$(BIBTEX) $(PAPER) || true
	$(LATEX) $(PAPER).tex
	$(LATEX) $(PAPER).tex

clean:
	rm -f $(PAPER).aux $(PAPER).log $(PAPER).bbl $(PAPER).blg \
	      $(PAPER).out $(PAPER).toc $(PAPER).fls $(PAPER).fdb_latexmk
	rm -f figures/*.src.aux figures/*.src.log

distclean: clean
	rm -f $(PAPER).pdf $(FIG_PDFS)
