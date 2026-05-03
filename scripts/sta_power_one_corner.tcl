# Phase 2C — activity-aware power on the existing post-route netlist for one corner.
#
# Inputs (set by the caller via env):
#   STA_LIB                — sky130 .lib for this corner
#   STA_NETLIST            — post-route Verilog netlist (e.g. final/pnl/<top>.pnl.v)
#   STA_TOP                — top-level module name (e.g. tile_tlg_hc_s1)
#   STA_SDC                — flow/common/tile.sdc
#   STA_SPEF               — corner-specific SPEF parasitics
#   STA_VCD                — VCD dump from RTL simulation
#   STA_VCD_SCOPE          — hierarchical scope of the DUT in the VCD (e.g. tb_power/dut)
#   STA_CORNER_NAME        — for labeling reports (e.g. max_ff_n40C_1v95)
#   STA_REPORT_DIR         — where to drop power.rpt and power.metrics.json
#
# This is OpenSTA standalone (matches the librelane sta -no_splash -exit
# corner.tcl invocation pattern, but only for the power stage).

set lib_file       $::env(STA_LIB)
set netlist_file   $::env(STA_NETLIST)
set top_module     $::env(STA_TOP)
set sdc_file       $::env(STA_SDC)
set spef_file      $::env(STA_SPEF)
set vcd_file       $::env(STA_VCD)
set vcd_scope      $::env(STA_VCD_SCOPE)
set corner_name    $::env(STA_CORNER_NAME)
set report_dir     $::env(STA_REPORT_DIR)

file mkdir $report_dir

set_cmd_units \
    -time ns \
    -capacitance pF \
    -current mA \
    -voltage V \
    -resistance kOhm \
    -distance um

# Single-corner OpenSTA flow: define the corner, load the matching liberty,
# read the netlist (filler / tap cells become harmless black boxes and don't
# contribute to power), link, read SDC, read parasitics, then activity.
define_corners $corner_name
read_liberty -corner $corner_name $lib_file
read_verilog $netlist_file
link_design $top_module
read_sdc $sdc_file
read_spef -corner $corner_name $spef_file

# Activity. OpenSTA in librelane 3.0.3 supports `read_power_activities -vcd`
# directly (no SAIF tooling shipped). The -scope strips the wrapper hierarchy
# so signal names match the linked design's port nets.
read_power_activities -scope $vcd_scope -vcd $vcd_file

# Run the full per-corner report and write a textual summary to disk.
# OpenSTA in librelane 3.0.3 doesn't expose `redirect` or `redirect_file_begin`,
# so we build the text by hand using the TCL APIs (`sta::design_power` and
# `sta::group_power`) and call `report_power` on stdout for the docker log.
set rpt_path [file join $report_dir power.rpt]
set fp [open $rpt_path w]
puts $fp "===== Phase 2C activity-aware power"
puts $fp "  top:           $top_module"
puts $fp "  corner:        $corner_name"
puts $fp "  liberty:       $lib_file"
puts $fp "  netlist:       $netlist_file"
puts $fp "  spef:          $spef_file"
puts $fp "  vcd:           $vcd_file"
puts $fp "  vcd_scope:     $vcd_scope"
puts $fp "============================================================="
puts $fp ""

# Pull totals + per-group data via the underlying API (so the report is
# self-contained and matches the JSON metrics emitted below).
set corner_obj [sta::find_corner $corner_name]
set design_pw [sta::design_power $corner_obj]
set d_internal  [lindex $design_pw 0]
set d_switching [lindex $design_pw 1]
set d_leakage   [lindex $design_pw 2]
set d_total     [lindex $design_pw 3]

puts $fp [format "%-15s %12s %12s %12s %12s" \
            "Group" "Internal" "Switching" "Leakage" "Total"]
puts $fp [string repeat - 67]
foreach grp {Sequential Combinational Clock Macro Pad} {
    if {[catch {sta::group_power $corner_obj $grp} gp]} {
        continue
    }
    set gi  [lindex $gp 0]
    set gs  [lindex $gp 1]
    set gl  [lindex $gp 2]
    set gt  [lindex $gp 3]
    puts $fp [format "%-15s %12.4e %12.4e %12.4e %12.4e" $grp $gi $gs $gl $gt]
}
puts $fp [string repeat - 67]
puts $fp [format "%-15s %12.4e %12.4e %12.4e %12.4e" \
            "Total" $d_internal $d_switching $d_leakage $d_total]
close $fp

# Also dump the standard report_power textual block on stdout, so the
# docker log captures it for forensic review.
puts ""
puts "------ report_power -corner $corner_name ------"
report_power -corner $corner_name

# Reuse the totals already extracted above; emit JSON for downstream tooling.
set jp [open [file join $report_dir power.metrics.json] w]
puts $jp "{"
puts $jp "  \"corner\": \"$corner_name\","
puts $jp "  \"top\": \"$top_module\","
puts $jp "  \"power__internal__total\": $d_internal,"
puts $jp "  \"power__switching__total\": $d_switching,"
puts $jp "  \"power__leakage__total\": $d_leakage,"
puts $jp "  \"power__total\": $d_total"
puts $jp "}"
close $jp

puts "STA_POWER_ONE_CORNER_DONE corner=$corner_name total=$d_total"
exit 0
