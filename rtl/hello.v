// hello.v — 4-bit synchronous-reset counter for Phase 0 smoke test.
module hello (
    input  wire       clk,
    input  wire       rst_n,
    output reg  [3:0] count
);
    always @(posedge clk) begin
        if (!rst_n) count <= 4'd0;
        else        count <= count + 4'd1;
    end
endmodule
