PAPER  := main
LATEX  := pdflatex -interaction=nonstopmode -halt-on-error
BIBTEX := bibtex

FIG_SRCS := $(wildcard figures/*.src.tex)
FIG_TIKZ_PDFS := $(FIG_SRCS:.src.tex=.pdf)
FIG_PY_PDFS   := figures/fig4_power_breakdown.pdf
FIG_SRC_PDFS  := figures/fig3_layout.pdf
FIG_PDFS      := $(FIG_TIKZ_PDFS) $(FIG_PY_PDFS) $(FIG_SRC_PDFS)

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

# Build the floorplan figure: KLayout renders soc_top.gds with
# upper-metal layers suppressed to reveal std-cell texture, then
# matplotlib composites extracted-bbox overlays on top.
figures/src/fig3_base.png: figures/src/fig3_render_base.py figures/src/fig3_clean.lyp
	klayout -b -r figures/src/fig3_render_base.py >/dev/null

figures/fig3_layout.pdf: figures/src/fig3_compose.py figures/src/fig3_base.png \
                        figures/src/fig3_floorplan_data.json
	python3 figures/src/fig3_compose.py >/dev/null

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
