// tb_neuron_s0.v — drives the same 100 random 64-bit inputs through all three
// implementations of neuron seed=0 and compares each output against the Python
// golden model (loaded from tb_ys_s0.hex).
`timescale 1ns/1ps
module tb_neuron_s0;
    localparam integer N = 100;

    reg  [63:0]              x;
    reg  [63:0]              xs [0:N-1];
    reg  [0:0]               ys [0:N-1];

    wire                     y_naive;
    wire                     y_handopt;
    wire                     y_tlg;

    neuron_naive_s0   u_n (.x(x), .y(y_naive));
    neuron_handopt_s0 u_h (.x(x), .y(y_handopt));
    neuron_tlg_s0     u_t (.x(x), .y(y_tlg));

    integer i, errors_n, errors_h, errors_t;
    reg     expected;

    initial begin
        errors_n = 0; errors_h = 0; errors_t = 0;
        $readmemh("tb_xs_s0.hex", xs);
        $readmemh("tb_ys_s0.hex", ys);
        for (i = 0; i < N; i = i + 1) begin
            x = xs[i];
            #1;  // settle combinational logic
            expected = ys[i][0];
            if (y_naive   !== expected) begin
                $display("[FAIL] naive   i=%0d x=%h exp=%b got=%b", i, x, expected, y_naive);
                errors_n = errors_n + 1;
            end
            if (y_handopt !== expected) begin
                $display("[FAIL] handopt i=%0d x=%h exp=%b got=%b", i, x, expected, y_handopt);
                errors_h = errors_h + 1;
            end
            if (y_tlg     !== expected) begin
                $display("[FAIL] tlg     i=%0d x=%h exp=%b got=%b", i, x, expected, y_tlg);
                errors_t = errors_t + 1;
            end
        end
        $display("---");
        $display("naive   : %0d / %0d match", N - errors_n, N);
        $display("handopt : %0d / %0d match", N - errors_h, N);
        $display("tlg     : %0d / %0d match", N - errors_t, N);
        if (errors_n + errors_h + errors_t == 0)
            $display("PASS: all 3 variants agree with the golden model on %0d vectors.", N);
        else
            $display("FAIL: %0d total mismatches.", errors_n + errors_h + errors_t);
        $finish;
    end
endmodule
