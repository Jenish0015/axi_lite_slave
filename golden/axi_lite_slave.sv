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

    localparam [ADDR_WIDTH-1:0] ADDR_FIFO_PUSH   = 6'h00;
    localparam [ADDR_WIDTH-1:0] ADDR_FIFO_STATUS = 6'h04;
    localparam [ADDR_WIDTH-1:0] ADDR_FIFO_POP    = 6'h08;
    localparam [ADDR_WIDTH-1:0] ADDR_FIFO_SUM    = 6'h0C;

    reg [31:0] fifo_mem [0:7];
    reg [2:0]  rd_ptr;
    reg [2:0]  wr_ptr;
    reg [3:0]  count;

    reg                    aw_latched;
    reg                    w_latched;
    reg [ADDR_WIDTH-1:0]   aw_addr_reg;
    reg [DATA_WIDTH-1:0]   w_data_reg;
    reg [3:0]              w_strb_reg;

    reg                    pop_pending;

    wire fifo_full  = (count == 4'd8);
    wire fifo_empty = (count == 4'd0);

    integer i;
    reg [31:0] fifo_sum_comb;
    reg [31:0] push_data;
    reg do_push, do_pop;

    always @(*) begin
        fifo_sum_comb = 32'd0;
        for (i = 0; i < count; i = i + 1)
            fifo_sum_comb = fifo_sum_comb + fifo_mem[(rd_ptr + i) & 3'h7];

        push_data[7:0]   = w_strb_reg[0] ? w_data_reg[7:0]   : 8'h00;
        push_data[15:8]  = w_strb_reg[1] ? w_data_reg[15:8]  : 8'h00;
        push_data[23:16] = w_strb_reg[2] ? w_data_reg[23:16] : 8'h00;
        push_data[31:24] = w_strb_reg[3] ? w_data_reg[31:24] : 8'h00;
    end

    always @(posedge ACLK or negedge ARESETn) begin
        if (!ARESETn) begin
            AWREADY    <= 1'b0;
            WREADY     <= 1'b0;
            BVALID     <= 1'b0;
            BRESP      <= 2'b00;
            ARREADY    <= 1'b0;
            RVALID     <= 1'b0;
            RDATA      <= 32'b0;
            RRESP      <= 2'b00;

            aw_latched <= 1'b0;
            w_latched  <= 1'b0;
            aw_addr_reg <= {ADDR_WIDTH{1'b0}};
            w_data_reg  <= {DATA_WIDTH{1'b0}};
            w_strb_reg  <= 4'b0;
            pop_pending <= 1'b0;

            rd_ptr <= 3'd0;
            wr_ptr <= 3'd0;
            count  <= 4'd0;
            for (i = 0; i < 8; i = i + 1)
                fifo_mem[i] <= 32'd0;
        end else begin
            do_push = 1'b0;
            do_pop  = 1'b0;

            AWREADY <= (!aw_latched) && (!BVALID);
            WREADY  <= (!w_latched)  && (!BVALID);
            ARREADY <= (!RVALID);

            if (!aw_latched && !BVALID && AWVALID) begin
                aw_latched  <= 1'b1;
                aw_addr_reg <= AWADDR;
            end

            if (!w_latched && !BVALID && WVALID) begin
                w_latched <= 1'b1;
                w_data_reg <= WDATA;
                w_strb_reg <= WSTRB;
            end

            if (aw_latched && w_latched && !BVALID) begin
                case (aw_addr_reg)
                    ADDR_FIFO_PUSH: begin
                        if (!fifo_full) begin
                            do_push = 1'b1;
                            BRESP   <= 2'b00;
                        end else begin
                            BRESP   <= 2'b10;
                        end
                    end
                    ADDR_FIFO_STATUS,
                    ADDR_FIFO_POP,
                    ADDR_FIFO_SUM: BRESP <= 2'b00;
                    default:       BRESP <= 2'b10;
                endcase
                BVALID     <= 1'b1;
                aw_latched <= 1'b0;
                w_latched  <= 1'b0;
            end

            if (BVALID && BREADY)
                BVALID <= 1'b0;

            if (!RVALID && ARVALID) begin
                case (ARADDR)
                    ADDR_FIFO_PUSH: begin
                        RDATA <= 32'd0;
                        RRESP <= 2'b00;
                        pop_pending <= 1'b0;
                    end
                    ADDR_FIFO_STATUS: begin
                        RDATA <= {26'd0, fifo_empty, fifo_full, count};
                        RRESP <= 2'b00;
                        pop_pending <= 1'b0;
                    end
                    ADDR_FIFO_POP: begin
                        if (!fifo_empty) begin
                            RDATA <= fifo_mem[rd_ptr];
                            RRESP <= 2'b00;
                            pop_pending <= 1'b1;
                        end else begin
                            RDATA <= 32'hDEADBEEF;
                            RRESP <= 2'b10;
                            pop_pending <= 1'b0;
                        end
                    end
                    ADDR_FIFO_SUM: begin
                        RDATA <= fifo_sum_comb;
                        RRESP <= 2'b00;
                        pop_pending <= 1'b0;
                    end
                    default: begin
                        RDATA <= 32'd0;
                        RRESP <= 2'b10;
                        pop_pending <= 1'b0;
                    end
                endcase
                RVALID <= 1'b1;
            end

            if (RVALID && RREADY) begin
                if (pop_pending) begin
                    do_pop = 1'b1;
                    pop_pending <= 1'b0;
                end
                RVALID <= 1'b0;
            end

            if (do_push) begin
                fifo_mem[wr_ptr] <= push_data;
                wr_ptr <= wr_ptr + 3'd1;
            end
            if (do_pop)
                rd_ptr <= rd_ptr + 3'd1;

            case ({do_push, do_pop})
                2'b10: count <= count + 4'd1;
                2'b01: count <= count - 4'd1;
                default: count <= count;
            endcase
        end
    end

endmodule