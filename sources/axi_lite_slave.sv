`timescale 1us/1us
module axi_lite_slave (
    // Global signals
    input  logic        ACLK,
    input  logic        ARESETn,

    // Write address channel
    input  logic [31:0] AWADDR,
    input  logic        AWVALID,
    output logic        AWREADY,

    // Write data channel
    input  logic [31:0] WDATA,
    input  logic [3:0]  WSTRB,
    input  logic        WVALID,
    output logic        WREADY,

    // Write response channel
    output logic [1:0]  BRESP,
    output logic        BVALID,
    input  logic        BREADY,

    // Read address channel
    input  logic [31:0] ARADDR,
    input  logic        ARVALID,
    output logic        ARREADY,

    // Read data channel
    output logic [31:0] RDATA,
    output logic [1:0]  RRESP,
    output logic        RVALID,
    input  logic        RREADY
);
    // Internal logic

endmodule