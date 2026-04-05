`timescale 1ns / 1ps

// ----------------------------------------------------------------------------
// Agent hints (read before implementing)
// - Hidden tests / cocotb compile `sources/axi_lite_slave_dut.sv` when present;
//   otherwise they compile this file. Prefer a flat `module axi_lite_slave`
//   with NO parameters in `axi_lite_slave_dut.sv` (match ports below, 32-bit buses).
// - Register decode uses addr[5:0]: 0x00 CTRL, 0x04 DATA_IN, 0x08 DATA_OUT, 0x0C STATUS.
// - Fixed-latency datapath (~32 enabled cycles from start to done); while busy,
//   reads of DATA_OUT must return 0. Do not advance the pipeline counter when
//   stalled: (RVALID & ~RREADY) | (BVALID & ~BREADY).
// - CTRL byte0: WSTRB[0]=0 must NOT start/clear the pipeline (masked write).
//   WSTRB[0]=1 and WDATA[0]=1 starts from current DATA_IN; =0 clears.
// - DATA_IN: merge writes per WSTRB byte; AXI AW and W channels are independent.
// ----------------------------------------------------------------------------

// Baseline branch: parameterized ports, empty body (agent implements all logic).
module axi_lite_slave #(
    parameter int unsigned DATA_WIDTH = 32,
    parameter int unsigned ADDR_WIDTH = 32
) (
    input  wire                      ACLK,
    input  wire                      ARESETn,

    input  wire [ADDR_WIDTH-1:0]     AWADDR,
    input  wire                      AWVALID,
    output reg                       AWREADY,

    input  wire [DATA_WIDTH-1:0]    WDATA,
    input  wire [3:0]                WSTRB,
    input  wire                      WVALID,
    output reg                       WREADY,

    output reg [1:0]                 BRESP,
    output reg                       BVALID,
    input  wire                      BREADY,

    input  wire [ADDR_WIDTH-1:0]     ARADDR,
    input  wire                      ARVALID,
    output reg                       ARREADY,

    output reg [DATA_WIDTH-1:0]     RDATA,
    output reg [1:0]                 RRESP,
    output reg                       RVALID,
    input  wire                      RREADY
);

    // --- Empty shell: add your RTL below (see header comments). No behavior required for baseline compile. ---
    // Suggested order: (1) AXI write FSM (AW/W then B), (2) AXI read FSM (AR then R),
    // (3) register file + WSTRB merges, (4) fixed-cycle pipeline with pipe_stall holdoff.

endmodule
