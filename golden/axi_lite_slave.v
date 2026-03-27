`timescale 1ns/1ps

module axi_lite_slave #(
    parameter DATA_WIDTH = 32,
    parameter ADDR_WIDTH = 6
)(
    input  wire                   ACLK,
    input  wire                   ARESETn,
    input  wire [ADDR_WIDTH-1:0]  AWADDR,
    input  wire                   AWVALID,
    output reg                    AWREADY,
    input  wire [DATA_WIDTH-1:0]  WDATA,
    input  wire [3:0]             WSTRB,
    input  wire                   WVALID,
    output reg                    WREADY,
    output reg [1:0]              BRESP,
    output reg                    BVALID,
    input  wire                   BREADY,
    input  wire [ADDR_WIDTH-1:0]  ARADDR,
    input  wire                   ARVALID,
    output reg                    ARREADY,
    output reg [DATA_WIDTH-1:0]   RDATA,
    output reg [1:0]              RRESP,
    output reg                    RVALID,
    input  wire                   RREADY
);

    localparam [ADDR_WIDTH-1:0] ADDR_CTRL     = 6'h00;
    localparam [ADDR_WIDTH-1:0] ADDR_DATA_IN  = 6'h04;
    localparam [ADDR_WIDTH-1:0] ADDR_DATA_OUT = 6'h08;
    localparam [ADDR_WIDTH-1:0] ADDR_STATUS   = 6'h0C;

    localparam [1:0] RESP_OKAY   = 2'b00;
    localparam [1:0] RESP_SLVERR = 2'b10;

    localparam [1:0] W_IDLE = 2'd0, W_DATA = 2'd1, W_RESP = 2'd2;
    localparam [0:0] R_IDLE = 1'b0, R_WAIT = 1'b1;

    reg [31:0] reg_ctrl;
    reg [31:0] reg_data_in;
    reg [ADDR_WIDTH-1:0] latched_awaddr;
    reg [1:0] wstate;
    reg       rstate;

    always @(posedge ACLK or negedge ARESETn) begin
        if (!ARESETn) begin
            reg_ctrl       <= 32'd0;
            reg_data_in    <= 32'd0;
            latched_awaddr <= {ADDR_WIDTH{1'b0}};
            wstate         <= W_IDLE;
            rstate         <= R_IDLE;
            AWREADY        <= 1'b0;
            WREADY         <= 1'b0;
            BVALID         <= 1'b0;
            BRESP          <= RESP_OKAY;
            ARREADY        <= 1'b0;
            RVALID         <= 1'b0;
            RDATA          <= 32'd0;
            RRESP          <= RESP_OKAY;
        end else begin
            // ---------------- Write FSM ----------------
            case (wstate)
                W_IDLE: begin
                    AWREADY <= 1'b1;
                    WREADY  <= 1'b0;
                    BVALID  <= 1'b0;
                    if (AWVALID && AWREADY) begin
                        latched_awaddr <= AWADDR;
                        AWREADY <= 1'b0;
                        WREADY  <= 1'b1;
                        wstate  <= W_DATA;
                    end
                end

                W_DATA: begin
                    if (WVALID && WREADY) begin
                        WREADY <= 1'b0;
                        case (latched_awaddr)
                            ADDR_CTRL: begin
                                if (WSTRB[0]) reg_ctrl[7:0]   <= WDATA[7:0];
                                if (WSTRB[1]) reg_ctrl[15:8]  <= WDATA[15:8];
                                if (WSTRB[2]) reg_ctrl[23:16] <= WDATA[23:16];
                                if (WSTRB[3]) reg_ctrl[31:24] <= WDATA[31:24];
                                BRESP <= RESP_OKAY;
                            end
                            ADDR_DATA_IN: begin
                                if (WSTRB[0]) reg_data_in[7:0]   <= WDATA[7:0];
                                if (WSTRB[1]) reg_data_in[15:8]  <= WDATA[15:8];
                                if (WSTRB[2]) reg_data_in[23:16] <= WDATA[23:16];
                                if (WSTRB[3]) reg_data_in[31:24] <= WDATA[31:24];
                                BRESP <= RESP_OKAY;
                            end
                            ADDR_DATA_OUT, ADDR_STATUS: BRESP <= RESP_OKAY; // RO writes ignored
                            default: BRESP <= RESP_SLVERR;
                        endcase
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
            endcase

            // ---------------- Read FSM ----------------
            case (rstate)
                R_IDLE: begin
                    ARREADY <= 1'b1;
                    if (ARVALID && ARREADY) begin
                        ARREADY <= 1'b0;
                        case (ARADDR)
                            ADDR_CTRL:     begin RDATA <= reg_ctrl;    RRESP <= RESP_OKAY; end
                            ADDR_DATA_IN:  begin RDATA <= reg_data_in; RRESP <= RESP_OKAY; end
                            ADDR_DATA_OUT: begin RDATA <= 32'd0;       RRESP <= RESP_OKAY; end
                            ADDR_STATUS:   begin RDATA <= 32'd0;       RRESP <= RESP_OKAY; end
                            default:       begin RDATA <= 32'd0;       RRESP <= RESP_SLVERR; end
                        endcase
                        RVALID <= 1'b1;
                        rstate <= R_WAIT;
                    end
                end

                R_WAIT: begin
                    if (RVALID && RREADY) begin
                        RVALID  <= 1'b0;
                        ARREADY <= 1'b1;
                        rstate  <= R_IDLE;
                    end
                end
            endcase
        end
    end

endmodule