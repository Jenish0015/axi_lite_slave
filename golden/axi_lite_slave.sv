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

    localparam [5:0] ADDR_CTRL     = 6'h00;
    localparam [5:0] ADDR_DATA_IN  = 6'h04;
    localparam [5:0] ADDR_DATA_OUT = 6'h08;
    localparam [5:0] ADDR_STATUS   = 6'h0C;
    localparam [1:0] RESP_OKAY     = 2'b00;
    localparam [1:0] RESP_SLVERR   = 2'b10;
    localparam integer PIPE_CYCLES = 32;

    reg [31:0] ctrl_reg;
    reg [31:0] data_in_reg;
    reg [31:0] data_out_reg;
    reg [31:0] status_reg;

    reg [5:0]  pipe_count;
    reg [31:0] pipe_operand;
    reg        pipe_busy;
    reg        cancel_run;

    reg                  aw_latched;
    reg                  w_latched;
    reg [ADDR_WIDTH-1:0] aw_addr_reg;
    reg [DATA_WIDTH-1:0] w_data_reg;
    reg [3:0]            w_strb_reg;

    reg                  read_pending;
    reg [ADDR_WIDTH-1:0] ar_addr_reg;

    wire [31:0] exp_result = (((pipe_operand ^ 32'hA5A5A5A5) + pipe_operand) & 32'hFFFF_FFFF) >> 2;
    wire pipe_advance = !AWVALID && !WVALID && !ARVALID && !BVALID && !RVALID;

    always @(posedge ACLK or negedge ARESETn) begin
        if (!ARESETn) begin
            AWREADY      <= 1'b0;
            WREADY       <= 1'b0;
            BRESP        <= RESP_OKAY;
            BVALID       <= 1'b0;
            ARREADY      <= 1'b0;
            RDATA        <= 32'd0;
            RRESP        <= RESP_OKAY;
            RVALID       <= 1'b0;

            aw_latched   <= 1'b0;
            w_latched    <= 1'b0;
            aw_addr_reg  <= {ADDR_WIDTH{1'b0}};
            w_data_reg   <= 32'd0;
            w_strb_reg   <= 4'd0;

            read_pending <= 1'b0;
            ar_addr_reg  <= {ADDR_WIDTH{1'b0}};

            ctrl_reg     <= 32'd0;
            data_in_reg  <= 32'd0;
            data_out_reg <= 32'd0;
            status_reg   <= 32'd0;

            pipe_count   <= 6'd0;
            pipe_operand <= 32'd0;
            pipe_busy    <= 1'b0;
            cancel_run   <= 1'b0;
        end else begin
            cancel_run = 1'b0;

            if (!aw_latched && !(BVALID && !BREADY)) begin
                AWREADY <= 1'b1;
                if (AWVALID) begin
                    AWREADY     <= 1'b0;
                    aw_latched  <= 1'b1;
                    aw_addr_reg <= AWADDR;
                end
            end else begin
                AWREADY <= 1'b0;
            end

            if (!w_latched && !(BVALID && !BREADY)) begin
                WREADY <= 1'b1;
                if (WVALID) begin
                    WREADY    <= 1'b0;
                    w_latched <= 1'b1;
                    w_data_reg<= WDATA;
                    w_strb_reg<= WSTRB;
                end
            end else begin
                WREADY <= 1'b0;
            end

            if (aw_latched && w_latched && !BVALID) begin
                BRESP <= RESP_OKAY;
                if (aw_addr_reg == ADDR_CTRL) begin
                    if (w_strb_reg[0]) ctrl_reg[7:0]   <= w_data_reg[7:0];
                    if (w_strb_reg[1]) ctrl_reg[15:8]  <= w_data_reg[15:8];
                    if (w_strb_reg[2]) ctrl_reg[23:16] <= w_data_reg[23:16];
                    if (w_strb_reg[3]) ctrl_reg[31:24] <= w_data_reg[31:24];

                    if (w_strb_reg[0] && !w_data_reg[0]) begin
                        cancel_run   = 1'b1;
                        pipe_busy    <= 1'b0;
                        pipe_count   <= 6'd0;
                        status_reg   <= 32'd0;
                        data_out_reg <= 32'd0;
                    end

                    if (w_strb_reg[0] && w_data_reg[0]) begin
                        cancel_run   = 1'b1;
                        pipe_busy    <= 1'b1;
                        pipe_count   <= 6'd0;
                        pipe_operand <= data_in_reg;
                        status_reg   <= 32'd0;
                        data_out_reg <= 32'd0;
                    end
                end else if (aw_addr_reg == ADDR_DATA_IN) begin
                    if (w_strb_reg[0]) data_in_reg[7:0]   <= w_data_reg[7:0];
                    if (w_strb_reg[1]) data_in_reg[15:8]  <= w_data_reg[15:8];
                    if (w_strb_reg[2]) data_in_reg[23:16] <= w_data_reg[23:16];
                    if (w_strb_reg[3]) data_in_reg[31:24] <= w_data_reg[31:24];
                end else if (aw_addr_reg == ADDR_DATA_OUT || aw_addr_reg == ADDR_STATUS) begin
                    // Writes to read-only locations are accepted and ignored.
                end else begin
                    BRESP <= RESP_SLVERR;
                end

                BVALID     <= 1'b1;
                aw_latched <= 1'b0;
                w_latched  <= 1'b0;
            end

            if (BVALID && BREADY) begin
                BVALID = 1'b0;
            end

            if (!read_pending && !RVALID) begin
                ARREADY <= 1'b1;
                if (ARVALID) begin
                    ARREADY      <= 1'b0;
                    read_pending <= 1'b1;
                    ar_addr_reg  <= ARADDR;
                end
            end else begin
                ARREADY <= 1'b0;
            end

            if (RVALID) begin
                if (RREADY) begin
                    RVALID       = 1'b0;
                    read_pending = 1'b0;
                end
            end else if (read_pending) begin
                case (ar_addr_reg)
                    ADDR_CTRL: begin
                        RDATA <= ctrl_reg;
                        RRESP <= RESP_OKAY;
                    end
                    ADDR_DATA_IN: begin
                        RDATA <= data_in_reg;
                        RRESP <= RESP_OKAY;
                    end
                    ADDR_DATA_OUT: begin
                        RDATA <= data_out_reg;
                        RRESP <= RESP_OKAY;
                    end
                    ADDR_STATUS: begin
                        RDATA <= status_reg;
                        RRESP <= RESP_OKAY;
                    end
                    default: begin
                        RDATA <= 32'd0;
                        RRESP <= RESP_SLVERR;
                    end
                endcase
                RVALID <= 1'b1;
            end

            if (pipe_busy && !cancel_run && pipe_advance) begin
                if (pipe_count == PIPE_CYCLES - 1) begin
                    pipe_busy    <= 1'b0;
                    data_out_reg <= exp_result;
                    status_reg   <= 32'h1;
                    ctrl_reg[0]  <= 1'b0;
                end else begin
                    pipe_count <= pipe_count + 1'b1;
                end
            end
        end
    end

endmodule
`timescale 1ns / 1ps

module axi_lite_slave_tb;

    // ---------------------------------------------------------------
    // Parameters
    // ---------------------------------------------------------------
    localparam DATA_WIDTH  = 32;
    localparam ADDR_WIDTH  = 6;
    localparam CLK_PERIOD  = 10;

    localparam [5:0] ADDR_CTRL     = 6'h00;
    localparam [5:0] ADDR_DATA_IN  = 6'h04;
    localparam [5:0] ADDR_DATA_OUT = 6'h08;
    localparam [5:0] ADDR_STATUS   = 6'h0C;

    // ---------------------------------------------------------------
    // DUT interface signals
    // ---------------------------------------------------------------
    logic                   ACLK;
    logic                   ARESETn;

    logic [ADDR_WIDTH-1:0]  AWADDR;
    logic                   AWVALID;
    wire                    AWREADY;

    logic [DATA_WIDTH-1:0]  WDATA;
    logic [3:0]             WSTRB;
    logic                   WVALID;
    wire                    WREADY;

    wire  [1:0]             BRESP;
    wire                    BVALID;
    logic                   BREADY;

    logic [ADDR_WIDTH-1:0]  ARADDR;
    logic                   ARVALID;
    wire                    ARREADY;

    wire  [DATA_WIDTH-1:0]  RDATA;
    wire  [1:0]             RRESP;
    wire                    RVALID;
    logic                   RREADY;

    // ---------------------------------------------------------------
    // Internal testbench state
    // ---------------------------------------------------------------
    logic [DATA_WIDTH-1:0]  read_data;
    logic [1:0]             read_resp;
    logic [1:0]             write_resp;
    integer                 test_num;

    // ---------------------------------------------------------------
    // DUT instantiation
    // ---------------------------------------------------------------
    axi_lite_slave #(
        .DATA_WIDTH (DATA_WIDTH),
        .ADDR_WIDTH (ADDR_WIDTH)
    ) dut (
        .ACLK    (ACLK),
        .ARESETn (ARESETn),
        .AWADDR  (AWADDR),
        .AWVALID (AWVALID),
        .AWREADY (AWREADY),
        .WDATA   (WDATA),
        .WSTRB   (WSTRB),
        .WVALID  (WVALID),
        .WREADY  (WREADY),
        .BRESP   (BRESP),
        .BVALID  (BVALID),
        .BREADY  (BREADY),
        .ARADDR  (ARADDR),
        .ARVALID (ARVALID),
        .ARREADY (ARREADY),
        .RDATA   (RDATA),
        .RRESP   (RRESP),
        .RVALID  (RVALID),
        .RREADY  (RREADY)
    );

    // ---------------------------------------------------------------
    // Clock generation
    // ---------------------------------------------------------------
    initial ACLK = 0;
    always #(CLK_PERIOD / 2) ACLK = ~ACLK;

    // ---------------------------------------------------------------
    // Tasks
    // ---------------------------------------------------------------
    task axi_idle;
        // Internal logic
    endtask

    task axi_write (
        input logic [ADDR_WIDTH-1:0] addr,
        input logic [DATA_WIDTH-1:0] data,
        input logic [3:0]            strb
    );
        // Internal logic
    endtask

    task axi_read (
        input  logic [ADDR_WIDTH-1:0] addr,
        output logic [DATA_WIDTH-1:0] data,
        output logic [1:0]            resp
    );
        // Internal logic
    endtask

    task wait_done (
        input integer timeout_cycles
    );
        // Internal logic
    endtask

    // ---------------------------------------------------------------
    // Stimulus
    // ---------------------------------------------------------------
    initial begin
        $dumpfile("axi_lite_slave_tb.vcd");
        $dumpvars(0, axi_lite_slave_tb);

        // Internal logic
    end

endmodule