// =============================================================================
// tb_soc_smoke.sv — Phase-3C SoC smoke testbench.
//
// Instantiates soc_top with INIT_HEX pointing at the smoke firmware, drives
// clk + a multi-cycle reset, and watches for two markers:
//
//   - gpio_o[7:0] == 8'hBE          : firmware reached the OUT write,
//     proving the WB master/interconnect/GPIO path is live and byte-strobed
//     writes are honoured.
//   - u_gpio.sim_end_q == 32'hCAFEBABE : firmware reached the SIM_END write,
//     proving the firmware ran to completion and 32-b stores work.
//
// Both observed → "SOC SMOKE TEST: PASS". Either missing within 100K cycles
// → "SOC SMOKE TEST: FAIL (timeout)" with diagnostic dump of the last
// few WB master transactions.
//
// Optional PC trace: a small ring buffer logs the address of each acked
// instruction-fetch-class transaction for the first 64 transactions; on
// failure it prints them. To keep the TB self-contained we treat any read
// (we_o=0) as instruction-class for the trace — close enough for a smoke
// test where the firmware reads no data.
// =============================================================================
`default_nettype none
`timescale 1 ns / 1 ps

module tb_soc_smoke;

    // Clock + reset.
    reg clk = 1'b0;
    always #5 clk = ~clk;     // 100 MHz

    reg rst_n_i = 1'b0;
    initial begin
        // Hold reset for >= 16 cycles (well past the 2-FF synchronizer).
        repeat (16) @(posedge clk);
        rst_n_i <= 1'b1;
    end

    // GPIO ports.
    reg  [7:0] gpio_i = 8'h00;
    wire [7:0] gpio_o;

    // DUT.
    soc_top #(
        .INIT_HEX("firmware/smoke/firmware.hex")
    ) dut (
        .clk     (clk),
        .rst_n_i (rst_n_i),
        .gpio_i  (gpio_i),
        .gpio_o  (gpio_o)
    );

    // -------------------------------------------------------------------------
    // Cycle counter + timeout.
    // -------------------------------------------------------------------------
    integer cycles = 0;
    always @(posedge clk) cycles <= cycles + 1;

    localparam integer TIMEOUT_CYCLES = 100_000;

    // -------------------------------------------------------------------------
    // Markers.
    // -------------------------------------------------------------------------
    reg gpio_out_seen = 1'b0;
    reg sentinel_seen = 1'b0;

    always @(posedge clk) begin
        if (rst_n_i) begin
            if (!gpio_out_seen && (gpio_o == 8'hBE)) begin
                gpio_out_seen <= 1'b1;
                $display("[%0t] tb_soc_smoke: gpio_o = 0x%02h observed (cycle %0d)",
                         $time, gpio_o, cycles);
            end
            if (!sentinel_seen && (dut.u_gpio.sim_end_q == 32'hCAFEBABE)) begin
                sentinel_seen <= 1'b1;
                $display("[%0t] tb_soc_smoke: sim_end_q = 0xCAFEBABE observed (cycle %0d)",
                         $time, cycles);
            end
        end
    end

    // -------------------------------------------------------------------------
    // PC / bus trace (small ring buffer for failure diagnostics).
    // -------------------------------------------------------------------------
    localparam integer TRACE_DEPTH = 64;
    reg [31:0] trace_adr [0:TRACE_DEPTH-1];
    reg        trace_we  [0:TRACE_DEPTH-1];
    reg [31:0] trace_dat [0:TRACE_DEPTH-1];
    integer    trace_n = 0;

    wire        m_cyc = dut.m_cyc;
    wire        m_stb = dut.m_stb;
    wire        m_ack = dut.m_ack;
    wire        m_we  = dut.m_we;
    wire [31:0] m_adr = dut.m_adr;
    wire [31:0] m_dat_w = dut.m_dat_w;

    always @(posedge clk) begin
        if (rst_n_i && m_cyc && m_stb && m_ack && (trace_n < TRACE_DEPTH)) begin
            trace_adr[trace_n] <= m_adr;
            trace_we [trace_n] <= m_we;
            trace_dat[trace_n] <= m_dat_w;
            trace_n            <= trace_n + 1;
        end
    end

    // -------------------------------------------------------------------------
    // Pass/fail decision.
    // -------------------------------------------------------------------------
    integer i;
    initial begin
        // VCD optional — uncomment for debug.
        // $dumpfile("/tmp/tb_soc_smoke.vcd");
        // $dumpvars(0, tb_soc_smoke);

        wait (rst_n_i === 1'b1);

        // Wait for both markers, or timeout.
        fork
            begin : pass_watcher
                wait (gpio_out_seen && sentinel_seen);
                #1;
                $display("[%0t] SOC SMOKE TEST: PASS  (cycles=%0d, transactions=%0d)",
                         $time, cycles, trace_n);
                if ($test$plusargs("verbose")) begin
                    $display("  acked WB transactions:");
                    for (i = 0; i < trace_n; i = i + 1) begin
                        $display("    [%0d] adr=0x%08h  we=%0d  dat=0x%08h",
                                 i, trace_adr[i], trace_we[i], trace_dat[i]);
                    end
                end
                $finish;
            end
            begin : timeout_watcher
                repeat (TIMEOUT_CYCLES) @(posedge clk);
                $display("[%0t] SOC SMOKE TEST: FAIL (timeout at %0d cycles)",
                         $time, cycles);
                $display("  gpio_out_seen = %0d  sentinel_seen = %0d",
                         gpio_out_seen, sentinel_seen);
                $display("  last gpio_o = 0x%02h", gpio_o);
                $display("  last %0d acked WB transactions:", trace_n);
                for (i = 0; i < trace_n; i = i + 1) begin
                    $display("    [%0d] adr=0x%08h  we=%0d  dat=0x%08h",
                             i, trace_adr[i], trace_we[i], trace_dat[i]);
                end
                $fatal(1, "smoke test timed out");
            end
        join_any
        disable fork;
    end

endmodule

`default_nettype wire
