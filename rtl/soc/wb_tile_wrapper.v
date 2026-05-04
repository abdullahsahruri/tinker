// =============================================================================
// wb_tile_wrapper.v — Wishbone B4 classic slave wrapping the Phase-2C tile_tlg_ld.
//
// Spec: docs/PHASE3_ARCHITECTURE.md §4.   Implementation notes: docs/PHASE3B_NOTES.md.
//
// Register layout (byte offsets within the 512 B slave window):
//   0x000..0x07F : W[i].LO at 0x000+8*i, W[i].HI at 0x004+8*i (i=0..15).
//                  LO writes update a 32-b shadow only; HI writes drive one
//                  cycle of cfg_we with cfg_addr={2'b00,i}, cfg_wdata={HI,LO}.
//   0x080..0x0BC : T[i] at 0x080+4*i. Each write drives one cycle of cfg_we
//                  with cfg_addr={2'b01,i}, cfg_wdata[6:0]=data[6:0].
//   0x0C0..0x0FF : reserved (writes ignored, reads return 0).
//   0x100        : XIN.LO  — 32-b shadow.
//   0x104        : XIN.HI  — write commits {HI,LO} and pulses x_valid 1 cycle.
//   0x108        : STATUS  [RO] {30'b0, DONE, BUSY}.
//   0x10C        : YOUT    [RO] {15'b0, y_valid_sticky, y_out[15:0]}.
//   0x110        : CTRL    bit0=CLR_DONE (W1C), bit1=SOFT_RESET (W1).
//   0x114..0x1FF : reserved (writes ignored, reads return 0).
//
// While BUSY=1, all writes that would mutate tile-visible state (W[i].*, T[i],
// XIN.LO, XIN.HI) are silently dropped: ack returns normally but the shadow
// is not updated and no cfg_we / x_valid pulse is generated. CTRL writes are
// always honored — that is how firmware aborts a stuck inference.
//
// Wishbone protocol: ack_q registers a 1-cycle pulse on the first cycle of
// (cyc&stb). Reads are single-cycle, combinational mux from wb_adr_i to
// wb_dat_o; data is valid in the cycle ack_o pulses.
//
// Read-back of writable registers: this implementation keeps full shadows
// (LO+HI for weights, 7-b for thresholds, LO+HI for XIN) so that reads of
// the most recent written value succeed. This is a deliberate deviation
// from PHASE3_ARCHITECTURE.md §4.1/§4.2 ("the wrapper does not mirror
// storage … reads of write-only offsets return 0") — see PHASE3B_NOTES.md
// for the rationale and area cost (~1.3 K flops vs spec-strict ~0.6 K).
// =============================================================================
`default_nettype none

module wb_tile_wrapper (
    input  wire        clk,
    input  wire        rst_n,

    input  wire        wb_cyc_i,
    input  wire        wb_stb_i,
    input  wire        wb_we_i,
    input  wire [3:0]  wb_sel_i,
    input  wire [31:0] wb_adr_i,
    input  wire [31:0] wb_dat_i,
    output wire [31:0] wb_dat_o,
    output wire        wb_ack_o,
    output wire        wb_err_o
);

    integer i;

    // -------------------------------------------------------------------------
    // 1. WB ack — registered, 1-cycle pulse on the first stb cycle.
    // -------------------------------------------------------------------------
    reg ack_q;
    always @(posedge clk) begin
        if (!rst_n)                              ack_q <= 1'b0;
        else if (wb_cyc_i & wb_stb_i & ~ack_q)   ack_q <= 1'b1;
        else                                     ack_q <= 1'b0;
    end
    assign wb_ack_o = ack_q;
    assign wb_err_o = 1'b0;     // reserved offsets ack OK; no err path needed

    // -------------------------------------------------------------------------
    // 2. Address decode within the 512 B window. Only adr[8:2] is consumed
    //    (word-aligned); the interconnect strips upper bits before passing
    //    the access through.
    // -------------------------------------------------------------------------
    wire [3:0] widx = wb_adr_i[6:3];   // weight neuron index, 0x000..0x07F
    wire [3:0] tidx = wb_adr_i[5:2];   // threshold neuron index, 0x080..0x0BC

    wire is_w_region = (wb_adr_i[8:7] == 2'b00);
    wire is_w_lo     = is_w_region & ~wb_adr_i[2];
    wire is_w_hi     = is_w_region &  wb_adr_i[2];
    wire is_t        = (wb_adr_i[8:7] == 2'b01) & (wb_adr_i[6] == 1'b0);

    wire is_ctrl_reg = (wb_adr_i[8:7] == 2'b10);
    wire is_xin_lo   = is_ctrl_reg & (wb_adr_i[6:2] == 5'd0);
    wire is_xin_hi   = is_ctrl_reg & (wb_adr_i[6:2] == 5'd1);
    wire is_status   = is_ctrl_reg & (wb_adr_i[6:2] == 5'd2);
    wire is_yout     = is_ctrl_reg & (wb_adr_i[6:2] == 5'd3);
    wire is_ctrl     = is_ctrl_reg & (wb_adr_i[6:2] == 5'd4);

    wire bus_xact = wb_cyc_i & wb_stb_i & ~ack_q;     // first cycle of stb
    wire bus_wr   = bus_xact &  wb_we_i;

    // -------------------------------------------------------------------------
    // 3. Shadow / state registers.
    //    - w_lo, xin_lo are required (assemble 64-b cfg/x_in over a 32-b bus).
    //    - w_hi, xin_hi, t_shadow exist purely for register read-back.
    // -------------------------------------------------------------------------
    reg [31:0] w_lo_shadow [0:15];
    reg [31:0] w_hi_shadow [0:15];
    reg [6:0]  t_shadow    [0:15];
    reg [31:0] xin_lo_shadow;
    reg [31:0] xin_hi_shadow;

    reg        busy;
    reg        done;
    reg [15:0] yout;
    reg        yvalid_sticky;

    // -------------------------------------------------------------------------
    // 4. Tile-facing combinational drives. cfg_we and x_valid pulse for one
    //    cycle on the same edge that the corresponding bus_wr is acked. All
    //    gated by ~busy per spec §4.6.
    // -------------------------------------------------------------------------
    wire        tile_x_valid;
    wire [63:0] tile_x_in;
    wire        tile_cfg_we;
    wire [5:0]  tile_cfg_addr;
    wire [63:0] tile_cfg_wdata;
    wire [15:0] tile_y_out;
    wire        tile_y_valid;

    wire commit_w_hi = bus_wr & is_w_hi   & ~busy;
    wire commit_t    = bus_wr & is_t      & ~busy;
    wire commit_xin  = bus_wr & is_xin_hi & ~busy;

    assign tile_cfg_we    = commit_w_hi | commit_t;
    assign tile_cfg_addr  = commit_w_hi ? {2'b00, widx} :
                            commit_t    ? {2'b01, tidx} : 6'b0;
    assign tile_cfg_wdata = commit_w_hi ? {wb_dat_i, w_lo_shadow[widx]} :
                            commit_t    ? {57'b0, wb_dat_i[6:0]}        : 64'b0;
    assign tile_x_valid   = commit_xin;
    assign tile_x_in      = {wb_dat_i, xin_lo_shadow};

    // -------------------------------------------------------------------------
    // 5. Sequential state — shadows, busy/done capture, soft reset, clr-done.
    // -------------------------------------------------------------------------
    wire ctrl_clr_done   = bus_wr & is_ctrl & wb_dat_i[0];
    wire ctrl_soft_reset = bus_wr & is_ctrl & wb_dat_i[1];

    always @(posedge clk) begin
        if (!rst_n) begin
            for (i = 0; i < 16; i = i + 1) begin
                w_lo_shadow[i] <= 32'b0;
                w_hi_shadow[i] <= 32'b0;
                t_shadow[i]    <= 7'b0;
            end
            xin_lo_shadow <= 32'b0;
            xin_hi_shadow <= 32'b0;
            busy          <= 1'b0;
            done          <= 1'b0;
            yout          <= 16'b0;
            yvalid_sticky <= 1'b0;
        end else begin
            // 5a. Shadow updates (gated by ~busy except CTRL).
            if (bus_wr & is_w_lo   & ~busy) w_lo_shadow[widx] <= wb_dat_i;
            if (commit_w_hi)                w_hi_shadow[widx] <= wb_dat_i;
            if (commit_t)                   t_shadow[tidx]    <= wb_dat_i[6:0];
            if (bus_wr & is_xin_lo & ~busy) xin_lo_shadow     <= wb_dat_i;
            if (commit_xin)                 xin_hi_shadow     <= wb_dat_i;

            // 5b. Inference busy/done capture. tile_y_valid pulses two cycles
            //     after x_valid; busy clears in the same edge that fires it.
            if (commit_xin)               busy <= 1'b1;
            else if (busy & tile_y_valid) busy <= 1'b0;

            if (busy & tile_y_valid) begin
                done          <= 1'b1;
                yout          <= tile_y_out;
                yvalid_sticky <= 1'b1;
            end

            // 5c. CTRL strobes — always honored (firmware uses SOFT_RESET to
            //     abort a stuck inference; CLR_DONE clears sticky DONE/yvs).
            if (ctrl_clr_done) begin
                done          <= 1'b0;
                yvalid_sticky <= 1'b0;
            end
            if (ctrl_soft_reset) begin
                for (i = 0; i < 16; i = i + 1) begin
                    w_lo_shadow[i] <= 32'b0;
                    w_hi_shadow[i] <= 32'b0;
                    t_shadow[i]    <= 7'b0;
                end
                xin_lo_shadow <= 32'b0;
                xin_hi_shadow <= 32'b0;
                busy          <= 1'b0;
                done          <= 1'b0;
                yout          <= 16'b0;
                yvalid_sticky <= 1'b0;
            end
        end
    end

    // -------------------------------------------------------------------------
    // 6. Read-data mux — combinational from wb_adr_i; valid when ack pulses.
    //    case (1'b1) selects the first matching `is_*` (mutually exclusive
    //    by construction of the decoder above).
    // -------------------------------------------------------------------------
    reg [31:0] rd_data;
    always @* begin
        case (1'b1)
            is_w_lo:   rd_data = w_lo_shadow[widx];
            is_w_hi:   rd_data = w_hi_shadow[widx];
            is_t:      rd_data = {25'b0, t_shadow[tidx]};
            is_xin_lo: rd_data = xin_lo_shadow;
            is_xin_hi: rd_data = xin_hi_shadow;
            is_status: rd_data = {30'b0, done, busy};
            is_yout:   rd_data = {15'b0, yvalid_sticky, yout};
            default:   rd_data = 32'b0;     // CTRL read = 0; reserved = 0
        endcase
    end
    assign wb_dat_o = rd_data;

    // -------------------------------------------------------------------------
    // 7. Tile instance. Unchanged from the 3A skeleton.
    // -------------------------------------------------------------------------
    tile_tlg_ld u_tile (
        .clk        (clk),
        .rst_n      (rst_n),
        .x_in       (tile_x_in),
        .x_valid    (tile_x_valid),
        .y_out      (tile_y_out),
        .y_valid    (tile_y_valid),
        .cfg_we     (tile_cfg_we),
        .cfg_addr   (tile_cfg_addr),
        .cfg_wdata  (tile_cfg_wdata)
    );

    // wb_sel_i is unused: the tile cfg/control regs are 32-b word writes only;
    // sub-word stores into this window are not a supported access pattern.
    wire _unused_ok = &{1'b0, wb_sel_i, 1'b0};

endmodule

`default_nettype wire
