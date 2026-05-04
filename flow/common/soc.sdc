# SoC SDC.
#
# Synchronous SoC: one real clock (`clk`), async-asserted/sync-deasserted
# reset (`rst_n_i` — fed to a 2-FF synchronizer inside `soc_top`), and
# 8-bit `gpio_i`/`gpio_o` boundary nets. We constrain it as a normal
# synchronous block: a real clock on clk, register-to-register paths
# covered by that clock, and I/O timing referenced to it. `rst_n_i`
# is treated like any other synchronous input — the synchronizer's
# first flop has a real setup requirement at the clk edge, so the
# 2.5 ns input delay we apply elsewhere is appropriate.
#
# I/O delay choice: 25% of CLOCK_PERIOD, identical to the Phase-2
# tile.sdc. With CLOCK_PERIOD=10 ns this allocates 2.5 ns each for
# upstream-driver→input-flop and output-flop→downstream, leaving
# ~5 ns for the comb path between register endpoints. The SoC's
# only chip-boundary inputs are clk + rst_n_i + gpio_i[7:0] (10
# pins) and outputs are gpio_o[7:0]; none of these are on the
# critical path, so the 25% allocation is generous.
#
# Pattern note: `[all_inputs]` minus the clock port is built with
# `lsearch` + `lreplace` rather than `remove_from_collection` because
# OpenSTA in librelane 3.0.3 does not provide the latter. This
# matches `flow/common/tile.sdc` and librelane's bundled `base.sdc`.
#
# Identical SDC parameter set as `tile.sdc` (CLOCK_PERIOD,
# MAX_FANOUT_CONSTRAINT, MAX_TRANSITION_CONSTRAINT,
# SYNTH_DRIVING_CELL, OUTPUT_CAP_LOAD) for fair Phase 2 ↔ Phase 3
# comparison.

create_clock -name clk -period $::env(CLOCK_PERIOD) [get_ports clk]

set io_delay [expr 0.25 * $::env(CLOCK_PERIOD)]

set clk_input [get_port clk]
set clk_indx  [lsearch [all_inputs] $clk_input]
set non_clock_inputs [lreplace [all_inputs] $clk_indx $clk_indx ""]

set_input_delay  $io_delay -clock [get_clocks clk] $non_clock_inputs
set_output_delay $io_delay -clock [get_clocks clk] [all_outputs]

set_max_fanout $::env(MAX_FANOUT_CONSTRAINT) [current_design]
if { [info exists ::env(MAX_TRANSITION_CONSTRAINT)] } {
    set_max_transition $::env(MAX_TRANSITION_CONSTRAINT) [current_design]
}

set driving_cell [lindex [split $::env(SYNTH_DRIVING_CELL) "/"] 0]
set driving_pin  [lindex [split $::env(SYNTH_DRIVING_CELL) "/"] 1]
set_driving_cell -lib_cell $driving_cell -pin $driving_pin $non_clock_inputs

set cap_load [expr $::env(OUTPUT_CAP_LOAD) / 1000.0]
set_load $cap_load [all_outputs]
