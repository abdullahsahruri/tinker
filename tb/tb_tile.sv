// tb_tile.sv — exercises all 4 tile variants in one simulation run.
//
// Drives the same 200 random 64-bit inputs through tile_tlg_hc, tile_tlg_ld,
// tile_handopt_hc, tile_handopt_ld, comparing each output to a Python golden
// model loaded from tb_tile_ys.hex. The two loadable DUTs are programmed
// before vector replay using the same (W, t) values that gen_tile.py baked
// into the hardcoded variants.
//
// Per-vector schedule (2 cycles each, 1 cycle of input flop + 1 cycle of
// output flop = 2-cycle pipeline):
//   cycle T   : x_in=xs[i], x_valid=1   → input flops latch xs[i]
//   cycle T+1 :                          → output flops latch y_comb(xs[i])
//   cycle T+2 : y_out / y_valid valid for xs[i]; check, advance i.

`timescale 1ns/1ps
module tb_tile;
    localparam integer N_VEC     = 200;
    localparam integer N_NEURONS = 16;

    // Clock / reset.
    reg clk;
    initial clk = 0;
    always #5 clk = ~clk;        // 100 MHz
    reg rst_n;

    // Stimulus shared by all DUTs.
    reg [63:0] x_in;
    reg        x_valid;

    // Cfg interface, only the loadable DUTs read it.
    reg        cfg_we;
    reg [5:0]  cfg_addr;
    reg [63:0] cfg_wdata;

    // Outputs from each DUT.
    wire [15:0] y_th, y_tl, y_hh, y_hl;
    wire        v_th, v_tl, v_hh, v_hl;

    tile_tlg_hc      dut_th (
        .clk(clk), .rst_n(rst_n),
        .x_in(x_in), .x_valid(x_valid),
        .y_out(y_th), .y_valid(v_th)
    );
    tile_tlg_ld      dut_tl (
        .clk(clk), .rst_n(rst_n),
        .x_in(x_in), .x_valid(x_valid),
        .y_out(y_tl), .y_valid(v_tl),
        .cfg_we(cfg_we), .cfg_addr(cfg_addr), .cfg_wdata(cfg_wdata)
    );
    tile_handopt_hc  dut_hh (
        .clk(clk), .rst_n(rst_n),
        .x_in(x_in), .x_valid(x_valid),
        .y_out(y_hh), .y_valid(v_hh)
    );
    tile_handopt_ld  dut_hl (
        .clk(clk), .rst_n(rst_n),
        .x_in(x_in), .x_valid(x_valid),
        .y_out(y_hl), .y_valid(v_hl),
        .cfg_we(cfg_we), .cfg_addr(cfg_addr), .cfg_wdata(cfg_wdata)
    );

    // Vector storage.
    reg [63:0] xs [0:N_VEC-1];
    reg [15:0] ys [0:N_VEC-1];

    // Configuration words derived from the manifest. Built into the
    // testbench at compile time via $readmemh from a small hex file
    // emitted alongside the vectors.
    reg [63:0] w_set [0:N_NEURONS-1];
    reg [6:0]  t_set [0:N_NEURONS-1];

    // Mismatch counters.
    integer err_th, err_tl, err_hh, err_hl;
    integer i;

    initial begin
        // --- 1. Setup ---------------------------------------------------
        $readmemh("tb_tile_xs.hex",  xs);
        $readmemh("tb_tile_ys.hex",  ys);
        $readmemh("tb_tile_ws.hex",  w_set);
        $readmemh("tb_tile_ts.hex",  t_set);

        rst_n   = 0;
        x_in    = 64'b0;
        x_valid = 1'b0;
        cfg_we  = 1'b0;
        cfg_addr  = 6'b0;
        cfg_wdata = 64'b0;
        err_th = 0; err_tl = 0; err_hh = 0; err_hl = 0;

        // Hold reset for 4 cycles to flush any X's.
        repeat (4) @(posedge clk);
        rst_n = 1;
        @(posedge clk);

        // --- 2. Program loadable DUTs (32 cfg writes) -------------------
        for (i = 0; i < N_NEURONS; i = i + 1) begin
            @(negedge clk);
            cfg_we    = 1'b1;
            cfg_addr  = i[5:0];          // 0..15 = weight regs
            cfg_wdata = w_set[i];
        end
        for (i = 0; i < N_NEURONS; i = i + 1) begin
            @(negedge clk);
            cfg_we    = 1'b1;
            cfg_addr  = (16 + i);        // 16..31 = threshold regs
            cfg_wdata = {57'b0, t_set[i]};
        end
        @(negedge clk);
        cfg_we = 1'b0;

        // Dead cycle so the last cfg write propagates before any vector
        // attempts to read the regs.
        @(posedge clk);
        @(posedge clk);

        // --- 3. Drive 200 vectors --------------------------------------
        for (i = 0; i < N_VEC; i = i + 1) begin
            // cycle T: assert x_valid=1 with xs[i]
            @(negedge clk);
            x_in    = xs[i];
            x_valid = 1'b1;
            // edge T: input flops latch x_in into x_reg, v_d1 ← 1.
            @(posedge clk);
            // cycle T+1: drop x_valid so we don't re-latch.
            @(negedge clk);
            x_valid = 1'b0;
            // edge T+1: output flops latch y_comb(x_reg) into y_out_r,
            //           v_d2 ← v_d1.
            @(posedge clk);
            #1;  // settle past the edge

            if (v_th !== 1'b1) begin
                $display("[FAIL] tile_tlg_hc      i=%0d y_valid not asserted", i);
                err_th = err_th + 1;
            end else if (y_th !== ys[i]) begin
                $display("[FAIL] tile_tlg_hc      i=%0d x=%h exp=%04h got=%04h",
                         i, xs[i], ys[i], y_th);
                err_th = err_th + 1;
            end
            if (v_tl !== 1'b1) begin
                $display("[FAIL] tile_tlg_ld      i=%0d y_valid not asserted", i);
                err_tl = err_tl + 1;
            end else if (y_tl !== ys[i]) begin
                $display("[FAIL] tile_tlg_ld      i=%0d x=%h exp=%04h got=%04h",
                         i, xs[i], ys[i], y_tl);
                err_tl = err_tl + 1;
            end
            if (v_hh !== 1'b1) begin
                $display("[FAIL] tile_handopt_hc  i=%0d y_valid not asserted", i);
                err_hh = err_hh + 1;
            end else if (y_hh !== ys[i]) begin
                $display("[FAIL] tile_handopt_hc  i=%0d x=%h exp=%04h got=%04h",
                         i, xs[i], ys[i], y_hh);
                err_hh = err_hh + 1;
            end
            if (v_hl !== 1'b1) begin
                $display("[FAIL] tile_handopt_ld  i=%0d y_valid not asserted", i);
                err_hl = err_hl + 1;
            end else if (y_hl !== ys[i]) begin
                $display("[FAIL] tile_handopt_ld  i=%0d x=%h exp=%04h got=%04h",
                         i, xs[i], ys[i], y_hl);
                err_hl = err_hl + 1;
            end
        end

        // --- 4. Report -------------------------------------------------
        $display("---");
        if (err_th == 0) $display("TILE FUNCTIONAL CHECK [tile_tlg_hc]:     PASS (%0d/%0d)", N_VEC, N_VEC);
        else             $display("TILE FUNCTIONAL CHECK [tile_tlg_hc]:     FAIL (%0d errors)", err_th);
        if (err_tl == 0) $display("TILE FUNCTIONAL CHECK [tile_tlg_ld]:     PASS (%0d/%0d)", N_VEC, N_VEC);
        else             $display("TILE FUNCTIONAL CHECK [tile_tlg_ld]:     FAIL (%0d errors)", err_tl);
        if (err_hh == 0) $display("TILE FUNCTIONAL CHECK [tile_handopt_hc]: PASS (%0d/%0d)", N_VEC, N_VEC);
        else             $display("TILE FUNCTIONAL CHECK [tile_handopt_hc]: FAIL (%0d errors)", err_hh);
        if (err_hl == 0) $display("TILE FUNCTIONAL CHECK [tile_handopt_ld]: PASS (%0d/%0d)", N_VEC, N_VEC);
        else             $display("TILE FUNCTIONAL CHECK [tile_handopt_ld]: FAIL (%0d errors)", err_hl);
        if (err_th + err_tl + err_hh + err_hl == 0) $finish;
        else $fatal(1, "%0d total tile mismatches.", err_th + err_tl + err_hh + err_hl);
    end
endmodule
