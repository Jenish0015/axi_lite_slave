`timescale 1ns / 1ps

module axi_lite_slave #(
    parameter DATA_WIDTH = 32,
    parameter ADDR_WIDTH = 6
)(
    input  wire                  ACLK,
    input  wire                  ARESETn,
    input  wire [ADDR_WIDTH-1:0]  AWADDR,
    input  wire                  AWVALID,
    output reg                   AWREADY,
    input  wire [DATA_WIDTH-1:0]  WDATA,
    input  wire [3:0]            WSTRB,
    input  wire                  WVALID,
    output reg                   WREADY,
    output reg  [1:0]            BRESP,
    output reg                   BVALID,
    input  wire                  BREADY,
    input  wire [ADDR_WIDTH-1:0]  ARADDR,
    input  wire                  ARVALID,
    output reg                   ARREADY,
    output reg [DATA_WIDTH-1:0]   RDATA,
    output reg [1:0]             RRESP,
    output reg                   RVALID,
    input  wire                  RREADY
);

    // TODO: Implement AXI-Lite slave with:
    

endmodule
