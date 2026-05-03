#!/usr/bin/env python3
"""Parse LibreLane sign-off metrics for the Phase-2 tile runs and emit:

  results/phase2/summary.csv   — one row per (variant, seed)
  results/phase2/summary.md    — multi-seed comparison tables for the writeup

Multi-seed (Session 2B.5) sweeps:
  - hardcoded variants (`tlg_hc`, `handopt_hc`) run for seed_id ∈ {0, 1, 2}
  - loadable variants (`tlg_ld`, `handopt_ld`) only for seed_id 0; their
    .v file is **seed-invariant** by construction (the truth tables and
    adder tree do not reference any specific weight value), so re-running
    the same RTL for additional seeds would only sample LibreLane's P&R
    noise — that's a separate question, not what 2B.5 is asking.

Per run we extract:
  cells              — design__instance__count__stdcell
  area_um2           — design__instance__area (post-route cell area, µm²)
  fmax_mhz_slow      — 1 / (CLOCK_PERIOD - WS) at the slow corner
                       max_ss_100C_1v60
  fmax_mhz_nom       — same, at the nominal corner nom_tt_025C_1v80
  power_total_uw     — total post-route power (W → µW)
  power_internal_uw  — internal power component
  power_switching_uw — switching power component
  power_leakage_uw   — leakage power component
  drc_violations     — magic + klayout combined
  lvs_violations     — design__lvs_error__count + unmatched_pins
  antenna_nets/pins  — antenna__violating__nets / __pins

Power keys in metrics.json are unitless Watts. Phase 1 / Phase 2B runs did
not have per-corner power keys — we expect the bare `power__total` form
here too — but the loader tries the nominal-corner-suffixed key first in
case a future librelane release adds them.
"""
from __future__ import annotations
import argparse
import csv
import json
import math
import statistics
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "results" / "phase2"

# Variants and the seed_ids each is run for. Hardcoded variants get a
# 3-seed sweep; loadable variants are seed-invariant by construction.
VARIANTS = ["tlg_hc", "tlg_ld", "handopt_hc", "handopt_ld"]
SEEDS_BY_VARIANT = {
    "tlg_hc":     [0, 1, 2],
    "tlg_ld":     [0],
    "handopt_hc": [0, 1, 2],
    "handopt_ld": [0],
}
PRETTY = {
    "tlg_hc":     "TLG hc",
    "tlg_ld":     "TLG ld",
    "handopt_hc": "handopt hc",
    "handopt_ld": "handopt ld",
}
SLOW_CORNER = "max_ss_100C_1v60"
NOM_CORNER = "nom_tt_025C_1v80"
CLOCK_PERIOD_NS = 10.0


def find_run_dir(variant: str, seed: int) -> Path | None:
    """Locate the LibreLane run directory for a given (variant, seed).

    seed_id 0 reuses Phase 2B's flat layout: flow/phase2_<v>/runs/phase2_<v>/
    seed_id N>=1 uses Phase 2B.5's per-seed layout:
      flow/phase2_<v>/seed<N>/runs/phase2_<v>_s<N>/
    """
    flow_root = ROOT / "flow" / f"phase2_{variant}"
    if seed == 0:
        runs = flow_root / "runs"
        tag = f"phase2_{variant}"
    else:
        runs = flow_root / f"seed{seed}" / "runs"
        tag = f"phase2_{variant}_s{seed}"
    if (runs / tag).is_dir():
        return runs / tag
    if runs.is_dir():
        candidates = sorted(runs.glob(f"{tag}*"))
        if candidates:
            return candidates[-1]
    return None


def fmax_from_ws(ws_ns: float | None) -> float:
    if ws_ns is None:
        return math.nan
    crit = CLOCK_PERIOD_NS - ws_ns
    if crit <= 0:
        return math.inf
    return 1000.0 / crit


def power_uw(metrics: dict, key_root: str) -> float:
    for k in (f"{key_root}__corner:{NOM_CORNER}", key_root):
        if k in metrics:
            try:
                return float(metrics[k]) * 1e6
            except (TypeError, ValueError):
                pass
    return math.nan


def collect_one(variant: str, seed: int) -> dict | None:
    run = find_run_dir(variant, seed)
    if run is None:
        return None
    metrics_path = run / "final" / "metrics.json"
    if not metrics_path.is_file():
        return None
    m = json.loads(metrics_path.read_text())
    ws_slow = m.get(f"timing__setup__ws__corner:{SLOW_CORNER}",
                    m.get("timing__setup__ws"))
    ws_nom = m.get(f"timing__setup__ws__corner:{NOM_CORNER}", ws_slow)
    drc = (m.get("magic__drc_error__count", 0)
           + m.get("klayout__drc_error__count", 0))
    lvs = (m.get("design__lvs_error__count", 0)
           + m.get("design__lvs_unmatched_pins__count", 0))
    return {
        "variant": variant,
        "seed": seed,
        "cells": int(m.get("design__instance__count__stdcell", 0)),
        "area_um2": float(m.get("design__instance__area", math.nan)),
        "fmax_mhz_slow": fmax_from_ws(
            ws_slow if isinstance(ws_slow, (int, float)) else None),
        "fmax_mhz_nom": fmax_from_ws(
            ws_nom if isinstance(ws_nom, (int, float)) else None),
        "ws_slow_ns": float(ws_slow) if isinstance(ws_slow, (int, float)) else math.nan,
        "power_total_uw":     power_uw(m, "power__total"),
        "power_internal_uw":  power_uw(m, "power__internal__total"),
        "power_switching_uw": power_uw(m, "power__switching__total"),
        "power_leakage_uw":   power_uw(m, "power__leakage__total"),
        "drc_violations": int(drc),
        "lvs_violations": int(lvs),
        "antenna_nets": int(m.get("antenna__violating__nets", 0)),
        "antenna_pins": int(m.get("antenna__violating__pins", 0)),
        "run_dir": str(run.relative_to(ROOT)),
    }


def fmt_int(v):
    if v is None:
        return "—"
    return f"{int(v)}"


def fmt_f(v, prec=2):
    if v is None or (isinstance(v, float) and (math.isnan(v) or v == math.inf)):
        return "—" if v is None or math.isnan(v) else "∞"
    return f"{v:.{prec}f}"


def fmt_mean_std(xs, prec=2, *, int_mean=False):
    """Format a list as 'mean ± stdev'. For N=1, omit the ± part."""
    xs = [x for x in xs
          if not (isinstance(x, float) and (math.isnan(x) or x == math.inf))]
    if not xs:
        return "—"
    mean = statistics.mean(xs)
    if len(xs) < 2:
        return f"{int(round(mean))}" if int_mean else f"{mean:.{prec}f}"
    std = statistics.stdev(xs)
    if int_mean:
        return f"{int(round(mean))} ± {int(round(std))}"
    return f"{mean:.{prec}f} ± {std:.{prec}f}"


def mean_of(rows, key):
    xs = [r[key] for r in rows
          if not (isinstance(r[key], float) and (math.isnan(r[key]) or r[key] == math.inf))]
    return statistics.mean(xs) if xs else math.nan


def pct_change(new, base, *, lower_is_better=True):
    if (new is None or base is None
            or any(isinstance(x, float) and (math.isnan(x) or x == math.inf)
                   for x in (new, base))
            or base == 0):
        return math.nan
    raw = (new - base) / base * 100.0
    return -raw if lower_is_better else raw


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=RESULTS)
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    rows: list[dict] = []
    rows_by_variant: dict[str, list[dict]] = {v: [] for v in VARIANTS}
    missing: list[tuple[str, int]] = []
    for v in VARIANTS:
        for s in SEEDS_BY_VARIANT[v]:
            r = collect_one(v, s)
            if r is None:
                missing.append((v, s))
            else:
                rows.append(r)
                rows_by_variant[v].append(r)

    csv_path = args.out / "summary.csv"
    fieldnames = ["variant", "seed", "cells", "area_um2",
                  "fmax_mhz_slow", "fmax_mhz_nom", "ws_slow_ns",
                  "power_total_uw", "power_internal_uw",
                  "power_switching_uw", "power_leakage_uw",
                  "drc_violations", "lvs_violations",
                  "antenna_nets", "antenna_pins", "run_dir"]
    with csv_path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in rows:
            writer.writerow(r)
    print(f"wrote {csv_path} with {len(rows)} rows ({len(missing)} missing)")
    for v, s in missing:
        print(f"  missing: {v} seed={s}")

    # ---- Markdown summary -------------------------------------------------
    md = ["# Phase 2 Session B / B.5 — tile-level synthesis comparison",
          "",
          f"Slow corner: `{SLOW_CORNER}`. CLOCK_PERIOD = {CLOCK_PERIOD_NS} ns "
          f"(target 100 MHz). All runs use SYNTH_STRATEGY = AREA 0, "
          f"FP_CORE_UTIL = 35, PL_TARGET_DENSITY_PCT = 55, identical SDC "
          f"(`flow/common/tile.sdc`). Only the RTL differs across runs.",
          "",
          "Hardcoded variants are run for **3 weight seeds** (seed_id 0/1/2). "
          "Loadable variants are run for seed_id 0 only — their RTL is "
          "seed-invariant by construction (no weight constants in the file), "
          "so re-running them on additional weight seeds would produce "
          "identical metrics.",
          ""]
    md.append("| Variant | N | Cells (µ ± σ) | Area µm² (µ ± σ) | "
              "Fmax slow MHz (µ ± σ) | Power µW (µ ± σ) | DRC | LVS |")
    md.append("|---|---:|---:|---:|---:|---:|---:|---:|")
    for v in VARIANTS:
        rs = rows_by_variant[v]
        if not rs:
            md.append(f"| {PRETTY[v]} | 0 | — | — | — | — | — | — |")
            continue
        md.append(
            f"| {PRETTY[v]} "
            f"| {len(rs)} "
            f"| {fmt_mean_std([r['cells'] for r in rs], int_mean=True)} "
            f"| {fmt_mean_std([r['area_um2'] for r in rs])} "
            f"| {fmt_mean_std([r['fmax_mhz_slow'] for r in rs])} "
            f"| {fmt_mean_std([r['power_total_uw'] for r in rs])} "
            f"| {sum(r['drc_violations'] for r in rs)} "
            f"| {sum(r['lvs_violations'] for r in rs)} |"
        )

    # Per-seed table for inspection.
    md += ["",
           "## Per-seed detail",
           "",
           "| Variant | Seed | Cells | Area (µm²) | Fmax slow (MHz) | "
           "Power (µW) | WS slow (ns) | DRC | LVS |",
           "|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for v in VARIANTS:
        for r in rows_by_variant[v]:
            md.append(
                f"| {PRETTY[v]} | {r['seed']} "
                f"| {fmt_int(r['cells'])} "
                f"| {fmt_f(r['area_um2'])} "
                f"| {fmt_f(r['fmax_mhz_slow'])} "
                f"| {fmt_f(r['power_total_uw'])} "
                f"| {fmt_f(r['ws_slow_ns'], 3)} "
                f"| {r['drc_violations']} "
                f"| {r['lvs_violations']} |"
            )

    # Power decomposition (means).
    md += ["",
           "## Power decomposition (mean µW, nominal corner)",
           "",
           "| Variant | N | Internal | Switching | Leakage | Total |",
           "|---|---:|---:|---:|---:|---:|"]
    for v in VARIANTS:
        rs = rows_by_variant[v]
        if not rs:
            md.append(f"| {PRETTY[v]} | 0 | — | — | — | — |")
            continue
        md.append(
            f"| {PRETTY[v]} "
            f"| {len(rs)} "
            f"| {fmt_mean_std([r['power_internal_uw'] for r in rs])} "
            f"| {fmt_mean_std([r['power_switching_uw'] for r in rs])} "
            f"| {fmt_mean_std([r['power_leakage_uw'] for r in rs], prec=4)} "
            f"| {fmt_mean_std([r['power_total_uw'] for r in rs])} |"
        )

    # ---- Comparisons across MEANS ----------------------------------------
    md += ["",
           "## Relative comparisons (means)",
           "",
           "Sign convention: **positive = first variant is better** "
           "(smaller area, fewer cells, higher Fmax, lower power). All "
           "comparisons are taken between per-variant means; for hardcoded "
           "variants this is over 3 seeds, for loadable over 1 seed.",
           ""]

    pairs = [
        ("tlg_hc",     "handopt_hc", "TLG hc vs handopt hc",
         "Same logic-style isolation — both hardcoded, both no regfile, "
         "synthesis methodology only."),
        ("tlg_ld",     "handopt_ld", "TLG ld vs handopt ld",
         "Realistic comparison — both programmable, methodology cost "
         "with the regfile present in both."),
        ("tlg_ld",     "tlg_hc",     "TLG ld vs TLG hc",
         "Programmability cost on the TLG path."),
        ("handopt_ld", "handopt_hc", "handopt ld vs handopt hc",
         "Programmability cost on the adder-tree path."),
    ]
    md.append("| Comparison | ΔCells | ΔArea | ΔFmax (slow) | ΔPower |")
    md.append("|---|---:|---:|---:|---:|")
    for new_v, base_v, label, _ in pairs:
        rs_new, rs_base = rows_by_variant[new_v], rows_by_variant[base_v]
        if not rs_new or not rs_base:
            md.append(f"| {label} | — | — | — | — |")
            continue
        d_cells = pct_change(mean_of(rs_new, "cells"),
                             mean_of(rs_base, "cells"), lower_is_better=True)
        d_area = pct_change(mean_of(rs_new, "area_um2"),
                            mean_of(rs_base, "area_um2"), lower_is_better=True)
        d_fmax = pct_change(mean_of(rs_new, "fmax_mhz_slow"),
                            mean_of(rs_base, "fmax_mhz_slow"),
                            lower_is_better=False)
        d_pwr = pct_change(mean_of(rs_new, "power_total_uw"),
                           mean_of(rs_base, "power_total_uw"),
                           lower_is_better=True)
        md.append(f"| {label} "
                  f"| {fmt_f(d_cells, 1)}% "
                  f"| {fmt_f(d_area, 1)}% "
                  f"| {fmt_f(d_fmax, 1)}% "
                  f"| {fmt_f(d_pwr, 1)}% |")
    md += ["",
           "Comparison rationale:",
           ""]
    for _, _, label, why in pairs:
        md.append(f"- **{label}** — {why}")

    md_path = args.out / "summary.md"
    md_path.write_text("\n".join(md) + "\n")
    print(f"wrote {md_path}")


if __name__ == "__main__":
    main()
