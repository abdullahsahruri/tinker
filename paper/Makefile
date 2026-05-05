PAPER  := main
LATEX  := pdflatex -interaction=nonstopmode -halt-on-error
BIBTEX := bibtex

FIG_SRCS := $(wildcard figures/*.src.tex)
FIG_PDFS := $(FIG_SRCS:.src.tex=.pdf)

.PHONY: all clean distclean figures

all: $(PAPER).pdf

# Build a placeholder figure PDF from its standalone source.
figures/%.pdf: figures/%.src.tex
	cd figures && $(LATEX) $*.src.tex >/dev/null
	mv figures/$*.src.pdf figures/$*.pdf
	rm -f figures/$*.src.aux figures/$*.src.log

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
