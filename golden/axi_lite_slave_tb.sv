`timescale 1ns / 1ps
// Reference self-checking testbench (iverilog/VCS, etc.). Build with the golden DUT:
//   iverilog -g2012 -o sim golden/axi_lite_slave.sv golden/axi_lite_slave_tb.sv
// Cocotb hidden tests use sources/ (student) or golden/axi_lite_slave.sv when present.

module axi_lite_slave_tb;

    // ---------------------------------------------------------------
    // Parameters
    // ---------------------------------------------------------------
    localparam DATA_WIDTH  = 32;
    localparam ADDR_WIDTH  = 6;
    localparam CLK_PERIOD  = 10;

    localparam [5:0] ADDR_CTRL     = 6'h00;
    localparam [5:0] ADDR_DATA_IN  = 6'h04;
    localparam [5:0] ADDR_DATA_OUT = 6'h08;
    localparam [5:0] ADDR_STATUS   = 6'h0C;

    localparam integer PIPE_CYCLES = 32;

    // ---------------------------------------------------------------
    // DUT interface signals
    // ---------------------------------------------------------------
    logic                   ACLK;
    logic                   ARESETn;

    logic [ADDR_WIDTH-1:0]  AWADDR;
    logic                   AWVALID;
    wire                    AWREADY;

    logic [DATA_WIDTH-1:0]  WDATA;
    logic [3:0]             WSTRB;
    logic                   WVALID;
    wire                    WREADY;

    wire  [1:0]             BRESP;
    wire                    BVALID;
    logic                   BREADY;

    logic [ADDR_WIDTH-1:0]  ARADDR;
    logic                   ARVALID;
    wire                    ARREADY;

    wire  [DATA_WIDTH-1:0]  RDATA;
    wire  [1:0]             RRESP;
    wire                    RVALID;
    logic                   RREADY;

    // ---------------------------------------------------------------
    // Internal testbench state
    // ---------------------------------------------------------------
    logic [DATA_WIDTH-1:0]  read_data;
    logic [1:0]             read_resp;
    logic [1:0]             write_resp;
    integer                 test_num;

    // ---------------------------------------------------------------
    // DUT instantiation
    // ---------------------------------------------------------------
    axi_lite_slave #(
        .DATA_WIDTH (DATA_WIDTH),
        .ADDR_WIDTH (ADDR_WIDTH)
    ) dut (
        .ACLK    (ACLK),
        .ARESETn (ARESETn),
        .AWADDR  (AWADDR),
        .AWVALID (AWVALID),
        .AWREADY (AWREADY),
        .WDATA   (WDATA),
        .WSTRB   (WSTRB),
        .WVALID  (WVALID),
        .WREADY  (WREADY),
        .BRESP   (BRESP),
        .BVALID  (BVALID),
        .BREADY  (BREADY),
        .ARADDR  (ARADDR),
        .ARVALID (ARVALID),
        .ARREADY (ARREADY),
        .RDATA   (RDATA),
        .RRESP   (RRESP),
        .RVALID  (RVALID),
        .RREADY  (RREADY)
    );

    // ---------------------------------------------------------------
    // Clock generation
    // ---------------------------------------------------------------
    initial ACLK = 0;
    always #(CLK_PERIOD / 2) ACLK = ~ACLK;

    // ---------------------------------------------------------------
    // Tasks
    // ---------------------------------------------------------------

    // Drive all bus signals to idle / de-asserted state
    task axi_idle;
        AWADDR  = '0;
        AWVALID = 1'b0;
        WDATA   = '0;
        WSTRB   = 4'hF;
        WVALID  = 1'b0;
        BREADY  = 1'b0;
        ARADDR  = '0;
        ARVALID = 1'b0;
        RREADY  = 1'b0;
    endtask

    // Single AXI-Lite write; result captured in write_resp
    task axi_write (
        input logic [ADDR_WIDTH-1:0] addr,
        input logic [DATA_WIDTH-1:0] data,
        input logic [3:0]            strb
    );
        // --- Write address channel ---
        @(posedge ACLK);
        AWADDR  = addr;
        AWVALID = 1'b1;

        repeat (50) begin
            @(posedge ACLK);
            if (AWREADY) begin
                AWVALID = 1'b0;
                break;
            end
        end
        AWVALID = 1'b0;
        @(posedge ACLK);

        // --- Write data channel ---
        WDATA  = data;
        WSTRB  = strb;
        WVALID = 1'b1;

        repeat (50) begin
            @(posedge ACLK);
            if (WREADY) begin
                WVALID = 1'b0;
                break;
            end
        end
        WVALID = 1'b0;

        // --- Write response channel ---
        BREADY = 1'b1;
        repeat (50) begin
            @(posedge ACLK);
            if (BVALID) begin
                write_resp = BRESP;
                break;
            end
        end
        @(posedge ACLK);
        BREADY = 1'b0;
    endtask

    // Single AXI-Lite read; result captured in read_data / read_resp
    task axi_read (
        input  logic [ADDR_WIDTH-1:0] addr,
        output logic [DATA_WIDTH-1:0] data,
        output logic [1:0]            resp
    );
        // --- Read address channel ---
        @(posedge ACLK);
        ARADDR  = addr;
        ARVALID = 1'b1;
        RREADY  = 1'b1;

        repeat (50) begin
            @(posedge ACLK);
            if (ARREADY) begin
                ARVALID = 1'b0;
                break;
            end
        end
        ARVALID = 1'b0;

        // --- Read data channel ---
        repeat (50) begin
            @(posedge ACLK);
            if (RVALID) begin
                data = RDATA;
                resp = RRESP;
                break;
            end
        end
        @(posedge ACLK);
        RREADY = 1'b0;
    endtask

    // Poll STATUS register until bit 0 set or timeout
    task wait_done (
        input integer timeout_cycles
    );
        logic [DATA_WIDTH-1:0] st;
        logic [1:0]            rr;
        integer                i;
        for (i = 0; i < timeout_cycles; i = i + 1) begin
            axi_read(ADDR_STATUS, st, rr);
            if (st[0]) begin
                $display("[%0t] Pipeline done after %0d polls", $time, i + 1);
                return;
            end
        end
        $display("[%0t] WARNING: wait_done timed out after %0d cycles", $time, timeout_cycles);
    endtask

    // ---------------------------------------------------------------
    // Golden reference function
    // ---------------------------------------------------------------
    function automatic logic [DATA_WIDTH-1:0] expected_result (
        input logic [DATA_WIDTH-1:0] val
    );
        logic [DATA_WIDTH-1:0] xored;
        logic [DATA_WIDTH:0]   total;
        xored = val ^ 32'hA5A5A5A5;
        total = ({1'b0, xored} + {1'b0, val});
        return total[DATA_WIDTH-1:0] >> 2;
    endfunction

    // ---------------------------------------------------------------
    // Stimulus
    // ---------------------------------------------------------------
    initial begin
        $dumpfile("axi_lite_slave_tb.vcd");
        $dumpvars(0, axi_lite_slave_tb);

        // ------------------------------------------------------------------
        // Reset
        // ------------------------------------------------------------------
        axi_idle();
        ARESETn = 1'b0;
        repeat (5) @(posedge ACLK);
        ARESETn = 1'b1;
        repeat (3) @(posedge ACLK);

        // ==================================================================
        // Test 1 – Masked CTRL write must NOT trigger pipeline
        // ==================================================================
        test_num = 1;
        $display("[%0t] TEST %0d: Masked CTRL write", $time, test_num);

        axi_write(ADDR_DATA_IN, 32'h00000015, 4'hF);
        axi_write(ADDR_CTRL,    32'h00000001, 4'h0); // strb=0 → no effect

        repeat (12) @(posedge ACLK);

        axi_read(ADDR_STATUS, read_data, read_resp);
        if (read_data !== 32'h0)
            $display("FAIL T1: STATUS should be 0, got %0h", read_data);

        axi_read(ADDR_DATA_OUT, read_data, read_resp);
        if (read_data !== 32'h0)
            $display("FAIL T1: DATA_OUT should be 0 before trigger, got %0h", read_data);

        $display("[%0t] TEST %0d PASS", $time, test_num);

        // ==================================================================
        // Test 2 – Basic trigger and correct result
        // ==================================================================
        test_num = 2;
        $display("[%0t] TEST %0d: Basic pipeline run", $time, test_num);

        axi_write(ADDR_DATA_IN, 32'h000000FF, 4'hF);
        axi_write(ADDR_CTRL,    32'h00000001, 4'h1); // trigger

        wait_done(PIPE_CYCLES + 20);

        axi_read(ADDR_DATA_OUT, read_data, read_resp);
        if (read_data !== expected_result(32'h000000FF))
            $display("FAIL T2: DATA_OUT = %0h, expected %0h",
                     read_data, expected_result(32'h000000FF));
        else
            $display("[%0t] TEST %0d PASS (DATA_OUT = %0h)", $time, test_num, read_data);

        axi_write(ADDR_CTRL, 32'h00000000, 4'h1); // clear

        // ==================================================================
        // Test 3 – Retrigger mid-pipeline uses latest operand
        // ==================================================================
        test_num = 3;
        $display("[%0t] TEST %0d: Retrigger with new operand", $time, test_num);

        axi_write(ADDR_DATA_IN, 32'h00000015, 4'hF);
        axi_write(ADDR_CTRL,    32'h00000001, 4'h1);        // first trigger

        repeat (PIPE_CYCLES / 4) @(posedge ACLK);

        axi_write(ADDR_CTRL,    32'h00000000, 4'h1);        // cancel
        axi_write(ADDR_DATA_IN, 32'h0000002A, 4'hF);        // new operand
        axi_write(ADDR_CTRL,    32'h00000001, 4'h1);        // retrigger

        // DATA_OUT must still be 0 mid-pipeline
        repeat (PIPE_CYCLES / 3) @(posedge ACLK);
        axi_read(ADDR_DATA_OUT, read_data, read_resp);
        if (read_data !== 32'h0)
            $display("FAIL T3: DATA_OUT changed too early, got %0h", read_data);

        wait_done(PIPE_CYCLES + 20);

        axi_read(ADDR_DATA_OUT, read_data, read_resp);
        if (read_data !== expected_result(32'h0000002A))
            $display("FAIL T3: DATA_OUT = %0h, expected %0h",
                     read_data, expected_result(32'h0000002A));
        else
            $display("[%0t] TEST %0d PASS (DATA_OUT = %0h)", $time, test_num, read_data);

        axi_write(ADDR_CTRL, 32'h00000000, 4'h1);

        // ==================================================================
        // Test 4 – SLVERR on unmapped address (write)
        // ==================================================================
        test_num = 4;
        $display("[%0t] TEST %0d: SLVERR on unmapped write address", $time, test_num);

        axi_write(6'h3C, 32'hDEADBEEF, 4'hF);
        if (write_resp !== 2'b10)
            $display("FAIL T4: BRESP = %0b, expected SLVERR (10)", write_resp);
        else
            $display("[%0t] TEST %0d PASS", $time, test_num);

        // ==================================================================
        // Test 5 – SLVERR on unmapped address (read)
        // ==================================================================
        test_num = 5;
        $display("[%0t] TEST %0d: SLVERR on unmapped read address", $time, test_num);

        axi_read(6'h3C, read_data, read_resp);
        if (read_resp !== 2'b10)
            $display("FAIL T5: RRESP = %0b, expected SLVERR (10)", read_resp);
        else
            $display("[%0t] TEST %0d PASS", $time, test_num);

        // ==================================================================
        // Test 6 – Read back CTRL and DATA_IN registers
        // ==================================================================
        test_num = 6;
        $display("[%0t] TEST %0d: Register read-back", $time, test_num);

        axi_write(ADDR_DATA_IN, 32'hCAFEBABE, 4'hF);
        axi_read (ADDR_DATA_IN, read_data, read_resp);
        if (read_data !== 32'hCAFEBABE)
            $display("FAIL T6: DATA_IN read-back = %0h, expected CAFEBABE", read_data);
        else
            $display("[%0t] TEST %0d PASS", $time, test_num);

        // ------------------------------------------------------------------
        // Done
        // ------------------------------------------------------------------
        repeat (10) @(posedge ACLK);
        $display("[%0t] All tests complete.", $time);
        $finish;
    end

endmodule