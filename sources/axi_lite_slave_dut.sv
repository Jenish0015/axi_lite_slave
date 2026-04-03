`timescale 1ns / 1ps

// Baseline: flat `axi_lite_slave` (no parameters) for cocotb. Implement the full AXI-Lite slave here.
module axi_lite_slave (
    input  wire         ACLK,
    input  wire         ARESETn,

    input  wire [31:0]  AWADDR,
    input  wire         AWVALID,
    output reg          AWREADY,

    input  wire [31:0]  WDATA,
    input  wire [3:0]   WSTRB,
    input  wire         WVALID,
    output reg          WREADY,

    output reg [1:0]    BRESP,
    output reg          BVALID,
    input  wire         BREADY,

    input  wire [31:0]  ARADDR,
    input  wire         ARVALID,
    output reg          ARREADY,

    output reg [31:0]   RDATA,
    output reg [1:0]    RRESP,
    output reg          RVALID,
    input  wire         RREADY
);

    // Stub — hidden tests expect failure until implementation is added.
    always @(posedge ACLK or negedge ARESETn) begin
        if (!ARESETn) begin
            AWREADY <= 1'b0;
            WREADY  <= 1'b0;
            BVALID  <= 1'b0;
            BRESP   <= 2'b00;
            ARREADY <= 1'b0;
            RVALID  <= 1'b0;
            RDATA   <= 32'h0;
            RRESP   <= 2'b00;
        end else begin
            AWREADY <= 1'b0;
            WREADY  <= 1'b0;
            BVALID  <= 1'b0;
            ARREADY <= 1'b0;
            RVALID  <= 1'b0;
            RDATA   <= 32'h0;
            RRESP   <= 2'b00;
            BRESP   <= 2'b00;
        end
    end

endmodule
