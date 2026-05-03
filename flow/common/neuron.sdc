# Combinational neuron SDC.
#
# The neuron has no clock and no flip-flops; it is a pure logic block. We
# create a virtual clock with the LibreLane-supplied CLOCK_PERIOD and pin
# all primary inputs/outputs to that clock with zero I/O delay so that the
# longest combinational path from any input to any output becomes the
# constraint. Worst setup slack at the slow corner therefore reports the
# margin against (period - max_combinational_delay).
#
# Identical SDC across the naive / handopt / tlg variants for fair comparison.

create_clock -name virt -period $::env(CLOCK_PERIOD)
set_input_delay  0 -clock [get_clocks virt] [all_inputs]
set_output_delay 0 -clock [get_clocks virt] [all_outputs]

set_max_fanout $::env(MAX_FANOUT_CONSTRAINT) [current_design]
if { [info exists ::env(MAX_TRANSITION_CONSTRAINT)] } {
    set_max_transition $::env(MAX_TRANSITION_CONSTRAINT) [current_design]
}

# Drive strength on inputs and load on outputs so the path delays are not
# computed on ideal-source/no-load assumptions.
set driving_cell [lindex [split $::env(SYNTH_DRIVING_CELL) "/"] 0]
set driving_pin  [lindex [split $::env(SYNTH_DRIVING_CELL) "/"] 1]
set_driving_cell -lib_cell $driving_cell -pin $driving_pin [all_inputs]

set cap_load [expr $::env(OUTPUT_CAP_LOAD) / 1000.0]
set_load $cap_load [all_outputs]
