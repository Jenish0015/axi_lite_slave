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

    localparam W_IDLE = 2'd0, W_DATA = 2'd1, W_RESP = 2'd2;
    reg [1:0] wstate;
    reg [ADDR_WIDTH-1:0] waddr;

    // AXI Write FSM
    always @(posedge ACLK) begin
        if (!ARESETn) begin
            wstate <= W_IDLE; AWREADY <= 1'b0; WREADY <= 1'b0;
            BVALID <= 1'b0; BRESP <= 2'b00;
            ctrl_reg <= 32'd0; data_in_reg <= 32'd0;
        end else begin
            case (wstate)
            W_IDLE: begin
                AWREADY <= 1'b1; WREADY <= 1'b0; BVALID <= 1'b0;
                if (AWVALID) begin
                    waddr <= AWADDR; AWREADY <= 1'b0;
                    WREADY <= 1'b1; wstate <= W_DATA;
                end
            end
            W_DATA: begin
                if (WVALID) begin
                    WREADY <= 1'b0;
                    case (waddr)
                        6'h00: ctrl_reg    <= WDATA;
                        6'h04: data_in_reg <= WDATA;
                        default: ;
                    endcase
                    BVALID <= 1'b1; BRESP <= 2'b00; wstate <= W_RESP;
                end
            end
            W_RESP: begin
                if (BREADY) begin BVALID <= 1'b0; wstate <= W_IDLE; end
            end
            endcase
        end
    end

    // AXI Read FSM
    always @(posedge ACLK) begin
        if (!ARESETn) begin
            ARREADY <= 1'b0; RVALID <= 1'b0; RRESP <= 2'b00; RDATA <= 32'd0;
        end else begin
            if (ARVALID && !RVALID) begin
                ARREADY <= 1'b1;
                case (ARADDR)
                    6'h00: RDATA <= ctrl_reg;
                    6'h04: RDATA <= data_in_reg;
                    6'h08: RDATA <= data_out_reg;
                    6'h0C: RDATA <= status_reg;
                    default: RDATA <= 32'd0;
                endcase
                RRESP <= 2'b00; RVALID <= 1'b1;
            end else if (RREADY) begin
                RVALID <= 1'b0; ARREADY <= 1'b0;
            end
        end
    end

    // Datapath - combinational compute, registered output
    always @(posedge ACLK) begin
        if (!ARESETn) begin
            data_out_reg <= 32'd0;
            status_reg   <= 32'd0;
        end else begin
            if (ctrl_reg[0]) begin
                data_out_reg  <= (data_in_reg + 32'd10) << 1;
                status_reg[0] <= 1'b1;
            end else begin
                status_reg[0] <= 1'b0;
            end
        end
    end

endmodule
