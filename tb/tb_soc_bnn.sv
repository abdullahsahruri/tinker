// =============================================================================
// tb_soc_bnn.sv — Phase-3D end-to-end BNN inference testbench.
//
// Drives the full SoC (firmware/inference/firmware.hex) over 16 MNIST test
// images preloaded into DMEM at word offsets 0..31. Snoops the WB master
// bus for per-image GPIO writes, captures the firmware's predictions, and
// compares them to the precomputed Python-golden expectations
// (tb/tb_bnn_expected.hex).
//
// PASS criterion: match_n >= MATCH_FLOOR (default 14 of 16) AND the final
// 0xCAFEBABE sentinel observed within TIMEOUT_CYCLES.
//
// Hierarchical preloads — `dut.u_dmem.mem` is the slave's flat regfile, set
// by the TB after reset deassertion (wb_dmem's `initial` block already zeros
// it at sim time 0).
// =============================================================================
`default_nettype none
`timescale 1 ns / 1 ps

module tb_soc_bnn;

    // ---- Clock + reset ----------------------------------------------------
    reg clk = 1'b0;
    always #5 clk = ~clk;     // 100 MHz

    reg rst_n_i = 1'b0;
    initial begin
        repeat (16) @(posedge clk);
        rst_n_i <= 1'b1;
    end

    // ---- GPIO ports -------------------------------------------------------
    reg  [7:0] gpio_i = 8'h00;
    wire [7:0] gpio_o;

    // ---- DUT --------------------------------------------------------------
    soc_top #(
        .INIT_HEX("firmware/inference/firmware.hex")
    ) dut (
        .clk     (clk),
        .rst_n_i (rst_n_i),
        .gpio_i  (gpio_i),
        .gpio_o  (gpio_o)
    );

    // ---- Cycle counter + timeout -----------------------------------------
    integer cycles = 0;
    always @(posedge clk) cycles <= cycles + 1;

    localparam integer TIMEOUT_CYCLES = 5_000_000;

    // ---- Image + expected loaders ----------------------------------------
    localparam integer N_IMAGES = 16;
    localparam integer DMEM_WORDS = 2 * N_IMAGES;     // 32 words
    reg [31:0] xs_loader [0:DMEM_WORDS-1];
    reg [7:0]  expected  [0:N_IMAGES-1];
    integer load_i;
    initial begin
        $readmemh("tb/tb_bnn_xs.hex",       xs_loader);
        $readmemh("tb/tb_bnn_expected.hex", expected);
    end

    // After reset deassertion, copy the loader into DMEM hierarchically so
    // the firmware sees the test images at DMEM_BASE = 0x1000_0000.
    initial begin : preload_dmem
        wait (rst_n_i === 1'b1);
        @(posedge clk);
        for (load_i = 0; load_i < DMEM_WORDS; load_i = load_i + 1) begin
            dut.u_dmem.mem[load_i] = xs_loader[load_i];
        end
    end

    // ---- Per-image observer ----------------------------------------------
    // Snoop acked WB writes:
    //   adr 0x3000_0004 = GPIO_OUT (firmware writes the predicted class)
    //   adr 0x3000_0000 = GPIO_SIM_END (per-image sentinel 0xC0FE000X
    //                                   or final 0xCAFEBABE)
    // Predictions and sentinels arrive in lockstep, one per image, in order.
    reg [7:0]  soc_pred [0:N_IMAGES-1];
    integer    image_idx = 0;
    reg        done_flag = 1'b0;
    reg [7:0]  last_pred = 8'h00;   // latched on the most recent GPIO_OUT write

    wire        m_cyc = dut.m_cyc;
    wire        m_stb = dut.m_stb;
    wire        m_ack = dut.m_ack;
    wire        m_we  = dut.m_we;
    wire [31:0] m_adr = dut.m_adr;
    wire [31:0] m_dat_w = dut.m_dat_w;

    integer init_pred_i;
    initial begin
        for (init_pred_i = 0; init_pred_i < N_IMAGES; init_pred_i = init_pred_i + 1)
            soc_pred[init_pred_i] = 8'hFF;     // sentinel for "never written"
    end

    always @(posedge clk) begin
        if (rst_n_i && m_cyc && m_stb && m_ack && m_we) begin
            if (m_adr == 32'h3000_0004) begin
                last_pred <= m_dat_w[7:0];
            end
            if (m_adr == 32'h3000_0000) begin
                if ((m_dat_w & 32'hFFFF_0000) == 32'hC0FE_0000) begin
                    if (image_idx < N_IMAGES) begin
                        soc_pred[image_idx] <= last_pred;
                        $display("[cycle %0d] img[%0d]: pred=%0d  expected=%0d  sentinel=0x%08h  %s",
                                 cycles, image_idx, last_pred, expected[image_idx],
                                 m_dat_w,
                                 (last_pred == expected[image_idx]) ? "OK" : "MISS");
                        image_idx <= image_idx + 1;
                    end
                end else if (m_dat_w == 32'hCAFE_BABE) begin
                    done_flag <= 1'b1;
                end
            end
        end
    end

    // ---- WB transaction trace (last N) for failure diagnostics -----------
    localparam integer TRACE_DEPTH = 256;
    reg [31:0] trace_adr [0:TRACE_DEPTH-1];
    reg        trace_we  [0:TRACE_DEPTH-1];
    reg [31:0] trace_dat [0:TRACE_DEPTH-1];
    integer    trace_n = 0;
    always @(posedge clk) begin
        if (rst_n_i && m_cyc && m_stb && m_ack) begin
            trace_adr[trace_n % TRACE_DEPTH] <= m_adr;
            trace_we [trace_n % TRACE_DEPTH] <= m_we;
            trace_dat[trace_n % TRACE_DEPTH] <= m_dat_w;
            trace_n <= trace_n + 1;
        end
    end

    // ---- Pass / fail decision --------------------------------------------
    integer i;
    integer match_n;
    integer dump_start;
    integer dump_n;
    integer dump_off;
    initial begin
        // Optional VCD: vvp +vcd
        if ($test$plusargs("vcd")) begin
            $dumpfile("/tmp/tb_soc_bnn.vcd");
            $dumpvars(0, tb_soc_bnn);
        end

        wait (rst_n_i === 1'b1);

        fork
            begin : pass_watcher
                wait (done_flag === 1'b1);
                #1;
                match_n = 0;
                for (i = 0; i < N_IMAGES; i = i + 1) begin
                    if (soc_pred[i] == expected[i]) match_n = match_n + 1;
                end
                $display("");
                $display("=== BNN INFERENCE RESULTS ===");
                for (i = 0; i < N_IMAGES; i = i + 1) begin
                    $display("  img[%0d]: soc=%0d  expected=%0d  %s",
                             i, soc_pred[i], expected[i],
                             (soc_pred[i] == expected[i]) ? "OK" : "MISS");
                end
                $display("");
                $display("BNN INFERENCE TEST: %s (%0d/%0d)  cycles=%0d  xacts=%0d",
                         (match_n >= 14) ? "PASS" : "FAIL",
                         match_n, N_IMAGES, cycles, trace_n);
                $finish;
            end
            begin : timeout_watcher
                repeat (TIMEOUT_CYCLES) @(posedge clk);
                $display("");
                $display("BNN INFERENCE TEST: FAIL (timeout at %0d cycles)", cycles);
                $display("  images completed = %0d/%0d", image_idx, N_IMAGES);
                $display("  last predicted   = %0d", last_pred);
                $display("  done_flag        = %0d", done_flag);
                $display("  WB transactions  = %0d (showing last %0d):",
                         trace_n,
                         (trace_n < TRACE_DEPTH) ? trace_n : TRACE_DEPTH);
                dump_n = (trace_n < TRACE_DEPTH) ? trace_n : TRACE_DEPTH;
                dump_start = (trace_n < TRACE_DEPTH) ? 0
                                                    : (trace_n - TRACE_DEPTH);
                for (i = 0; i < dump_n; i = i + 1) begin
                    dump_off = (dump_start + i) % TRACE_DEPTH;
                    $display("    [%0d] adr=0x%08h we=%0d dat=0x%08h",
                             dump_start + i,
                             trace_adr[dump_off],
                             trace_we [dump_off],
                             trace_dat[dump_off]);
                end
                $fatal(1, "bnn inference timed out");
            end
        join_any
        disable fork;
    end

endmodule

`default_nettype wire
