#!/usr/bin/env python3
"""Parse LibreLane sign-off metrics for the four Phase-2 tile runs and emit:

  results/phase2/summary.csv   — one row per variant
  results/phase2/summary.md    — comparison tables for the writeup

For each run we extract:
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

Power keys in metrics.json are unitless Watts. Phase 1 runs did not
have per-corner power keys, so we expect the bare `power__total` form
here too — but the loader tries the nominal-corner-suffixed key first
in case a future librelane release adds them.
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

VARIANTS = ["tlg_hc", "tlg_ld", "handopt_hc", "handopt_ld"]
PRETTY = {
    "tlg_hc":     "TLG hc",
    "tlg_ld":     "TLG ld",
    "handopt_hc": "handopt hc",
    "handopt_ld": "handopt ld",
}
SLOW_CORNER = "max_ss_100C_1v60"
NOM_CORNER = "nom_tt_025C_1v80"
CLOCK_PERIOD_NS = 10.0


def find_run_dir(variant: str) -> Path | None:
    flow_root = ROOT / "flow" / f"phase2_{variant}"
    runs = flow_root / "runs"
    tag = f"phase2_{variant}"
    if (runs / tag).is_dir():
        return runs / tag
    if runs.is_dir():
        candidates = sorted(runs.glob(f"phase2_{variant}*"))
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
    """Find a power metric in W and return it in µW. Tries the nominal
    corner first, then the bare key."""
    for k in (f"{key_root}__corner:{NOM_CORNER}", key_root):
        if k in metrics:
            try:
                return float(metrics[k]) * 1e6
            except (TypeError, ValueError):
                pass
    return math.nan


def collect_one(variant: str) -> dict | None:
    run = find_run_dir(variant)
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


def pct_change(new, base, *, lower_is_better=True):
    """Return (new - base)/base × 100, with sign convention so that
    positive = new is *better* than base on this metric."""
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

    rows: dict[str, dict] = {}
    missing: list[str] = []
    for v in VARIANTS:
        r = collect_one(v)
        if r is None:
            missing.append(v)
        else:
            rows[v] = r

    csv_path = args.out / "summary.csv"
    fieldnames = ["variant", "cells", "area_um2",
                  "fmax_mhz_slow", "fmax_mhz_nom", "ws_slow_ns",
                  "power_total_uw", "power_internal_uw",
                  "power_switching_uw", "power_leakage_uw",
                  "drc_violations", "lvs_violations",
                  "antenna_nets", "antenna_pins", "run_dir"]
    with csv_path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for v in VARIANTS:
            if v in rows:
                writer.writerow(rows[v])
    print(f"wrote {csv_path} with {len(rows)} rows ({len(missing)} missing)")
    for v in missing:
        print(f"  missing: {v}")

    # ---- Markdown summary -------------------------------------------------
    md = ["# Phase 2 Session B — tile-level synthesis comparison",
          "",
          f"Slow corner: `{SLOW_CORNER}`. CLOCK_PERIOD = {CLOCK_PERIOD_NS} ns "
          f"(target 100 MHz). All four runs use SYNTH_STRATEGY = AREA 0, "
          f"FP_CORE_UTIL = 35, PL_TARGET_DENSITY_PCT = 55, identical SDC "
          f"(`flow/common/tile.sdc`). Only the RTL differs across runs.",
          ""]
    md.append("| Variant | Cells | Area (µm²) | Fmax slow (MHz) | "
              "Fmax nom (MHz) | Power (µW) | DRC | LVS |")
    md.append("|---|---:|---:|---:|---:|---:|---:|---:|")
    for v in VARIANTS:
        r = rows.get(v)
        if r is None:
            md.append(f"| {PRETTY[v]} | — | — | — | — | — | — | — |")
            continue
        md.append(
            f"| {PRETTY[v]} "
            f"| {fmt_int(r['cells'])} "
            f"| {fmt_f(r['area_um2'])} "
            f"| {fmt_f(r['fmax_mhz_slow'])} "
            f"| {fmt_f(r['fmax_mhz_nom'])} "
            f"| {fmt_f(r['power_total_uw'])} "
            f"| {r['drc_violations']} "
            f"| {r['lvs_violations']} |"
        )

    # Power decomposition.
    md += ["",
           "## Power decomposition (µW, nominal corner)",
           "",
           "| Variant | Internal | Switching | Leakage | Total |",
           "|---|---:|---:|---:|---:|"]
    for v in VARIANTS:
        r = rows.get(v)
        if r is None:
            md.append(f"| {PRETTY[v]} | — | — | — | — |")
            continue
        md.append(
            f"| {PRETTY[v]} "
            f"| {fmt_f(r['power_internal_uw'])} "
            f"| {fmt_f(r['power_switching_uw'])} "
            f"| {fmt_f(r['power_leakage_uw'], 4)} "
            f"| {fmt_f(r['power_total_uw'])} |"
        )

    # ---- Comparisons ------------------------------------------------------
    md += ["",
           "## Relative comparisons",
           "",
           "Sign convention: **positive = first variant is better** "
           "(smaller area, fewer cells, higher Fmax, lower power).",
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
        rn, rb = rows.get(new_v), rows.get(base_v)
        if rn is None or rb is None:
            md.append(f"| {label} | — | — | — | — |")
            continue
        d_cells = pct_change(rn["cells"], rb["cells"], lower_is_better=True)
        d_area = pct_change(rn["area_um2"], rb["area_um2"], lower_is_better=True)
        d_fmax = pct_change(rn["fmax_mhz_slow"], rb["fmax_mhz_slow"],
                            lower_is_better=False)
        d_pwr = pct_change(rn["power_total_uw"], rb["power_total_uw"],
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
