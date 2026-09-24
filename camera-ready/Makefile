PAPER  := main
LATEX  := pdflatex -interaction=nonstopmode -halt-on-error
BIBTEX := bibtex

# Figures are single-sourced in ../paper/figures and built by that Makefile.
FIG_DIR := ../paper/figures
FIG_PDFS := $(FIG_DIR)/conventional3.pdf $(FIG_DIR)/fig1_soc_block.pdf \
            $(FIG_DIR)/fig2_tile_microarch.pdf $(FIG_DIR)/fig3_layout.pdf \
            $(FIG_DIR)/fig4_power_breakdown.pdf $(FIG_DIR)/fig_tlg_decomp.pdf

SUB     := submission
BASE    := socc2026_tinker_camera_ready

.PHONY: all figures check dist clean distclean

all: check

figures:
	$(MAKE) -C ../paper figures

# The .bbl is a build product in its own right: `dist` ships it, and without
# this rule a `clean` leaves main.pdf looking up-to-date with no .bbl on disk.
$(PAPER).bbl: $(PAPER).tex refs.bib
	$(LATEX) $(PAPER).tex
	$(BIBTEX) $(PAPER) || true

# Two-pass build with bibtex in between for cross-references + bib.
$(PAPER).pdf: $(PAPER).tex refs.bib tables/*.tex $(FIG_PDFS) $(PAPER).bbl
	$(LATEX) $(PAPER).tex
	$(BIBTEX) $(PAPER) || true
	$(LATEX) $(PAPER).tex
	$(LATEX) $(PAPER).tex

# Camera-ready gates: 6-page limit, no LLM-tooling mention, authors present.
check: $(PAPER).pdf
	@pages=$$(pdfinfo $(PAPER).pdf | awk '/^Pages:/ {print $$2}'); \
	echo "Built $(PAPER).pdf ($$pages pages)"; \
	if [ "$$pages" -gt 6 ]; then echo "ERROR: over the 6-page limit" >&2; exit 1; fi
	@text=$$(pdftotext -layout $(PAPER).pdf -); \
	if echo "$$text" | grep -qiE "claude|anthropic|chatgpt|openai"; then \
	    echo "ERROR: LLM tooling mention in camera-ready PDF" >&2; exit 1; fi; \
	if ! echo "$$text" | grep -qi "sahruri"; then \
	    echo "WARNING: no author name in PDF text -- still anonymized?" >&2; fi; \
	if echo "$$text" | grep -qi "anonymous"; then \
	    echo "WARNING: 'anonymous' still appears in the PDF" >&2; fi
	@if grep -q "TODO(camera-ready)" $(PAPER).tex; then \
	    echo "NOTE: unresolved TODO(camera-ready) markers remain in $(PAPER).tex" >&2; fi

# Submission bundle: the upload PDF plus a self-contained source archive.
# Publishers do not run BibTeX, so main.bbl ships in the archive and the
# archive's \graphicspath is rewritten to its own local figures/ copy.
dist: check
	rm -rf $(SUB)
	mkdir -p $(SUB)/source/figures $(SUB)/source/tables
	cp $(PAPER).pdf $(SUB)/$(BASE).pdf
	sed 's|\.\./paper/figures/|figures/|' $(PAPER).tex > $(SUB)/source/$(PAPER).tex
	cp refs.bib $(PAPER).bbl $(SUB)/source/
	cp tables/*.tex $(SUB)/source/tables/
	cp $(FIG_PDFS) $(SUB)/source/figures/
	@# Verify the archive builds standalone and matches the upload PDF page count.
	@cd $(SUB)/source && $(LATEX) $(PAPER).tex >/dev/null 2>&1 && \
	   $(LATEX) $(PAPER).tex >/dev/null 2>&1 || { echo "ERROR: source bundle does not compile" >&2; exit 1; }
	@a=$$(pdfinfo $(SUB)/$(BASE).pdf | awk '/^Pages:/{print $$2}'); \
	 b=$$(pdfinfo $(SUB)/source/$(PAPER).pdf | awk '/^Pages:/{print $$2}'); \
	 if [ "$$a" != "$$b" ]; then echo "ERROR: bundle is $$b pages, upload PDF is $$a" >&2; exit 1; fi; \
	 echo "Source bundle compiles standalone ($$b pages)"
	@cd $(SUB)/source && rm -f $(PAPER).pdf $(PAPER).aux $(PAPER).log $(PAPER).out
	cd $(SUB) && zip -qr $(BASE)_source.zip source && rm -rf source
	@echo "Ready in $(SUB)/: $(BASE).pdf + $(BASE)_source.zip"

clean:
	rm -f $(PAPER).aux $(PAPER).log $(PAPER).bbl $(PAPER).blg \
	      $(PAPER).out $(PAPER).toc $(PAPER).fls $(PAPER).fdb_latexmk

distclean: clean
	rm -f $(PAPER).pdf
