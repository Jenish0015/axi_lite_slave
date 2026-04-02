`timescale 1ns/1ps

// Reference (golden) AXI-Lite slave: matches cocotb tests in tests/test_axi_lite_slave_hidden.py
module axi_lite_slave (
    input  logic        ACLK,
    input  logic        ARESETn,

    input  logic [31:0] AWADDR,
    input  logic        AWVALID,
    output logic        AWREADY,

    input  logic [31:0] WDATA,
    input  logic [3:0]  WSTRB,
    input  logic        WVALID,
    output logic        WREADY,

    output logic [1:0]  BRESP,
    output logic        BVALID,
    input  logic        BREADY,

    input  logic [31:0] ARADDR,
    input  logic        ARVALID,
    output logic        ARREADY,

    output logic [31:0] RDATA,
    output logic [1:0]  RRESP,
    output logic        RVALID,
    input  logic        RREADY
);

    localparam int unsigned PIPE_CYCLES = 32;

    localparam logic [5:0] ADDR_CTRL     = 6'h00;
    localparam logic [5:0] ADDR_DATA_IN  = 6'h04;
    localparam logic [5:0] ADDR_DATA_OUT = 6'h08;
    localparam logic [5:0] ADDR_STATUS   = 6'h0C;

    logic [31:0] ctrl_reg;
    logic [31:0] data_in_reg;
    logic [31:0] data_out_reg;
    logic [31:0] status_reg;

    logic [31:0] operand_reg;
    logic [31:0] pipe_ctr;
    logic        pipe_busy;

    typedef enum logic [1:0] {
        WST_IDLE,
        WST_AW,
        WST_RESP
    } w_state_e;

    w_state_e w_state;
    logic [31:0] w_addr_latch;

    typedef enum logic [1:0] {
        RST_IDLE,
        RST_DATA
    } r_state_e;

    r_state_e r_state;
    logic [31:0] r_addr_latch;

    logic [31:0] rdata_mux;

    function automatic logic [31:0] exp_fn(input logic [31:0] v);
        exp_fn = (((v ^ 32'hA5A5A5A5) + v) >> 2);
    endfunction

    wire pipe_stall = (RVALID & ~RREADY) | (BVALID & ~BREADY);

    assign BRESP = 2'b00;
    assign RRESP = 2'b00;
    assign RDATA = RVALID ? rdata_mux : 32'd0;

    always_comb begin
        case (r_addr_latch[5:0])
            ADDR_CTRL:     rdata_mux = ctrl_reg;
            ADDR_DATA_IN:  rdata_mux = data_in_reg;
            ADDR_DATA_OUT: rdata_mux = pipe_busy ? 32'd0 : data_out_reg;
            ADDR_STATUS:   rdata_mux = status_reg;
            default:       rdata_mux = 32'd0;
        endcase
    end

    always_ff @(posedge ACLK or negedge ARESETn) begin
        if (!ARESETn) begin
            w_state      <= WST_IDLE;
            w_addr_latch <= '0;
            AWREADY      <= 1'b0;
            WREADY       <= 1'b0;
            BVALID       <= 1'b0;
        end else begin
            case (w_state)
                WST_IDLE: begin
                    AWREADY <= (!BVALID) || BREADY;
                    WREADY  <= 1'b0;
                    if (AWVALID && AWREADY) begin
                        w_addr_latch <= AWADDR;
                        w_state      <= WST_AW;
                        AWREADY      <= 1'b0;
                        WREADY       <= 1'b1;
                    end
                end
                WST_AW: begin
                    AWREADY <= 1'b0;
                    WREADY  <= 1'b1;
                    if (WVALID && WREADY) begin
                        WREADY  <= 1'b0;
                        w_state <= WST_RESP;
                        BVALID  <= 1'b1;
                    end
                end
                WST_RESP: begin
                    AWREADY <= 1'b0;
                    WREADY  <= 1'b0;
                    if (BVALID && BREADY) begin
                        BVALID  <= 1'b0;
                        w_state <= WST_IDLE;
                    end
                end
                default: w_state <= WST_IDLE;
            endcase
        end
    end

    always_ff @(posedge ACLK or negedge ARESETn) begin
        if (!ARESETn) begin
            r_state      <= RST_IDLE;
            r_addr_latch <= '0;
            ARREADY      <= 1'b1;
            RVALID       <= 1'b0;
        end else begin
            case (r_state)
                RST_IDLE: begin
                    ARREADY <= 1'b1;
                    if (ARVALID && ARREADY) begin
                        r_addr_latch <= ARADDR;
                        ARREADY      <= 1'b0;
                        RVALID       <= 1'b1;
                        r_state      <= RST_DATA;
                    end
                end
                RST_DATA: begin
                    ARREADY <= 1'b0;
                    if (RVALID && RREADY) begin
                        RVALID  <= 1'b0;
                        r_state <= RST_IDLE;
                    end
                end
                default: r_state <= RST_IDLE;
            endcase
        end
    end

    always_ff @(posedge ACLK or negedge ARESETn) begin
        if (!ARESETn) begin
            ctrl_reg     <= '0;
            data_in_reg  <= '0;
            data_out_reg <= '0;
            status_reg   <= '0;
            operand_reg  <= '0;
            pipe_ctr     <= '0;
            pipe_busy    <= 1'b0;
        end else begin
            if (w_state == WST_AW && WVALID && WREADY) begin
                case (w_addr_latch[5:0])
                    ADDR_CTRL: begin
                        if (WSTRB[0]) ctrl_reg[7:0] <= WDATA[7:0];
                        if (WSTRB[1]) ctrl_reg[15:8] <= WDATA[15:8];
                        if (WSTRB[2]) ctrl_reg[23:16] <= WDATA[23:16];
                        if (WSTRB[3]) ctrl_reg[31:24] <= WDATA[31:24];
                        if (WSTRB[0]) begin
                            if (WDATA[0]) begin
                                operand_reg <= data_in_reg;
                                pipe_ctr    <= PIPE_CYCLES[31:0];
                                pipe_busy   <= 1'b1;
                                status_reg  <= '0;
                            end else begin
                                pipe_busy  <= 1'b0;
                                pipe_ctr   <= '0;
                                status_reg <= '0;
                            end
                        end
                    end
                    ADDR_DATA_IN: begin
                        for (int k = 0; k < 4; k++) begin
                            if (WSTRB[k]) begin
                                data_in_reg[8*k +: 8] <= WDATA[8*k +: 8];
                            end
                        end
                    end
                    default: ;
                endcase
            end else if (pipe_busy && !pipe_stall) begin
                if (pipe_ctr == 32'd1) begin
                    data_out_reg <= exp_fn(operand_reg);
                    pipe_busy    <= 1'b0;
                    pipe_ctr     <= 32'd0;
                    status_reg   <= 32'h1;
                end else if (pipe_ctr > 32'd0) begin
                    pipe_ctr <= pipe_ctr - 32'd1;
                end
            end
        end
    end

endmodule
