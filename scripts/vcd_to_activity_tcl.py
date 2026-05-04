#!/usr/bin/env python3
"""vcd_to_activity_tcl.py — parse a VCD and emit OpenSTA `set_power_activity`
TCL calls for every interior signal that names a net in the post-P&R
netlist.

Why: OpenSTA's `read_vcd` only annotates design *port* pins (the 18 chip
pins of soc_top here). Interior pins fall back to a default activity,
which collapses combinational power to ~0 in our SoC measurement. To
get a true activity-aware decomposition we have to compute per-net
toggle rates from the VCD and apply them to the design's interior
pins explicitly.

This tool:
1. Parses a VCD at the "$dumpvars(0, tb)" depth produced by iverilog.
2. For every signal whose hierarchy starts with `--src-scope`, computes
     activity = #toggles / #clock_cycles
     duty     = fraction_of_time_at_1
3. Strips the src-scope prefix and emits a TCL line for the resulting
   relative name. The relative name is dotted, matching the post-flatten
   netlist's escaped-identifier wires (e.g. `u_cpu.u_core.mem_addr[2]`).

The emitted TCL applies activity to the input pins driven by each net
(net → input pins of fan-out cells). Output pins inherit activity from
the cell's input toggles via OpenSTA's combinational propagation, so we
only need to set the input-pin side.

Example use:
  python3 vcd_to_activity_tcl.py /tmp/tb_soc_bnn.flat.vcd \\
      --src-scope tb_soc_bnn.dut \\
      --clock-period-ns 10 \\
      -o results/phase3/power/buckets/activities.tcl
"""
import argparse
import re
import sys
import time
from pathlib import Path


def parse_args():
    ap = argparse.ArgumentParser()
    ap.add_argument("vcd")
    ap.add_argument("--src-scope", required=True,
                    help="dot-separated VCD scope path to strip "
                         "(signals below this become design-relative).")
    ap.add_argument("--clock-period-ns", type=float, required=True,
                    help="clock period in ns; used to convert simulation "
                         "time to clock cycles.")
    ap.add_argument("-o", "--output", required=True,
                    help="output TCL file.")
    ap.add_argument("--top-clock-net", default="clk",
                    help="design's top-level clock net name; activities "
                         "for the clock are NOT emitted (clock activity is "
                         "set by create_clock).")
    return ap.parse_args()


def main():
    args = parse_args()
    src = args.src_scope.split(".")

    # Read all of the VCD up-front (it's only ~100 MB for our 234K-cycle
    # inference run).
    text = Path(args.vcd).read_text()

    # --- Parse the header ---
    # Build {short_id: (full_dotted_name, width)} for signals below src-scope.
    # Track $timescale.
    timescale_ps = None
    sigs = {}      # short_id -> (full_dotted_relative_name, width)
    scope_stack = []
    body_start = 0

    line_re = re.compile(r"^(.*)$", re.MULTILINE)
    pos = 0
    in_var_block = True
    while in_var_block:
        end = text.find("\n", pos)
        if end < 0:
            break
        line = text[pos:end].strip()
        pos = end + 1
        if not line:
            continue
        if line.startswith("$timescale"):
            # $timescale 1 ns $end  OR multi-line. Simplify: scan until $end.
            ts_text = line
            while "$end" not in ts_text:
                e2 = text.find("\n", pos)
                ts_text += " " + text[pos:e2].strip()
                pos = e2 + 1
            m = re.search(r"(\d+)\s*(fs|ps|ns|us|ms|s)", ts_text)
            if m:
                v = int(m.group(1)); u = m.group(2)
                mult_to_ps = {"fs": 0.001, "ps": 1, "ns": 1000,
                              "us": 1e6, "ms": 1e9, "s": 1e12}
                timescale_ps = v * mult_to_ps[u]
            continue
        if line.startswith("$scope"):
            toks = line.split()
            scope_stack.append(toks[2])
            continue
        if line.startswith("$upscope"):
            scope_stack.pop()
            continue
        if line.startswith("$var"):
            toks = line.split()
            if toks[-1] != "$end":
                continue
            width = int(toks[2])
            ident = toks[3]
            name = toks[4]
            rest = toks[5:-1]  # bit-range tokens
            # Below src-scope?
            if (len(scope_stack) >= len(src)
                    and scope_stack[: len(src)] == src):
                rel_path = scope_stack[len(src):]
                full_name = ".".join(rel_path + [name]) if rel_path else name
                if rest:
                    full_name = full_name + " " + " ".join(rest)
                sigs[ident] = (full_name, width)
            continue
        if line == "$enddefinitions $end":
            body_start = pos
            in_var_block = False
            break

    if timescale_ps is None:
        timescale_ps = 1000  # default 1 ns
    period_ps = args.clock_period_ns * 1000

    # --- Parse the body to count toggles and time-at-1 per signal ---
    last_val = {}        # short_id -> '0'/'1'/'x'/'z'/multi-bit string
    toggles = {}         # short_id -> int (counts 0↔1 transitions, per bit)
    one_time = {}        # short_id -> sim-time spent at value 1 (per bit*ps)
    last_change_t = {}   # short_id -> sim-time last seen
    cur_t = 0
    final_t = 0

    body = text[body_start:]
    # Iterate body line by line. Common formats:
    #   #<time>            timestamp
    #   <bit><id>          1-bit value change (0/1/x/z + ident)
    #   b<bits> <id>       multi-bit
    #   r<float> <id>      real-valued
    for line in body.splitlines():
        if not line:
            continue
        c0 = line[0]
        if c0 == "#":
            cur_t = int(line[1:])
            if cur_t > final_t:
                final_t = cur_t
            continue
        if c0 in "01xzXZ":
            # 1-bit
            if len(line) < 2:
                continue
            val = c0
            ident = line[1:]
            if ident not in sigs:
                continue
            prev = last_val.get(ident, "x")
            # Update time-at-1 for prev
            if prev == "1":
                one_time[ident] = one_time.get(ident, 0) + (cur_t - last_change_t.get(ident, 0))
            last_change_t[ident] = cur_t
            # Toggle count: a 0↔1 transition
            if prev != val and prev in "01" and val in "01":
                toggles[ident] = toggles.get(ident, 0) + 1
            last_val[ident] = val
            continue
        if c0 == "b":
            # bN…N <id>
            sp = line.find(" ")
            if sp < 0:
                continue
            bits = line[1:sp]
            ident = line[sp + 1:]
            if ident not in sigs:
                continue
            prev = last_val.get(ident, "x")
            # toggles for multi-bit: count differing bit positions vs prev
            # (when both prev and bits are 01-only); pad/truncate to width.
            width = sigs[ident][1]
            cur_padded = bits.rjust(width, "0")[-width:]
            if prev != "x" and len(prev) == width and prev != cur_padded:
                # Count differing bits if both are pure 0/1.
                if all(c in "01" for c in prev) and all(c in "01" for c in cur_padded):
                    diff = sum(1 for a, b in zip(prev, cur_padded) if a != b)
                    toggles[ident] = toggles.get(ident, 0) + diff
            # one_time: sum bits at 1, integrate over time-at-this-value
            if prev != "x" and len(prev) == width and all(c in "01" for c in prev):
                ones = prev.count("1")
                one_time[ident] = one_time.get(ident, 0) + ones * (cur_t - last_change_t.get(ident, 0))
            last_change_t[ident] = cur_t
            last_val[ident] = cur_padded
            continue
        if c0 in "rR":
            continue
        if c0 == "$":  # $dumpvars/$dumpall/$dumpoff/$dumpon
            continue

    # --- Convert to per-cycle activities and emit TCL ---
    sim_total_cycles = final_t * timescale_ps / period_ps
    if sim_total_cycles <= 0:
        print("ERROR: simulation duration is 0", file=sys.stderr)
        sys.exit(1)

    out_lines = []
    out_lines.append(f"# Auto-generated by scripts/vcd_to_activity_tcl.py")
    out_lines.append(f"# Source VCD: {args.vcd}")
    out_lines.append(f"# Source scope: {args.src_scope}")
    out_lines.append(f"# Clock period: {args.clock_period_ns} ns")
    out_lines.append(f"# Simulation duration: {final_t} ticks "
                     f"({final_t * timescale_ps / 1e6:.2f} ms = "
                     f"{sim_total_cycles:.0f} cycles)")
    out_lines.append(f"# {len(sigs)} signals in scope; emitting activities "
                     f"for those that match design nets.")
    out_lines.append("")
    out_lines.append("# For each VCD signal: try to find the matching design")
    out_lines.append("# net, then apply set_power_activity to its input pins.")
    out_lines.append("# Failures (no matching net, or no input pins) are")
    out_lines.append("# silently skipped — many VCD signals correspond to")
    out_lines.append("# wires that Yosys collapsed during synthesis.")
    out_lines.append("")
    out_lines.append("set _ann_count 0")
    out_lines.append("set _miss_count 0")

    n_emitted = 0
    n_skipped_clock = 0
    for ident, (name, width) in sigs.items():
        # Strip bit-range tokens we tacked into the name string.
        bare = name.split(" ", 1)[0]  # the dotted hierarchy + bracketed bit
        # Skip the clock — its activity is set by create_clock.
        if bare == args.top_clock_net or bare.endswith("." + args.top_clock_net):
            n_skipped_clock += 1
            continue
        t = toggles.get(ident, 0)
        ot = one_time.get(ident, 0)
        # For multi-bit signals, the per-bit-average activity is what we
        # want to apply to driver pins (each bit-pin has its own activity).
        # OpenSTA's set_power_activity -pins applies the same value to all
        # listed pins, so we use the per-bit-per-cycle average toggle rate.
        if width >= 1:
            activity = (t / width) / sim_total_cycles
            duty = (ot / width) / final_t if final_t > 0 else 0.5
        else:
            activity = 0
            duty = 0.5
        # Clamp pathological duty values.
        duty = max(0.0, min(1.0, duty))
        # Skip dead-zero signals.
        if activity == 0 and duty == 0:
            continue
        # Bus / vector signals: VCD names them with a trailing " [N:M]".
        # OpenSTA stores each bit as a separate net named
        # "<base>[<idx>]" (post-flatten), so we have to enumerate the
        # bits explicitly. For 1-bit signals (no rest) we just match the
        # base name.
        bus_range = name.split(" ", 1)[1] if " " in name else ""
        if bus_range:
            mr = re.match(r"\[(\d+):(\d+)\]", bus_range)
            if mr:
                hi, lo = int(mr.group(1)), int(mr.group(2))
                bit_lo, bit_hi = min(hi, lo), max(hi, lo)
                # Build a TCL list of net patterns "<bare>[<i>]" for each
                # bit. get_nets with a list pattern matches all of them.
                bit_names = [f"{{{bare}[{i}]}}" for i in range(bit_lo, bit_hi + 1)]
                pattern = " ".join(bit_names)
            else:
                # Single-element vector or unusual range; fall back to base.
                pattern = f"{{{bare}}}"
        else:
            pattern = f"{{{bare}}}"
        out_lines.append(
            f"if {{[catch {{set _n [get_nets -quiet {pattern}]}}]"
            f" || $_n eq \"\"}} {{ incr _miss_count }} else {{"
        )
        out_lines.append(
            f"  set _p [get_pins -quiet -of_objects $_n -filter "
            f"\"direction == input\"]"
        )
        out_lines.append(
            f"  if {{$_p ne \"\"}} {{ "
            f"set_power_activity -pins $_p -activity {activity:.6e} -duty {duty:.4f}; "
            f"incr _ann_count "
            f"}} else {{ incr _miss_count }}"
        )
        out_lines.append("}")
        n_emitted += 1

    out_lines.append("")
    out_lines.append('puts "set_power_activity: annotated $_ann_count nets, '
                     '$_miss_count signals had no matching net or no input pins."')

    Path(args.output).write_text("\n".join(out_lines) + "\n")
    print(
        f"vcd_to_activity_tcl: scope={args.src_scope!r}, "
        f"signals={len(sigs)}, clock_skipped={n_skipped_clock}, "
        f"emitted={n_emitted}, sim_cycles={sim_total_cycles:.0f}",
        file=sys.stderr,
    )


if __name__ == "__main__":
    sys.exit(main())
