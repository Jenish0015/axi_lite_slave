`timescale 1ns / 1ps

// Golden reference RTL in sources/axi_lite_slave_dut.sv (flat, no parameters).
// Write/read FSMs hold BVALID/BRESP and RDATA/RRESP during backpressure.
module axi_lite_slave (
    input  wire                      ACLK,
    input  wire                      ARESETn,

    input  wire [31:0]     AWADDR,
    input  wire                      AWVALID,
    output reg                       AWREADY,

    input  wire [31:0]     WDATA,
    input  wire [3:0]                WSTRB,
    input  wire                      WVALID,
    output reg                       WREADY,

    output reg [1:0]                 BRESP,
    output reg                       BVALID,
    input  wire                      BREADY,

    input  wire [31:0]     ARADDR,
    input  wire                      ARVALID,
    output reg                       ARREADY,

    output reg [31:0]     RDATA,
    output reg [1:0]                 RRESP,
    output reg                       RVALID,
    input  wire                      RREADY
);

    localparam integer PIPE_LEN = 32;

    localparam [31:0] ADDR_CTRL = 32'h0000_0000;
    localparam [31:0] ADDR_DIN  = 32'h0000_0004;
    localparam [31:0] ADDR_DOUT = 32'h0000_0008;
    localparam [31:0] ADDR_STAT = 32'h0000_000C;

    function automatic logic mapped_addr(input [31:0] a);
        mapped_addr = (a == ADDR_CTRL) || (a == ADDR_DIN) || (a == ADDR_DOUT) || (a == ADDR_STAT);
    endfunction

    function automatic logic writable_addr(input [31:0] a);
        writable_addr = (a == ADDR_CTRL) || (a == ADDR_DIN);
    endfunction

    function automatic logic read_only_addr(input [31:0] a);
        read_only_addr = (a == ADDR_DOUT) || (a == ADDR_STAT);
    endfunction

    reg [31:0] ctrl_reg;
    reg [31:0] data_in_reg;
    reg [31:0] data_out_reg;
    reg [31:0] status_reg;

    localparam W_IDLE = 2'd0;
    localparam W_DATA = 2'd1;
    localparam W_RESP = 2'd2;
    reg [1:0] wstate;
    reg [31:0] waddr;

    always @(posedge ACLK or negedge ARESETn) begin
        if (!ARESETn) begin
            wstate      <= W_IDLE;
            AWREADY     <= 1'b1;
            WREADY      <= 1'b0;
            BVALID      <= 1'b0;
            BRESP       <= 2'b00;
            waddr       <= {32{1'b0}};
            ctrl_reg    <= {32{1'b0}};
            data_in_reg <= {32{1'b0}};
        end else begin
            case (wstate)
                W_IDLE: begin
                    AWREADY <= 1'b1;
                    WREADY  <= 1'b0;
                    if (AWVALID && AWREADY) begin
                        waddr   <= AWADDR;
                        AWREADY <= 1'b0;
                        WREADY  <= 1'b1;
                        wstate  <= W_DATA;
                    end
                end
                W_DATA: begin
                    AWREADY <= 1'b0;
                    WREADY  <= 1'b1;
                    if (WVALID && WREADY) begin
                        WREADY <= 1'b0;
                        if (writable_addr(waddr)) begin
                            if (waddr == ADDR_CTRL) begin
                                if (WSTRB[0]) ctrl_reg[7:0]   <= WDATA[7:0];
                                if (WSTRB[1]) ctrl_reg[15:8]  <= WDATA[15:8];
                                if (WSTRB[2]) ctrl_reg[23:16] <= WDATA[23:16];
                                if (WSTRB[3]) ctrl_reg[31:24] <= WDATA[31:24];
                            end else begin
                                if (WSTRB[0]) data_in_reg[7:0]   <= WDATA[7:0];
                                if (WSTRB[1]) data_in_reg[15:8]  <= WDATA[15:8];
                                if (WSTRB[2]) data_in_reg[23:16] <= WDATA[23:16];
                                if (WSTRB[3]) data_in_reg[31:24] <= WDATA[31:24];
                            end
                            BRESP <= 2'b00;
                        end else if (mapped_addr(waddr) && read_only_addr(waddr)) begin
                            BRESP <= 2'b10;
                        end else begin
                            BRESP <= 2'b10;
                        end
                        BVALID <= 1'b1;
                        wstate <= W_RESP;
                    end
                end
                W_RESP: begin
                    AWREADY <= 1'b0;
                    WREADY  <= 1'b0;
                    if (BVALID && BREADY) begin
                        BVALID  <= 1'b0;
                        AWREADY <= 1'b1;
                        wstate  <= W_IDLE;
                    end else begin
                        BVALID <= BVALID;
                        BRESP  <= BRESP;
                    end
                end
                default: wstate <= W_IDLE;
            endcase
        end
    end

    localparam R_IDLE = 1'b0;
    localparam R_HOLD = 1'b1;
    reg rstate;
    reg [31:0] raddr;

    always @(posedge ACLK or negedge ARESETn) begin
        if (!ARESETn) begin
            rstate  <= R_IDLE;
            ARREADY <= 1'b1;
            RVALID  <= 1'b0;
            RDATA   <= {32{1'b0}};
            RRESP   <= 2'b00;
            raddr   <= {32{1'b0}};
        end else begin
            case (rstate)
                R_IDLE: begin
                    ARREADY <= !RVALID;
                    if (ARVALID && ARREADY) begin
                        raddr   <= ARADDR;
                        ARREADY <= 1'b0;
                        if (mapped_addr(ARADDR)) begin
                            case (ARADDR)
                                ADDR_CTRL: begin RDATA <= ctrl_reg;     RRESP <= 2'b00; end
                                ADDR_DIN:  begin RDATA <= data_in_reg;  RRESP <= 2'b00; end
                                ADDR_DOUT: begin RDATA <= data_out_reg; RRESP <= 2'b00; end
                                ADDR_STAT: begin RDATA <= status_reg;   RRESP <= 2'b00; end
                                default:   begin RDATA <= {32{1'b0}}; RRESP <= 2'b10; end
                            endcase
                        end else begin
                            RDATA <= {32{1'b0}};
                            RRESP <= 2'b10;
                        end
                        RVALID <= 1'b1;
                        rstate <= R_HOLD;
                    end
                end
                R_HOLD: begin
                    ARREADY <= 1'b0;
                    if (RVALID && RREADY) begin
                        RVALID <= 1'b0;
                        rstate <= R_IDLE;
                    end else begin
                        RVALID <= RVALID;
                        RDATA  <= RDATA;
                        RRESP  <= RRESP;
                    end
                end
                default: rstate <= R_IDLE;
            endcase
        end
    end

    reg        prev_ctrl0;
    reg        pipe_active;
    reg [5:0]  pipe_cnt;
    reg [31:0] pipe_operand;

    wire ctrl_rise = ctrl_reg[0] && !prev_ctrl0;
    wire ctrl_fall = !ctrl_reg[0] && prev_ctrl0;

    always @(posedge ACLK or negedge ARESETn) begin
        if (!ARESETn) begin
            prev_ctrl0   <= 1'b0;
            pipe_active  <= 1'b0;
            pipe_cnt     <= 6'd0;
            pipe_operand <= {32{1'b0}};
            data_out_reg <= {32{1'b0}};
            status_reg   <= {32{1'b0}};
        end else begin
            prev_ctrl0 <= ctrl_reg[0];

            if (ctrl_rise) begin
                pipe_operand <= data_in_reg;
                pipe_cnt     <= 6'd0;
                pipe_active  <= 1'b1;
            end else if (ctrl_fall) begin
                status_reg[0] <= 1'b0;
                pipe_active   <= 1'b0;
            end else if (pipe_active) begin
                if (pipe_cnt == 6'd31) begin
                    data_out_reg <= ((pipe_operand ^ 32'hA5A5A5A5) + pipe_operand) >> 2;
                    status_reg[0] <= 1'b1;
                    pipe_active   <= 1'b0;
                end else begin
                    pipe_cnt <= pipe_cnt + 6'd1;
                end
            end
        end
    end

endmodule
