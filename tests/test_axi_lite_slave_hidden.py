@cocotb.test()
async def test_axi_lite_torture_hard_fail_most_rtl(dut):
    """
    Hard combined stress:
    - strict AW/W/B sequencing and backpressure
    - strict AR/R backpressure and data hold
    - WSTRB masking on CTRL and DATA_IN
    - retrigger semantics with CTRL edge-only launch
    - fixed pipeline latency (32 cycles) with no early DATA_OUT update
    - reset mid-flight cancels pending result
    """
    from cocotb.clock import Clock
    from cocotb.triggers import RisingEdge

    PIPE_CYC = 32

    def exp(v):
        return (((v ^ 0xA5A5A5A5) + v) & 0xFFFFFFFF) >> 2

    async def wait(n):
        for _ in range(n):
            await RisingEdge(dut.ACLK)

    async def reset():
        dut.ARESETn.value = 0
        dut.AWVALID.value = 0
        dut.WVALID.value = 0
        dut.BREADY.value = 0
        dut.ARVALID.value = 0
        dut.RREADY.value = 0
        dut.AWADDR.value = 0
        dut.WDATA.value = 0
        dut.WSTRB.value = 0xF
        dut.ARADDR.value = 0
        await wait(5)
        dut.ARESETn.value = 1
        await wait(3)

    async def wr(addr, data, wstrb=0xF):
        dut.AWADDR.value = addr
        dut.AWVALID.value = 1
        for _ in range(50):
            await RisingEdge(dut.ACLK)
            if dut.AWREADY.value == 1:
                break
        dut.AWVALID.value = 0
        await RisingEdge(dut.ACLK)

        dut.WDATA.value = data
        dut.WSTRB.value = wstrb
        dut.WVALID.value = 1
        for _ in range(50):
            await RisingEdge(dut.ACLK)
            if dut.WREADY.value == 1:
                break
        dut.WVALID.value = 0
        await RisingEdge(dut.ACLK)

        dut.BREADY.value = 1
        for _ in range(50):
            await RisingEdge(dut.ACLK)
            if dut.BVALID.value == 1:
                break
        bresp = dut.BRESP.value.integer
        dut.BREADY.value = 0
        await RisingEdge(dut.ACLK)
        return bresp

    async def rd(addr):
        dut.ARADDR.value = addr
        dut.ARVALID.value = 1
        dut.RREADY.value = 1
        for _ in range(50):
            await RisingEdge(dut.ACLK)
            if dut.ARREADY.value == 1:
                break
        dut.ARVALID.value = 0
        for _ in range(50):
            if dut.RVALID.value == 1:
                d = dut.RDATA.value.integer
                r = dut.RRESP.value.integer
                dut.RREADY.value = 0
                await RisingEdge(dut.ACLK)
                return d, r
            await RisingEdge(dut.ACLK)
        dut.RREADY.value = 0
        await RisingEdge(dut.ACLK)
        return 0, 0

    clock = Clock(dut.ACLK, 10, units="ns")
    clock.start(start_high=False)
    await reset()

    # 1) CTRL write masked off: must not trigger
    await wr(0x04, 0x11223344, 0xF)
    await wr(0x00, 0x00000001, 0x0)  # masked bit0
    await wait(20)
    st, _ = await rd(0x0C)
    out, _ = await rd(0x08)
    assert st == 0 and out == 0, f"Masked CTRL wrongly triggered: STATUS={st}, DATA_OUT={out}"

    # 2) Trigger run #1
    await wr(0x00, 0x1, 0x1)

    # 3) Mid-pipeline DATA_OUT must remain old value
    await wait(PIPE_CYC // 3)
    early, _ = await rd(0x08)
    assert early == 0, f"DATA_OUT updated too early: {early}"

    # 4) Retrigger before completion: clear ctrl, new DATA_IN, set ctrl again
    await wr(0x00, 0x0, 0x1)
    await wr(0x04, 0x0000002A, 0xF)
    await wr(0x00, 0x1, 0x1)

    # 5) Read-channel hold check (RREADY low)
    dut.RREADY.value = 0
    dut.ARADDR.value = 0x08
    dut.ARVALID.value = 1
    for _ in range(50):
        await RisingEdge(dut.ACLK)
        if dut.ARREADY.value == 1:
            break
    dut.ARVALID.value = 0
    for _ in range(50):
        await RisingEdge(dut.ACLK)
        if dut.RVALID.value == 1:
            break
    hdata = dut.RDATA.value.integer
    hresp = dut.RRESP.value.integer
    for _ in range(8):
        await RisingEdge(dut.ACLK)
        assert dut.RVALID.value == 1, "RVALID dropped while RREADY=0"
        assert dut.RDATA.value.integer == hdata, "RDATA changed while held"
        assert dut.RRESP.value.integer == hresp, "RRESP changed while held"
    dut.RREADY.value = 1
    await RisingEdge(dut.ACLK)
    assert dut.RVALID.value == 0, "RVALID did not clear after handshake"
    dut.RREADY.value = 0

    # 6) Write-response hold check (BREADY low)
    dut.BREADY.value = 0
    dut.AWADDR.value = 0x04
    dut.AWVALID.value = 1
    for _ in range(50):
        await RisingEdge(dut.ACLK)
        if dut.AWREADY.value == 1:
            break
    dut.AWVALID.value = 0
    await RisingEdge(dut.ACLK)
    dut.WDATA.value = 0xDEADBEEF
    dut.WSTRB.value = 0xF
    dut.WVALID.value = 1
    for _ in range(50):
        await RisingEdge(dut.ACLK)
        if dut.WREADY.value == 1:
            break
    dut.WVALID.value = 0
    for _ in range(50):
        await RisingEdge(dut.ACLK)
        if dut.BVALID.value == 1:
            break
    hb = dut.BRESP.value.integer
    for _ in range(8):
        await RisingEdge(dut.ACLK)
        assert dut.BVALID.value == 1, "BVALID dropped while BREADY=0"
        assert dut.BRESP.value.integer == hb, "BRESP changed while held"
        assert dut.AWREADY.value == 0, "AWREADY should stay low while write response pending"
    dut.BREADY.value = 1
    await RisingEdge(dut.ACLK)
    assert dut.BVALID.value == 0, "BVALID did not clear after handshake"
    assert dut.AWREADY.value == 1, "AWREADY did not reassert after B handshake"
    dut.BREADY.value = 0

    # 7) Reset mid-flight cancellation
    await wr(0x04, 0x00000055, 0xF)
    await wr(0x00, 0x1, 0x1)
    await wait(PIPE_CYC // 4)
    await reset()
    await wait(PIPE_CYC + 10)
    dout, _ = await rd(0x08)
    stat, _ = await rd(0x0C)
    ctrl, _ = await rd(0x00)
    assert dout == 0 and stat == 0 and ctrl == 0, f"Reset cancellation failed dout={dout} st={stat} ctrl={ctrl}"

    # 8) Final clean run should compute correctly with full latency
    await wr(0x04, 0x0000002A, 0xF)
    await wr(0x00, 0x1, 0x1)
    await wait(PIPE_CYC + 12)
    final, rr = await rd(0x08)
    assert rr == 0, f"RRESP expected OKAY, got {rr}"
    assert final == exp(0x2A), f"Final result wrong: got {final}, expected {exp(0x2A)}"