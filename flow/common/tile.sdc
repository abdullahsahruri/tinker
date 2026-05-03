# Sequential tile SDC.
#
# The Phase-2 tile has a real clock (`clk`), a synchronous reset
# (`rst_n` — sampled inside `always @(posedge clk)`), an input flop on
# x_in/x_valid and an output flop on y_out/y_valid. We constrain it as
# a normal synchronous block: a real clock on clk, register-to-register
# paths covered by that clock, and I/O timing referenced to it. rst_n
# is treated like any other synchronous input — it has a real setup
# requirement at the input flop.
#
# I/O delay choice: 25% of CLOCK_PERIOD is the standard default at the
# block level when the surrounding logic is unknown — it allocates
# 2.5 ns each for upstream-driver→input-flop and output-flop→downstream
# at a 10 ns period, leaving ~5 ns for the comb path between the
# register endpoints. Phase 1 measured the equivalent combinational
# fan-in/popcount path well under 5 ns at the slow corner, so this
# leaves real margin without making the constraint trivially easy.
#
# Pattern note: `[all_inputs]` minus the clock port is built with
# `lsearch` + `lreplace` rather than `remove_from_collection` because
# OpenSTA in librelane 3.0.3 does not provide the latter. This matches
# the pattern used by librelane's bundled `base.sdc`.
#
# Identical SDC across all four tile variants for fair comparison.

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

# Drive strength on inputs and load on outputs so the path delays are
# not computed on ideal-source/no-load assumptions.
set driving_cell [lindex [split $::env(SYNTH_DRIVING_CELL) "/"] 0]
set driving_pin  [lindex [split $::env(SYNTH_DRIVING_CELL) "/"] 1]
set_driving_cell -lib_cell $driving_cell -pin $driving_pin $non_clock_inputs

set cap_load [expr $::env(OUTPUT_CAP_LOAD) / 1000.0]
set_load $cap_load [all_outputs]
