`timescale 1ns/1ps
 
// =============================================================================
// AXI-Lite Slave — Extended Register Map
// =============================================================================
//
//  0x00  CTRL      (RW)
//          [0]   start       — write 1 to begin computation (self-clearing)
//          [1]   acc_en      — when 1, DATA_OUT accumulates across triggers
//                              (result += new_result each trigger)
//                              when 0, DATA_OUT is overwritten each trigger
//          [2]   irq_en      — enables the IRQ output pin
//          [7:3] reserved    — RAZ/WI
//
//  0x04  DATA_IN   (RW)      — input operand, byte-strobe supported
//
//  0x08  DATA_OUT  (RO)      — computation result / accumulator
//
//  0x0C  STATUS    (RO, read-to-clear bit[0])
//          [0]   done        — set when pipeline completes; CLEARED ON READ
//          [1]   busy        — high while 3-cycle pipeline is running
//          [3:2] reserved    — RAZ
//
//  0x10  SCRATCH   (RW)      — general-purpose scratch register,
//                              byte-strobe supported, no side-effects
//
//  0x14  IRQ_STATUS (RO, read-to-clear)
//          [0]   irq_done    — latches high when computation done & irq_en=1
//                              CLEARED ON READ
//
// Unmapped addresses: read → RDATA=0, RRESP=SLVERR
//                     write → silently ignored, BRESP=SLVERR
//
// Computation (3-cycle pipeline):
//   Stage 1:  xor_val  = DATA_IN ^ 32'hA5A5A5A5
//   Stage 2:  sum_val  = {1'b0,xor_val} + {1'b0,DATA_IN}   (33-bit)
//   Stage 3:  result   = sum_val[32:0] >> 2
//
// acc_en mode:  DATA_OUT <= DATA_OUT + result   (32-bit, wrapping)
// normal mode:  DATA_OUT <= result
//
// IRQ output pin is the registered (flopped) value of:
//   irq_en & irq_status[0]
//
// =============================================================================
 
module axi_lite_slave #(
    parameter DATA_WIDTH = 32,
    parameter ADDR_WIDTH = 6
)(
    input  logic                   ACLK,
    input  logic                   ARESETn,
 
    input  logic [ADDR_WIDTH-1:0]  AWADDR,
    input  logic                   AWVALID,
    output logic                   AWREADY,
 
    input  logic [DATA_WIDTH-1:0]  WDATA,
    input  logic [3:0]             WSTRB,
    input  logic                   WVALID,
    output logic                   WREADY,
 
    output logic [1:0]             BRESP,
    output logic                   BVALID,
    input  logic                   BREADY,
 
    input  logic [ADDR_WIDTH-1:0]  ARADDR,
    input  logic                   ARVALID,
    output logic                   ARREADY,
 
    output logic [DATA_WIDTH-1:0]  RDATA,
    output logic [1:0]             RRESP,
    output logic                   RVALID,
    input  logic                   RREADY,
 
    output logic                   IRQ        // interrupt output
);
 
    // -------------------------------------------------------------------------
    // Address map
    // -------------------------------------------------------------------------
    localparam [ADDR_WIDTH-1:0] ADDR_CTRL       = 6'h00;
    localparam [ADDR_WIDTH-1:0] ADDR_DATA_IN    = 6'h04;
    localparam [ADDR_WIDTH-1:0] ADDR_DATA_OUT   = 6'h08;
    localparam [ADDR_WIDTH-1:0] ADDR_STATUS     = 6'h0C;
    localparam [ADDR_WIDTH-1:0] ADDR_SCRATCH    = 6'h10;
    localparam [ADDR_WIDTH-1:0] ADDR_IRQ_STATUS = 6'h14;
 
    localparam [1:0] RESP_OKAY   = 2'b00;
    localparam [1:0] RESP_SLVERR = 2'b10;
 
    // -------------------------------------------------------------------------
    // Registers
    // -------------------------------------------------------------------------
    logic [DATA_WIDTH-1:0] reg_ctrl;        // [2:0] used
    logic [DATA_WIDTH-1:0] reg_data_in;
    logic [DATA_WIDTH-1:0] reg_data_out;
    logic [DATA_WIDTH-1:0] reg_status;      // [1:0] used; bit[0] read-to-clear
    logic [DATA_WIDTH-1:0] reg_scratch;
    logic [DATA_WIDTH-1:0] reg_irq_status;  // bit[0] read-to-clear
 
    // CTRL bit aliases
    logic ctrl_start;
    logic ctrl_acc_en;
    logic ctrl_irq_en;
    assign ctrl_start  = reg_ctrl[0];
    assign ctrl_acc_en = reg_ctrl[1];
    assign ctrl_irq_en = reg_ctrl[2];
 
    // -------------------------------------------------------------------------
    // 3-stage computation pipeline
    // -------------------------------------------------------------------------
    // Stage 0 → 1
    logic        pipe_valid_s1;
    logic [31:0] pipe_data_in_s1;   // captured DATA_IN at trigger
    logic        pipe_acc_en_s1;    // captured acc_en at trigger
 
    // Stage 1 → 2
    logic        pipe_valid_s2;
    logic [31:0] pipe_xor_s2;
    logic [31:0] pipe_orig_s2;
    logic        pipe_acc_en_s2;
 
    // Stage 2 → 3 (done)
    logic        pipe_valid_s3;
    logic [32:0] pipe_sum_s3;
    logic        pipe_acc_en_s3;
 
    always_ff @(posedge ACLK or negedge ARESETn) begin
        if (!ARESETn) begin
            pipe_valid_s1  <= 1'b0;
            pipe_valid_s2  <= 1'b0;
            pipe_valid_s3  <= 1'b0;
            pipe_data_in_s1<= '0;
            pipe_acc_en_s1 <= 1'b0;
            pipe_xor_s2    <= '0;
            pipe_orig_s2   <= '0;
            pipe_acc_en_s2 <= 1'b0;
            pipe_sum_s3    <= '0;
            pipe_acc_en_s3 <= 1'b0;
        end else begin
            // Stage 0 → 1: trigger fires when CTRL[0] written
            // (ctrl_start is the registered value; we detect a write in the
            //  write-commit logic below and set pipe_valid_s1 there)
 
            // Stage 1 → 2
            pipe_valid_s2  <= pipe_valid_s1;
            pipe_xor_s2    <= pipe_data_in_s1 ^ 32'hA5A5A5A5;
            pipe_orig_s2   <= pipe_data_in_s1;
            pipe_acc_en_s2 <= pipe_acc_en_s1;
 
            // Stage 2 → 3
            pipe_valid_s3  <= pipe_valid_s2;
            pipe_sum_s3    <= {1'b0, pipe_xor_s2} + {1'b0, pipe_orig_s2};
            pipe_acc_en_s3 <= pipe_acc_en_s2;
        end
    end
 
    // Pipeline completion: update DATA_OUT, STATUS, IRQ_STATUS
    always_ff @(posedge ACLK or negedge ARESETn) begin
        if (!ARESETn) begin
            reg_data_out        <= '0;
            reg_status          <= '0;
            reg_irq_status      <= '0;
            IRQ                 <= 1'b0;
        end else begin
            // Default: clear busy when pipeline drains
            reg_status[1] <= pipe_valid_s1 | pipe_valid_s2 | pipe_valid_s3;
 
            if (pipe_valid_s3) begin
                logic [31:0] result;
                result = (pipe_sum_s3 & 33'h1_FFFF_FFFF) >> 2;
 
                if (pipe_acc_en_s3)
                    reg_data_out <= reg_data_out + result;
                else
                    reg_data_out <= result;
 
                reg_status[0]     <= 1'b1;       // done
                reg_irq_status[0] <= ctrl_irq_en; // latch IRQ if enabled
            end
 
            // IRQ pin: flopped ctrl_irq_en & irq_status[0]
            IRQ <= ctrl_irq_en & reg_irq_status[0];
        end
    end
 
    // -------------------------------------------------------------------------
    // Write channel
    // -------------------------------------------------------------------------
    logic                  aw_latched;
    logic [ADDR_WIDTH-1:0] aw_addr;
    logic                  w_latched;
    logic [DATA_WIDTH-1:0] w_data;
    logic [3:0]            w_strb;
 
    always_ff @(posedge ACLK or negedge ARESETn) begin
        if (!ARESETn) begin
            AWREADY    <= 1'b0;
            WREADY     <= 1'b0;
            BVALID     <= 1'b0;
            BRESP      <= RESP_OKAY;
            aw_latched <= 1'b0;
            w_latched  <= 1'b0;
            aw_addr    <= '0;
            w_data     <= '0;
            w_strb     <= '0;
            reg_ctrl    <= '0;
            reg_data_in <= '0;
            reg_scratch <= '0;
            pipe_valid_s1   <= 1'b0;
            pipe_data_in_s1 <= '0;
            pipe_acc_en_s1  <= 1'b0;
        end else begin
 
            // Default: pipeline stage 1 valid only held one cycle
            pipe_valid_s1 <= 1'b0;
 
            // Accept write address
            if (!aw_latched && !BVALID) begin
                AWREADY <= 1'b1;
                if (AWVALID) begin
                    aw_addr    <= AWADDR;
                    aw_latched <= 1'b1;
                    AWREADY    <= 1'b0;
                end
            end else begin
                AWREADY <= 1'b0;
            end
 
            // Accept write data
            if (!w_latched && !BVALID) begin
                WREADY <= 1'b1;
                if (WVALID) begin
                    w_data    <= WDATA;
                    w_strb    <= WSTRB;
                    w_latched <= 1'b1;
                    WREADY    <= 1'b0;
                end
            end else begin
                WREADY <= 1'b0;
            end
 
            // Commit write
            if (aw_latched && w_latched && !BVALID) begin
                case (aw_addr)
                    ADDR_CTRL: begin
                        // Only bits [2:0] are writable; upper bits RAZ/WI
                        if (w_strb[0]) begin
                            reg_ctrl[2:0] <= w_data[2:0];
                            // If start bit written, launch pipeline
                            if (w_data[0]) begin
                                pipe_valid_s1   <= 1'b1;
                                pipe_data_in_s1 <= reg_data_in;
                                pipe_acc_en_s1  <= w_data[1]; // use new acc_en
                                reg_ctrl[0]     <= 1'b0;      // self-clear start
                                reg_status[0]   <= 1'b0;      // clear done
                            end
                        end
                        BRESP <= RESP_OKAY;
                    end
 
                    ADDR_DATA_IN: begin
                        if (w_strb[0]) reg_data_in[7:0]   <= w_data[7:0];
                        if (w_strb[1]) reg_data_in[15:8]  <= w_data[15:8];
                        if (w_strb[2]) reg_data_in[23:16] <= w_data[23:16];
                        if (w_strb[3]) reg_data_in[31:24] <= w_data[31:24];
                        BRESP <= RESP_OKAY;
                    end
 
                    ADDR_SCRATCH: begin
                        if (w_strb[0]) reg_scratch[7:0]   <= w_data[7:0];
                        if (w_strb[1]) reg_scratch[15:8]  <= w_data[15:8];
                        if (w_strb[2]) reg_scratch[23:16] <= w_data[23:16];
                        if (w_strb[3]) reg_scratch[31:24] <= w_data[31:24];
                        BRESP <= RESP_OKAY;
                    end
 
                    ADDR_DATA_OUT,
                    ADDR_STATUS,
                    ADDR_IRQ_STATUS: begin
                        // Read-only: ignore write, BRESP=OKAY
                        BRESP <= RESP_OKAY;
                    end
 
                    default: begin
                        BRESP <= RESP_SLVERR;
                    end
                endcase
 
                BVALID     <= 1'b1;
                aw_latched <= 1'b0;
                w_latched  <= 1'b0;
            end
 
            // Deassert BVALID
            if (BVALID && BREADY)
                BVALID <= 1'b0;
        end
    end
 
    // -------------------------------------------------------------------------
    // Read channel  (read-to-clear on STATUS[0] and IRQ_STATUS[0])
    // -------------------------------------------------------------------------
    typedef enum logic { RD_IDLE = 1'b0, RD_WAIT = 1'b1 } rd_state_t;
    rd_state_t rd_state;
 
    always_ff @(posedge ACLK or negedge ARESETn) begin
        if (!ARESETn) begin
            ARREADY  <= 1'b0;
            RVALID   <= 1'b0;
            RDATA    <= '0;
            RRESP    <= RESP_OKAY;
            rd_state <= RD_IDLE;
        end else begin
            case (rd_state)
                RD_IDLE: begin
                    ARREADY <= 1'b1;
                    if (ARVALID) begin
                        ARREADY <= 1'b0;
                        RVALID  <= 1'b1;
                        case (ARADDR)
                            ADDR_CTRL: begin
                                RDATA <= {reg_ctrl[31:3], 3'b0} | {29'b0, reg_ctrl[2:0]};
                                RRESP <= RESP_OKAY;
                            end
                            ADDR_DATA_IN: begin
                                RDATA <= reg_data_in;
                                RRESP <= RESP_OKAY;
                            end
                            ADDR_DATA_OUT: begin
                                RDATA <= reg_data_out;
                                RRESP <= RESP_OKAY;
                            end
                            ADDR_STATUS: begin
                                RDATA         <= reg_status;
                                RRESP         <= RESP_OKAY;
                                reg_status[0] <= 1'b0;  // read-to-clear done bit
                            end
                            ADDR_SCRATCH: begin
                                RDATA <= reg_scratch;
                                RRESP <= RESP_OKAY;
                            end
                            ADDR_IRQ_STATUS: begin
                                RDATA              <= reg_irq_status;
                                RRESP              <= RESP_OKAY;
                                reg_irq_status[0]  <= 1'b0;  // read-to-clear
                            end
                            default: begin
                                RDATA <= '0;
                                RRESP <= RESP_SLVERR;
                            end
                        endcase
                        rd_state <= RD_WAIT;
                    end
                end
 
                RD_WAIT: begin
                    ARREADY <= 1'b0;
                    if (RVALID && RREADY) begin
                        RVALID   <= 1'b0;
                        rd_state <= RD_IDLE;
                    end
                end
 
                default: rd_state <= RD_IDLE;
            endcase
        end
    end
 
endmodule