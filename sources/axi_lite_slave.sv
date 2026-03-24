

`timescale 1ns/1ps

module tb_axi_lite_slave;

    localparam DATA_WIDTH = 32;
    localparam ADDR_WIDTH = 6;
    localparam CLK_PERIOD = 10;

    localparam [ADDR_WIDTH-1:0] ADDR_CTRL     = 6'h00;
    localparam [ADDR_WIDTH-1:0] ADDR_DATA_IN  = 6'h04;
    localparam [ADDR_WIDTH-1:0] ADDR_DATA_OUT = 6'h08;
    localparam [ADDR_WIDTH-1:0] ADDR_STATUS   = 6'h0C;

    logic                   ACLK;
    logic                   ARESETn;

    logic [ADDR_WIDTH-1:0]  AWADDR;
    logic                   AWVALID;
    logic                   AWREADY;

    logic [DATA_WIDTH-1:0]  WDATA;
    logic [3:0]             WSTRB;
    logic                   WVALID;
    logic                   WREADY;

    logic [1:0]             BRESP;
    logic                   BVALID;
    logic                   BREADY;

    logic [ADDR_WIDTH-1:0]  ARADDR;
    logic                   ARVALID;
    logic                   ARREADY;

    logic [DATA_WIDTH-1:0]  RDATA;
    logic [1:0]             RRESP;
    logic                   RVALID;
    logic                   RREADY;

    axi_lite_slave #(
        .DATA_WIDTH(DATA_WIDTH),
        .ADDR_WIDTH(ADDR_WIDTH)
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

    initial ACLK = 0;
    always #(CLK_PERIOD/2) ACLK = ~ACLK;

    int pass_count = 0;
    int fail_count = 0;

    task automatic check(
        input string       label,
        input logic [31:0] got,
        input logic [31:0] exp
    );
        if (got === exp) begin
            $display("  PASS  %s : got=0x%08X", label, got);
            pass_count++;
        end else begin
            $display("  FAIL  %s : got=0x%08X  exp=0x%08X", label, got, exp);
            fail_count++;
        end
    endtask

    task automatic axi_write(
        input  logic [ADDR_WIDTH-1:0] addr,
        input  logic [DATA_WIDTH-1:0] data,
        input  logic [3:0]            strb,
        output logic [1:0]            resp
    );
        @(posedge ACLK);
        AWADDR  <= addr;
        AWVALID <= 1'b1;
        WDATA   <= data;
        WSTRB   <= strb;
        WVALID  <= 1'b1;

        do @(posedge ACLK); while (!AWREADY);
        AWVALID <= 1'b0;

        do @(posedge ACLK); while (!WREADY);
        WVALID  <= 1'b0;

        BREADY  <= 1'b1;
        do @(posedge ACLK); while (!BVALID);
        resp    = BRESP;
        @(posedge ACLK);
        BREADY  <= 1'b0;
    endtask

    task automatic axi_read(
        input  logic [ADDR_WIDTH-1:0] addr,
        output logic [DATA_WIDTH-1:0] data,
        output logic [1:0]            resp
    );
        @(posedge ACLK);
        ARADDR  <= addr;
        ARVALID <= 1'b1;

        do @(posedge ACLK); while (!ARREADY);
        ARVALID <= 1'b0;

        RREADY  <= 1'b1;
        do @(posedge ACLK); while (!RVALID);
        data    = RDATA;
        resp    = RRESP;
        @(posedge ACLK);
        RREADY  <= 1'b0;
    endtask

    function automatic logic [31:0] compute_expected(input logic [31:0] val);
        logic [32:0] sum;
        sum = {1'b0, val ^ 32'hA5A5A5A5} + {1'b0, val};
        return (sum & 33'h1_FFFF_FFFF) >> 2;
    endfunction

    logic [31:0] rdata;
    logic [1:0]  rresp, wresp;
    logic [31:0] snap_data_out;
    logic [31:0] snap_status;
    int          poll_count;

    initial begin
        ARESETn <= 1'b0;
        AWADDR  <= '0; AWVALID <= 1'b0;
        WDATA   <= '0; WSTRB   <= 4'hF; WVALID <= 1'b0;
        BREADY  <= 1'b0;
        ARADDR  <= '0; ARVALID <= 1'b0;
        RREADY  <= 1'b0;

        repeat(5) @(posedge ACLK);
        ARESETn <= 1'b1;
        repeat(2) @(posedge ACLK);

        $display("\n[TC1] Reset defaults");
        axi_read(ADDR_CTRL,     rdata, rresp); check("CTRL     reset", rdata, 32'h0);
        axi_read(ADDR_DATA_IN,  rdata, rresp); check("DATA_IN  reset", rdata, 32'h0);
        axi_read(ADDR_DATA_OUT, rdata, rresp); check("DATA_OUT reset", rdata, 32'h0);
        axi_read(ADDR_STATUS,   rdata, rresp); check("STATUS   reset", rdata, 32'h0);

        $display("\n[TC2] Write / read DATA_IN");
        axi_write(ADDR_DATA_IN, 32'hDEAD_BEEF, 4'hF, wresp);
        check("BRESP OKAY",       {30'b0, wresp}, 32'h0);
        axi_read(ADDR_DATA_IN,   rdata, rresp);
        check("DATA_IN readback", rdata, 32'hDEAD_BEEF);

        $display("\n[TC3] Computation — trigger, poll STATUS, read DATA_OUT");
        axi_write(ADDR_DATA_IN, 32'h1234_5678, 4'hF, wresp);
        axi_write(ADDR_CTRL,    32'h0000_0001, 4'hF, wresp);

        poll_count = 0;
        do begin
            axi_read(ADDR_STATUS, rdata, rresp);
            poll_count++;
            if (poll_count > 30) begin
                $display("  FAIL  STATUS.done never set after 30 polls");
                fail_count++;
                disable fork;
            end
        end while (rdata[0] !== 1'b1);
        check("STATUS.done=1", rdata[0:0], 1'b1);
        $display("        done after %0d poll(s)", poll_count);

        $display("\n[TC4] Result correctness");
        axi_read(ADDR_DATA_OUT, rdata, rresp);
        check("DATA_OUT value", rdata, compute_expected(32'h1234_5678));

        $display("\n[TC5] CTRL auto-cleared after start");
        axi_read(ADDR_CTRL, rdata, rresp);
        check("CTRL[0] self-cleared", rdata[0:0], 1'b0);

        $display("\n[TC6] Re-trigger with new DATA_IN");
        axi_write(ADDR_DATA_IN, 32'hFFFF_FFFF, 4'hF, wresp);
        axi_write(ADDR_CTRL,    32'h0000_0001, 4'hF, wresp);

        poll_count = 0;
        do begin
            axi_read(ADDR_STATUS, rdata, rresp);
            poll_count++;
            if (poll_count > 30) begin
                $display("  FAIL  STATUS.done never set on re-trigger");
                fail_count++;
                disable fork;
            end
        end while (rdata[0] !== 1'b1);
        check("STATUS.done=1 (re-trigger)", rdata[0:0], 1'b1);
        axi_read(ADDR_DATA_OUT, rdata, rresp);
        check("DATA_OUT re-trigger value", rdata, compute_expected(32'hFFFF_FFFF));

        $display("\n[TC7] RO register write protection");
        axi_read(ADDR_DATA_OUT, snap_data_out, rresp);
        axi_read(ADDR_STATUS,   snap_status,   rresp);
        axi_write(ADDR_DATA_OUT, 32'hFFFF_FFFF, 4'hF, wresp);
        axi_write(ADDR_STATUS,   32'hFFFF_FFFF, 4'hF, wresp);
        axi_read(ADDR_DATA_OUT, rdata, rresp);
        check("DATA_OUT unchanged", rdata, snap_data_out);
        axi_read(ADDR_STATUS, rdata, rresp);
        check("STATUS   unchanged", rdata, snap_status);

        $display("\n[TC8] Back-to-back writes");
        axi_write(ADDR_DATA_IN, 32'hAAAA_AAAA, 4'hF, wresp);
        axi_write(ADDR_DATA_IN, 32'h5555_5555, 4'hF, wresp);
        axi_read(ADDR_DATA_IN, rdata, rresp);
        check("DATA_IN final value", rdata, 32'h5555_5555);

        $display("\n[TC9] Back-to-back reads");
        axi_write(ADDR_DATA_IN, 32'hCAFE_F00D, 4'hF, wresp);
        axi_read(ADDR_DATA_IN, rdata, rresp); check("BBR read 1",    rdata, 32'hCAFE_F00D);
        axi_read(ADDR_DATA_IN, rdata, rresp); check("BBR read 2",    rdata, 32'hCAFE_F00D);
        axi_read(ADDR_CTRL,    rdata, rresp); check("BBR read 3 CTRL", rdata, 32'h0);

        $display("\n[TC10] Byte-strobe low byte only");
        axi_write(ADDR_DATA_IN, 32'hFFFF_FFFF, 4'hF, wresp);
        axi_write(ADDR_DATA_IN, 32'h0000_00AB, 4'h1, wresp);
        axi_read(ADDR_DATA_IN, rdata, rresp);
        check("Low byte only updated", rdata, 32'hFFFF_FFAB);

        $display("\n[TC11] Byte-strobe high byte only");
        axi_write(ADDR_DATA_IN, 32'h0000_0000, 4'hF, wresp);
        axi_write(ADDR_DATA_IN, 32'hCD000000,  4'h8, wresp);
        axi_read(ADDR_DATA_IN, rdata, rresp);
        check("High byte only updated", rdata, 32'hCD00_0000);

        $display("\n[TC12] Unmapped address returns SLVERR");
        axi_read(6'h3C, rdata, rresp);
        check("RRESP=SLVERR", {30'b0, rresp}, 32'h2);
        check("RDATA=0",      rdata,           32'h0);

        $display("\n[TC13] STATUS cleared when new start issued");
        axi_write(ADDR_DATA_IN, 32'h0000_0001, 4'hF, wresp);
        axi_write(ADDR_CTRL,    32'h0000_0001, 4'hF, wresp);
        poll_count = 0;
        do begin
            axi_read(ADDR_STATUS, rdata, rresp);
            poll_count++;
            if (poll_count > 30) begin
                $display("  FAIL  STATUS.done never set (TC13)");
                fail_count++;
                disable fork;
            end
        end while (rdata[0] !== 1'b1);
        axi_write(ADDR_DATA_IN, 32'h0000_0002, 4'hF, wresp);
        axi_write(ADDR_CTRL,    32'h0000_0001, 4'hF, wresp);
        axi_read(ADDR_STATUS, rdata, rresp);
        check("STATUS cleared on new start", rdata[0:0], 1'b0);

        repeat(4) @(posedge ACLK);
        $display("\n========================================");
        $display("  Results : %0d PASSED  /  %0d FAILED", pass_count, fail_count);
        $display("========================================\n");
        if (fail_count == 0)
            $display("ALL TESTS PASSED");
        else
            $display("SOME TESTS FAILED — review log above");

        $finish;
    end

    initial begin
        #(CLK_PERIOD * 20_000);
        $display("ERROR: simulation timeout");
        $finish;
    end

endmodule