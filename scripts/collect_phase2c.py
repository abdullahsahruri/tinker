#!/usr/bin/env python3
"""Phase 2C — aggregate the 12 SAIF/VCD-driven power measurements.

Reads `results/phase2c/runs/<run_key>/<corner>/power.metrics.json` for every
(variant, seed) pair, joins against the 2B/2B.5 default-activity power
numbers, and emits:

  results/phase2c/summary.csv  — long-form, one row per (variant, seed)
  results/phase2c/summary.md   — aggregate + headline tables

Run after scripts/run_phase2c_all.sh completes.
"""
from __future__ import annotations
import argparse
import csv
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "results" / "phase2c"
PHASE2_RESULTS_CSV = ROOT / "results" / "phase2" / "summary.csv"

CORNER = "max_ff_n40C_1v95"
SEEDS = [0, 1, 2]
VARIANTS = [
    ("tlg",     "hc"),
    ("tlg",     "ld"),
    ("handopt", "hc"),
    ("handopt", "ld"),
]

# 2B/2B.5 default-activity power totals (W) for the same (variant, seed).
# These come from the existing flow/phase2_*/runs/.../final/metrics.json
# `power__total` field — re-derived here so the script is self-contained.
PHASE2B_DEFAULT_W = {
    ("tlg",     "hc", 0): 0.0266377,
    ("tlg",     "hc", 1): 0.0273639,
    ("tlg",     "hc", 2): 0.0269011,
    ("handopt", "hc", 0): 0.0370639,
    ("handopt", "hc", 1): 0.0411812,
    ("handopt", "hc", 2): 0.0395538,
    ("tlg",     "ld", 0): 0.0645664,
    ("handopt", "ld", 0): 0.1678578,
}


def run_key(variant_logic: str, variant_mode: str, seed_id: int) -> str:
    base = f"tile_{variant_logic}_{variant_mode}"
    if seed_id == 0:
        return base
    if variant_mode == "ld":
        # Loadable RTL is seed-invariant — seed 0's DUT name reused for all
        # seeds, with `_s<N>` appended only to the run-key for output paths.
        return f"{base}_s{seed_id}"
    return f"{base}_s{seed_id}"


def load_default_w(variant_logic: str, variant_mode: str, seed_id: int) -> float | None:
    """Default-activity power for ld seeds 1+ does not exist in 2B.5
    (synthesis is seed-invariant; only seed 0 was published). Use seed-0
    when missing, since the netlist is identical."""
    key = (variant_logic, variant_mode, seed_id)
    if key in PHASE2B_DEFAULT_W:
        return PHASE2B_DEFAULT_W[key]
    if variant_mode == "ld":
        return PHASE2B_DEFAULT_W[(variant_logic, "ld", 0)]
    return None


def collect() -> list[dict]:
    rows = []
    for vl, vm in VARIANTS:
        for sd in SEEDS:
            rk = run_key(vl, vm, sd)
            metrics_path = RESULTS / "runs" / rk / CORNER / "power.metrics.json"
            if not metrics_path.is_file():
                rows.append({
                    "variant_logic": vl, "variant_mode": vm, "seed_id": sd,
                    "run_key": rk, "missing": True,
                })
                continue
            m = json.loads(metrics_path.read_text())
            act_w = float(m["power__total"])
            def_w = load_default_w(vl, vm, sd)
            rows.append({
                "variant_logic": vl,
                "variant_mode": vm,
                "seed_id": sd,
                "run_key": rk,
                "missing": False,
                "activity_internal_w":  float(m["power__internal__total"]),
                "activity_switching_w": float(m["power__switching__total"]),
                "activity_leakage_w":   float(m["power__leakage__total"]),
                "activity_total_w":     act_w,
                "default_total_w":      def_w,
                "activity_ratio":       (act_w / def_w) if def_w else None,
                "activity_total_uw":    act_w * 1e6,
                "default_total_uw":     (def_w * 1e6) if def_w else None,
            })
    return rows


def write_csv(rows: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "variant_logic", "variant_mode", "seed_id", "run_key",
        "activity_total_uw", "activity_internal_w", "activity_switching_w",
        "activity_leakage_w", "default_total_uw", "activity_ratio",
    ]
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            if r.get("missing"):
                continue
            w.writerow(r)


def mean_std(xs: list[float]) -> tuple[float, float]:
    if not xs:
        return float("nan"), float("nan")
    m = sum(xs) / len(xs)
    if len(xs) == 1:
        return m, 0.0
    var = sum((x - m) ** 2 for x in xs) / (len(xs) - 1)  # sample stdev
    return m, math.sqrt(var)


def by_variant(rows: list[dict], variant_logic: str, variant_mode: str) -> list[dict]:
    return [r for r in rows
            if not r.get("missing")
            and r["variant_logic"] == variant_logic
            and r["variant_mode"] == variant_mode]


def fmt_pm(mu: float, sigma: float, scale: float = 1.0, dp: int = 3) -> str:
    return f"{mu*scale:.{dp}f} ± {sigma*scale:.{dp}f}"


def render_md(rows: list[dict]) -> str:
    out: list[str] = []
    out.append("# Phase 2C — activity-aware power summary\n")
    out.append(f"Corner: `{CORNER}` (the corner LibreLane reports as the "
               "headline `power__total` metric).\n")
    out.append("Workload: 1024 random-uniform 64-bit input vectors at the "
               "1+2 cadence (1 cycle x_valid + 2 idle, 3 cycles per "
               "vector). Loadable variants programmed with the seed's "
               "weight set before vector replay (cfg-included).\n")
    out.append("")

    # ---- Per-(variant, seed) full table ----
    out.append("## Per-(variant, seed) results\n")
    out.append("| variant | seed | act. power (mW) | default power (mW) | "
               "ratio (act/def) |")
    out.append("|---|---:|---:|---:|---:|")
    for vl, vm in VARIANTS:
        rs = by_variant(rows, vl, vm)
        for r in sorted(rs, key=lambda x: x["seed_id"]):
            ap = r["activity_total_uw"] / 1000.0
            dp_str = (f"{r['default_total_uw']/1000.0:.3f}"
                      if r["default_total_uw"] is not None else "—")
            ratio = (f"{r['activity_ratio']:.2f}×"
                     if r["activity_ratio"] is not None else "—")
            out.append(f"| {vl}_{vm} | {r['seed_id']} | "
                       f"{ap:.3f} | {dp_str} | {ratio} |")
    out.append("")

    # ---- Aggregate per variant ----
    out.append("## Aggregate per variant (mean ± stdev across 3 seeds)\n")
    out.append("| variant | N | act. power (mW) | act. ratio (act/def) | "
               "switching share | internal share |")
    out.append("|---|---:|---:|---:|---:|---:|")
    aggregates: dict[tuple[str, str], dict] = {}
    for vl, vm in VARIANTS:
        rs = by_variant(rows, vl, vm)
        if not rs:
            continue
        ap = [r["activity_total_w"] for r in rs]
        ratios = [r["activity_ratio"] for r in rs if r["activity_ratio"] is not None]
        sw = [r["activity_switching_w"]/r["activity_total_w"] for r in rs]
        intl = [r["activity_internal_w"]/r["activity_total_w"] for r in rs]
        mu_p, sd_p = mean_std(ap)
        mu_r, sd_r = mean_std(ratios)
        mu_sw, _   = mean_std(sw)
        mu_in, _   = mean_std(intl)
        aggregates[(vl, vm)] = {
            "n": len(rs),
            "mu_p": mu_p, "sd_p": sd_p,
            "mu_r": mu_r, "sd_r": sd_r,
            "cv_p": sd_p / mu_p if mu_p else float("nan"),
        }
        out.append(f"| {vl}_{vm} | {len(rs)} | "
                   f"{fmt_pm(mu_p, sd_p, scale=1000.0, dp=2)} | "
                   f"{fmt_pm(mu_r, sd_r, dp=3)} | "
                   f"{mu_sw*100:.1f}% | {mu_in*100:.1f}% |")
    out.append("")

    # ---- Headline TLG advantage tables ----
    out.append("## Headline TLG advantages under activity-aware power\n")
    out.append("Sign convention: positive = TLG wins. "
               "Advantage = (handopt − tlg) / handopt × 100%.\n")
    out.append("| pair | TLG mean (mW) | handopt mean (mW) | "
               "TLG advantage (mean) | seed-0 (single sample) |")
    out.append("|---|---:|---:|---:|---:|")

    def adv(mu_t, mu_h):
        return (mu_h - mu_t) / mu_h * 100.0 if mu_h else float("nan")

    rows_tlg_hc = sorted(by_variant(rows, "tlg", "hc"),     key=lambda r: r["seed_id"])
    rows_hop_hc = sorted(by_variant(rows, "handopt", "hc"), key=lambda r: r["seed_id"])
    rows_tlg_ld = sorted(by_variant(rows, "tlg", "ld"),     key=lambda r: r["seed_id"])
    rows_hop_ld = sorted(by_variant(rows, "handopt", "ld"), key=lambda r: r["seed_id"])

    for label, ts, hs in [("TLG hc vs handopt hc", rows_tlg_hc, rows_hop_hc),
                          ("TLG ld vs handopt ld", rows_tlg_ld, rows_hop_ld)]:
        if not ts or not hs:
            continue
        mu_t, _ = mean_std([r["activity_total_w"] for r in ts])
        mu_h, _ = mean_std([r["activity_total_w"] for r in hs])
        # Per-seed advantage (paired seeds, then mean ± stdev)
        per_seed_adv = []
        for tr in ts:
            hr = next((h for h in hs if h["seed_id"] == tr["seed_id"]), None)
            if hr:
                per_seed_adv.append(adv(tr["activity_total_w"], hr["activity_total_w"]))
        mu_a, sd_a = mean_std(per_seed_adv)
        # Seed 0 single-sample
        s0_adv = next(((adv(t["activity_total_w"], h["activity_total_w"]))
                       for t in ts for h in hs
                       if t["seed_id"] == 0 and h["seed_id"] == 0), None)
        s0_str = f"{s0_adv:.2f}%" if s0_adv is not None else "—"
        out.append(f"| **{label}** | {mu_t*1000:.2f} | {mu_h*1000:.2f} | "
                   f"**{mu_a:.2f}% ± {sd_a:.2f}%** | {s0_str} |")
    out.append("")

    # ---- Single-seed → 3-seed delta vs 2B.5 ----
    out.append("## Single-seed → 3-seed delta on the activity-aware "
               "headlines (parallels the 2B.5 §4.3 table)\n")
    out.append("| comparison | 2C seed-0 | 2C 3-seed mean | movement |")
    out.append("|---|---:|---:|---|")

    def adv_pair_seed(ts, hs, sd):
        tr = next((t for t in ts if t["seed_id"] == sd), None)
        hr = next((h for h in hs if h["seed_id"] == sd), None)
        if not tr or not hr:
            return None
        return adv(tr["activity_total_w"], hr["activity_total_w"])

    def adv_pair_mean(ts, hs):
        per = []
        for tr in ts:
            hr = next((h for h in hs if h["seed_id"] == tr["seed_id"]), None)
            if hr:
                per.append(adv(tr["activity_total_w"], hr["activity_total_w"]))
        return mean_std(per)

    for label, ts, hs in [("TLG hc vs handopt hc — power", rows_tlg_hc, rows_hop_hc),
                          ("TLG ld vs handopt ld — power", rows_tlg_ld, rows_hop_ld)]:
        s0 = adv_pair_seed(ts, hs, 0)
        mu, sd = adv_pair_mean(ts, hs)
        if s0 is None or math.isnan(mu):
            continue
        delta = mu - s0
        marker = "widens" if delta > 0.5 else ("tightens" if delta < -0.5 else "stable")
        out.append(f"| {label} | {s0:.2f}% | {mu:.2f}% ± {sd:.2f}% | {marker} ({delta:+.2f} pp) |")
    out.append("")

    # ---- Cross-reference vs 2B.5 default-activity ----
    out.append("## Default-activity (2B.5) vs activity-aware (2C) — "
               "TLG advantage by methodology\n")
    out.append("Default-activity numbers are 2B.5's published results "
               "(`power__total` from the existing post-route metrics.json). "
               "Activity-aware are this session.\n")
    out.append("| pair | default-activity (2B.5) | activity-aware (2C) | "
               "movement |")
    out.append("|---|---:|---:|---|")

    def def_adv(ts, hs):
        per = []
        for tr in ts:
            hr = next((h for h in hs if h["seed_id"] == tr["seed_id"]), None)
            if hr and tr.get("default_total_w") and hr.get("default_total_w"):
                per.append(adv(tr["default_total_w"], hr["default_total_w"]))
        return mean_std(per)

    for label, ts, hs in [("TLG hc vs handopt hc", rows_tlg_hc, rows_hop_hc),
                          ("TLG ld vs handopt ld", rows_tlg_ld, rows_hop_ld)]:
        d_mu, d_sd = def_adv(ts, hs)
        a_mu, a_sd = adv_pair_mean(ts, hs)
        if math.isnan(d_mu) or math.isnan(a_mu):
            continue
        delta = a_mu - d_mu
        marker = "**WIDENS**" if delta > 1.0 else ("**SHRINKS**" if delta < -1.0 else "stable")
        out.append(f"| **{label}** | {d_mu:.2f}% ± {d_sd:.2f}% | "
                   f"{a_mu:.2f}% ± {a_sd:.2f}% | {marker} ({delta:+.2f} pp) |")
    out.append("")

    # ---- CV comparison ----
    out.append("## Variance comparison vs 2B.5\n")
    out.append("2B.5 default-activity power CV (across 3 hc seeds):\n"
               "- TLG hc: 1.4%\n"
               "- handopt hc: 5.3%\n")
    out.append("Phase 2C activity-aware power CV (across 3 hc seeds):\n")
    for vl, vm in [("tlg", "hc"), ("handopt", "hc")]:
        a = aggregates.get((vl, vm))
        if a:
            out.append(f"- {vl}_{vm}: {a['cv_p']*100:.2f}%")
    out.append("")
    out.append("Phase 2C activity-aware power CV (across 3 ld weight programs):\n")
    for vl, vm in [("tlg", "ld"), ("handopt", "ld")]:
        a = aggregates.get((vl, vm))
        if a:
            out.append(f"- {vl}_{vm}: {a['cv_p']*100:.2f}%")
    out.append("")

    return "\n".join(out)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--out-csv", type=Path,
                   default=RESULTS / "summary.csv")
    p.add_argument("--out-md", type=Path,
                   default=RESULTS / "summary.md")
    args = p.parse_args()

    rows = collect()
    n_present = sum(1 for r in rows if not r.get("missing"))
    print(f"collected {n_present}/12 power measurements")
    missing = [r for r in rows if r.get("missing")]
    if missing:
        for r in missing:
            print(f"  MISSING: {r['variant_logic']}_{r['variant_mode']} s{r['seed_id']}  ({r['run_key']})")
    write_csv(rows, args.out_csv)
    print(f"wrote {args.out_csv}")
    args.out_md.write_text(render_md(rows))
    print(f"wrote {args.out_md}")


if __name__ == "__main__":
    main()
