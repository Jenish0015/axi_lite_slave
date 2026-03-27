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

    reg [31:0] ctrl_reg;
    reg [31:0] data_in_reg;
    reg [31:0] data_out_reg;
    reg [31:0] status_reg;

    localparam W_IDLE = 2'd0,
               W_DATA = 2'd1,
               W_RESP = 2'd2;

    reg [1:0] wstate;
    reg [ADDR_WIDTH-1:0] waddr;

    always @(posedge ACLK or negedge ARESETn) begin
        if (!ARESETn) begin
            wstate      <= W_IDLE;
            AWREADY     <= 1'b0;
            WREADY      <= 1'b0;
            BVALID      <= 1'b0;
            BRESP       <= 2'b00;
            waddr       <= 0;
            ctrl_reg    <= 32'b0;
            data_in_reg <= 32'b0;
        end else begin
            case (wstate)
                W_IDLE: begin
                    AWREADY <= 1'b1;
                    WREADY  <= 1'b0;
                    BVALID  <= 1'b0;
                    if (AWVALID && AWREADY) begin
                        waddr   <= AWADDR;
                        AWREADY <= 1'b0;
                        WREADY  <= 1'b1;
                        wstate  <= W_DATA;
                    end
                end
                W_DATA: begin
                    if (WVALID && WREADY) begin
                        WREADY <= 1'b0;
                        case (waddr[3:0])
                            4'h0: begin
                                if (WSTRB[0]) ctrl_reg[7:0]   <= WDATA[7:0];
                                if (WSTRB[1]) ctrl_reg[15:8]  <= WDATA[15:8];
                                if (WSTRB[2]) ctrl_reg[23:16] <= WDATA[23:16];
                                if (WSTRB[3]) ctrl_reg[31:24] <= WDATA[31:24];
                            end
                            4'h4: begin
                                if (WSTRB[0]) data_in_reg[7:0]   <= WDATA[7:0];
                                if (WSTRB[1]) data_in_reg[15:8]  <= WDATA[15:8];
                                if (WSTRB[2]) data_in_reg[23:16] <= WDATA[23:16];
                                if (WSTRB[3]) data_in_reg[31:24] <= WDATA[31:24];
                            end
                            default: ;
                        endcase
                        BRESP  <= 2'b00;
                        BVALID <= 1'b1;
                        wstate <= W_RESP;
                    end
                end
                W_RESP: begin
                    if (BVALID && BREADY) begin
                        BVALID  <= 1'b0;
                        AWREADY <= 1'b1;
                        wstate  <= W_IDLE;
                    end
                end
                default: wstate <= W_IDLE;
            endcase
        end
    end

    always @(posedge ACLK or negedge ARESETn) begin
        if (!ARESETn) begin
            ARREADY <= 1'b0;
            RVALID  <= 1'b0;
            RDATA   <= 32'b0;
            RRESP   <= 2'b00;
        end else begin
            if (!RVALID) begin
                ARREADY <= 1'b1;
                if (ARVALID && ARREADY) begin
                    ARREADY <= 1'b0;
                    RRESP   <= 2'b00;
                    case (ARADDR[3:0])
                        4'h0: RDATA <= ctrl_reg;
                        4'h4: RDATA <= data_in_reg;
                        4'h8: RDATA <= data_out_reg;
                        4'hC: RDATA <= status_reg;
                        default: begin
                            RDATA <= 32'b0;
                            RRESP <= 2'b10;
                        end
                    endcase
                    RVALID <= 1'b1;
                end
            end else if (RREADY && RVALID) begin
                RVALID  <= 1'b0;
                ARREADY <= 1'b1;
            end
        end
    end

    // Intentionally omit datapath: DATA_OUT / STATUS never update from CTRL/DATA_IN.

endmodule