`timescale 1ns / 1ps

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

    localparam [ADDR_WIDTH-1:0] ADDR_CTRL       = 6'h00;
    localparam [ADDR_WIDTH-1:0] ADDR_DATA_IN    = 6'h04;
    localparam [ADDR_WIDTH-1:0] ADDR_DATA_OUT   = 6'h08;
    localparam [ADDR_WIDTH-1:0] ADDR_STATUS     = 6'h0C;
    localparam [ADDR_WIDTH-1:0] ADDR_SCRATCH    = 6'h10;
    localparam [ADDR_WIDTH-1:0] ADDR_IRQ_STATUS = 6'h14;

    localparam [1:0] W_IDLE = 2'd0, W_DATA = 2'd1, W_RESP = 2'd2;
    localparam [1:0] R_IDLE = 2'd0, R_DATA = 2'd1;

    reg [31:0] ctrl_reg;
    reg [31:0] data_in_reg;
    reg [31:0] data_out_reg;
    reg [31:0] status_reg;
    reg [31:0] scratch_reg;
    reg [31:0] irq_status_reg;

    reg [1:0]            wstate;
    reg [ADDR_WIDTH-1:0] waddr;
    reg [1:0]            rstate;
    reg [ADDR_WIDTH-1:0] raddr;

    reg        busy;
    reg [1:0]  comp_wait;
    reg        pending_acc_en;
    reg        pending_irq_en;
    reg [31:0] pending_result;

    wire w_done = (wstate == W_DATA) && WVALID && WREADY;
    wire [32:0] sum33 = {1'b0, data_in_reg ^ 32'hA5A5A5A5} + {1'b0, data_in_reg};
    wire [31:0] compute_result = sum33[32:2];

    // Write channel FSM
    always @(posedge ACLK or negedge ARESETn) begin
        if (!ARESETn) begin
            wstate  <= W_IDLE;
            AWREADY <= 1'b1;
            WREADY  <= 1'b0;
            BVALID  <= 1'b0;
            BRESP   <= 2'b00;
            waddr   <= {ADDR_WIDTH{1'b0}};
        end else begin
            case (wstate)
                W_IDLE: begin
                    BVALID <= 1'b0;
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
                        case (waddr)
                            ADDR_CTRL, ADDR_DATA_IN, ADDR_DATA_OUT, ADDR_STATUS, ADDR_SCRATCH, ADDR_IRQ_STATUS:
                                BRESP <= 2'b00;
                            default:
                                BRESP <= 2'b10;
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
                default: wstate <= W_IDLE;
            endcase
        end
    end

    // Read channel FSM
    always @(posedge ACLK or negedge ARESETn) begin
        if (!ARESETn) begin
            rstate   <= R_IDLE;
            ARREADY  <= 1'b1;
            RVALID   <= 1'b0;
            RDATA    <= 32'b0;
            RRESP    <= 2'b00;
            raddr    <= {ADDR_WIDTH{1'b0}};
        end else begin
            case (rstate)
                R_IDLE: begin
                    RVALID <= 1'b0;
                    if (ARVALID && ARREADY) begin
                        ARREADY <= 1'b0;
                        raddr   <= ARADDR;
                        case (ARADDR)
                            ADDR_CTRL:       begin RDATA <= ctrl_reg;       RRESP <= 2'b00; end
                            ADDR_DATA_IN:    begin RDATA <= data_in_reg;    RRESP <= 2'b00; end
                            ADDR_DATA_OUT:   begin RDATA <= data_out_reg;   RRESP <= 2'b00; end
                            ADDR_STATUS:     begin RDATA <= status_reg;     RRESP <= 2'b00; end
                            ADDR_SCRATCH:    begin RDATA <= scratch_reg;    RRESP <= 2'b00; end
                            ADDR_IRQ_STATUS: begin RDATA <= irq_status_reg; RRESP <= 2'b00; end
                            default:         begin RDATA <= 32'b0;          RRESP <= 2'b10; end
                        endcase
                        RVALID <= 1'b1;
                        rstate <= R_DATA;
                    end
                end
                R_DATA: begin
                    if (RREADY && RVALID) begin
                        RVALID  <= 1'b0;
                        ARREADY <= 1'b1;
                        rstate  <= R_IDLE;
                    end
                end
                default: rstate <= R_IDLE;
            endcase
        end
    end

    // Registers and datapath
    always @(posedge ACLK or negedge ARESETn) begin
        if (!ARESETn) begin
            ctrl_reg       <= 32'b0;
            data_in_reg    <= 32'b0;
            data_out_reg   <= 32'b0;
            status_reg     <= 32'b0;
            scratch_reg    <= 32'b0;
            irq_status_reg <= 32'b0;
            busy           <= 1'b0;
            comp_wait      <= 2'd0;
            pending_acc_en <= 1'b0;
            pending_irq_en <= 1'b0;
            pending_result <= 32'b0;
        end else begin
            // Bus writes
            if (w_done) begin
                case (waddr)
                    ADDR_CTRL: begin
                        if (WSTRB[0]) ctrl_reg[2:0] <= WDATA[2:0];
                        status_reg[0] <= 1'b0;
                    end
                    ADDR_DATA_IN: begin
                        if (WSTRB[0]) data_in_reg[7:0]   <= WDATA[7:0];
                        if (WSTRB[1]) data_in_reg[15:8]  <= WDATA[15:8];
                        if (WSTRB[2]) data_in_reg[23:16] <= WDATA[23:16];
                        if (WSTRB[3]) data_in_reg[31:24] <= WDATA[31:24];
                    end
                    ADDR_SCRATCH: begin
                        if (WSTRB[0]) scratch_reg[7:0]   <= WDATA[7:0];
                        if (WSTRB[1]) scratch_reg[15:8]  <= WDATA[15:8];
                        if (WSTRB[2]) scratch_reg[23:16] <= WDATA[23:16];
                        if (WSTRB[3]) scratch_reg[31:24] <= WDATA[31:24];
                    end
                    default: begin
                        // RO and unmapped: no register mutation
                    end
                endcase
            end

            // Launch operation on start pulse when idle
            if (!busy && ctrl_reg[0]) begin
                busy           <= 1'b1;
                comp_wait      <= 2'd2;
                pending_acc_en <= ctrl_reg[1];
                pending_irq_en <= ctrl_reg[2];
                pending_result <= compute_result;
                ctrl_reg[0]    <= 1'b0; // self-clear START
                status_reg[0]  <= 1'b0;
            end else if (busy && (comp_wait != 2'd0)) begin
                comp_wait <= comp_wait - 2'd1;
            end else if (busy && (comp_wait == 2'd0)) begin
                busy <= 1'b0;
                if (pending_acc_en)
                    data_out_reg <= data_out_reg + pending_result;
                else
                    data_out_reg <= pending_result;
                status_reg[0] <= 1'b1;
                if (pending_irq_en)
                    irq_status_reg[0] <= 1'b1;
            end

            // Read-to-clear semantics
            if ((rstate == R_DATA) && RVALID && RREADY && (RRESP == 2'b00)) begin
                if ((raddr == ADDR_STATUS) && RDATA[0])
                    status_reg[0] <= 1'b0;
                if ((raddr == ADDR_IRQ_STATUS) && RDATA[0])
                    irq_status_reg[0] <= 1'b0;
            end
        end
    end

endmodule
