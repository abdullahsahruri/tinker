#!/usr/bin/env python3
"""Parse LibreLane sign-off metrics across the 15 Phase-1 runs and emit:

  results/phase1/summary.csv   — one row per (variant, seed)
  results/phase1/summary.md    — aggregated table for the writeup

For each run we extract:
  area_um2          — design__instance__area (post-route cell area, µm²)
  fmax_mhz          — derived from worst setup slack at the slow corner
                      (max_ss_100C_1v60): fmax = 1 / (CLOCK_PERIOD - WS) ns
  power_uw          — total post-route power at the nominal corner.
                      Read from metrics.json `power__total` at corner
                      nom_tt_025C_1v80 if present, else from the OpenSTA
                      power report.
"""
from __future__ import annotations
import argparse
import csv
import json
import math
import re
import statistics
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "results" / "phase1"

VARIANTS = ["naive", "handopt", "tlg"]
SEEDS = [0, 1, 2, 3, 4]
SLOW_CORNER = "max_ss_100C_1v60"
NOM_CORNER = "nom_tt_025C_1v80"
CLOCK_PERIOD_NS = 10.0


def find_run_dir(variant: str, seed: int) -> Path | None:
    """Find the LibreLane run directory for a given (variant, seed)."""
    flow_root = ROOT / "flow" / f"phase1_{variant}" / f"seed{seed}"
    runs = flow_root / "runs"
    tag = f"phase1_{variant}_s{seed}"
    if (runs / tag).is_dir():
        return runs / tag
    if not runs.is_dir():
        # Pilot used a top-level flow dir.
        flow_root = ROOT / "flow" / f"phase1_{variant}"
        runs = flow_root / "runs"
    if runs.is_dir():
        # Most-recent run-tag fallback.
        candidates = sorted(runs.glob(f"phase1_{variant}_s{seed}*"))
        if candidates:
            return candidates[-1]
    return None


def parse_power_report(run_dir: Path, corner: str) -> float | None:
    """Pull total internal+switching+leakage from a corner's power report.

    OpenSTA emits a 'Total' line like:
        Total                 1.23e-05  4.56e-06  7.89e-07  ...
    in the `*_power.rpt` of the OpenROAD STA-post-route step.
    """
    sta_dirs = sorted(run_dir.glob("*-openroad-stapostpnr"))
    if not sta_dirs:
        sta_dirs = sorted(run_dir.glob("*-openroad-stamidpnr"))
    if not sta_dirs:
        return None
    sta_dir = sta_dirs[-1]
    # Each corner has its own subdir.
    cdir = sta_dir / corner
    if not cdir.is_dir():
        return None
    rpts = list(cdir.glob("*power*.rpt")) + list(cdir.glob("power.rpt"))
    if not rpts:
        return None
    with rpts[0].open() as f:
        for line in f:
            m = re.match(r"^\s*Total\s+([0-9.eE+\-]+)\s+([0-9.eE+\-]+)\s+([0-9.eE+\-]+)\s+([0-9.eE+\-]+)", line)
            if m:
                # Watts → microwatts
                return float(m.group(4)) * 1e6
    return None


def collect_one(variant: str, seed: int) -> dict | None:
    run = find_run_dir(variant, seed)
    if run is None:
        return None
    metrics_path = run / "final" / "metrics.json"
    if not metrics_path.is_file():
        return None
    m = json.loads(metrics_path.read_text())

    area = m.get("design__instance__area")
    stdcells = m.get("design__instance__count__stdcell")

    ws_key = f"timing__setup__ws__corner:{SLOW_CORNER}"
    ws = m.get(ws_key, m.get("timing__setup__ws"))
    if ws is None or area is None:
        return None
    crit = CLOCK_PERIOD_NS - ws  # ns
    if crit <= 0:
        # Slack > period (path collapsed to ~0): cap at 1 GHz to avoid div0.
        fmax = math.inf
    else:
        fmax = 1000.0 / crit  # MHz

    # Power: prefer metrics.json key, fall back to report.
    power_uw = None
    pkeys = [k for k in m if k.startswith("power__total") and (NOM_CORNER in k or k == "power__total")]
    if pkeys:
        # Take the nominal-corner one if present; else the bare total.
        chosen = next((k for k in pkeys if NOM_CORNER in k), pkeys[0])
        # Watts in metrics → µW
        power_uw = float(m[chosen]) * 1e6
    else:
        power_uw = parse_power_report(run, NOM_CORNER)

    drc = m.get("magic__drc_error__count", 0) + m.get("klayout__drc_error__count", 0)
    lvs = m.get("design__lvs_error__count", 0) + m.get("design__lvs_unmatched_pins__count", 0)
    return {
        "variant": variant,
        "seed": seed,
        "area_um2": float(area),
        "stdcell_count": int(stdcells) if stdcells is not None else 0,
        "fmax_mhz": float(fmax) if fmax != math.inf else math.inf,
        "power_uw_at_100mhz": float(power_uw) if power_uw is not None else math.nan,
        "ws_at_slow_ns": float(ws),
        "drc_errors": int(drc),
        "lvs_errors": int(lvs),
        "run_dir": str(run.relative_to(ROOT)),
    }


def fmt(v):
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return "—"
    if isinstance(v, float) and v == math.inf:
        return "∞"
    if isinstance(v, float):
        return f"{v:.2f}"
    return str(v)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=RESULTS)
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    rows = []
    missing = []
    for v in VARIANTS:
        for s in SEEDS:
            row = collect_one(v, s)
            if row is None:
                missing.append((v, s))
            else:
                rows.append(row)

    csv_path = args.out / "summary.csv"
    with csv_path.open("w", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["variant", "seed", "area_um2", "stdcell_count", "fmax_mhz",
                        "power_uw_at_100mhz", "ws_at_slow_ns",
                        "drc_errors", "lvs_errors", "run_dir"])
        writer.writeheader()
        for r in rows:
            writer.writerow(r)
    print(f"wrote {csv_path} with {len(rows)} rows ({len(missing)} missing)")
    if missing:
        for v, s in missing:
            print(f"  missing: {v} seed={s}")

    # Aggregate per variant (mean ± std).
    md = ["# Phase 1 — synthesis comparison summary",
          "",
          f"Slow corner: `{SLOW_CORNER}`. CLOCK_PERIOD = {CLOCK_PERIOD_NS} ns "
          f"(target 100 MHz). All 15 runs use SYNTH_STRATEGY = AREA 0.",
          ""]
    md.append("| Variant | Area (µm²) mean±std | Stdcells mean±std | Fmax (MHz) mean±std | Power (µW) mean±std | DRC | LVS |")
    md.append("|---|---|---|---|---|---|---|")
    by_var = {v: [r for r in rows if r["variant"] == v] for v in VARIANTS}

    def agg(vs, key):
        xs = [r[key] for r in vs if not (isinstance(r[key], float) and (math.isnan(r[key]) or r[key] == math.inf))]
        if not xs:
            return None, None
        if len(xs) < 2:
            return statistics.mean(xs), 0.0
        return statistics.mean(xs), statistics.stdev(xs)

    means = {}
    for v in VARIANTS:
        a_m, a_s = agg(by_var[v], "area_um2")
        c_m, c_s = agg(by_var[v], "stdcell_count")
        f_m, f_s = agg(by_var[v], "fmax_mhz")
        p_m, p_s = agg(by_var[v], "power_uw_at_100mhz")
        means[v] = {"area": a_m, "cells": c_m, "fmax": f_m, "power": p_m}
        drc_total = sum(r["drc_errors"] for r in by_var[v])
        lvs_total = sum(r["lvs_errors"] for r in by_var[v])
        a_str = f"{a_m:.2f} ± {a_s:.2f}" if a_m is not None else "—"
        c_str = f"{c_m:.1f} ± {c_s:.1f}" if c_m is not None else "—"
        f_str = f"{f_m:.2f} ± {f_s:.2f}" if f_m is not None else "—"
        p_str = f"{p_m:.2f} ± {p_s:.2f}" if p_m is not None else "—"
        md.append(f"| {v} | {a_str} | {c_str} | {f_str} | {p_str} | {drc_total} | {lvs_total} |")

    # Relative improvements C-vs-A and C-vs-B.
    md.append("")
    md.append("## Relative improvements (TLG vs baselines)")
    md.append("")
    md.append("Improvement = `(baseline_mean - tlg_mean) / baseline_mean × 100%`. "
              "Positive ⇒ TLG is smaller / faster / lower-power.")
    md.append("")
    md.append("| Metric | C vs A (TLG vs naive) | C vs B (TLG vs hand-opt) |")
    md.append("|---|---|---|")
    if means["tlg"]["area"] is not None:
        for label, key, sign in [("Area", "area", +1), ("Stdcells", "cells", +1),
                                 ("Fmax", "fmax", -1), ("Power", "power", +1)]:
            base_a = means["naive"][key]; base_b = means["handopt"][key]; tlg = means["tlg"][key]
            if base_a is None or base_b is None or tlg is None:
                md.append(f"| {label} | — | — |")
                continue
            if sign > 0:
                imp_a = (base_a - tlg) / base_a * 100.0
                imp_b = (base_b - tlg) / base_b * 100.0
            else:
                # Higher fmax is better, so the sign flips.
                imp_a = (tlg - base_a) / base_a * 100.0
                imp_b = (tlg - base_b) / base_b * 100.0
            md.append(f"| {label} | {imp_a:+.1f}% | {imp_b:+.1f}% |")

    md_path = args.out / "summary.md"
    md_path.write_text("\n".join(md) + "\n")
    print(f"wrote {md_path}")


if __name__ == "__main__":
    main()
