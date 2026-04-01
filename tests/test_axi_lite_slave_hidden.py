from __future__ import annotations
import os
from pathlib import Path
import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge
from cocotb_tools.runner import get_runner


PIPE_CYC = 32


def exp(v: int) -> int:
    return (((v ^ 0xA5A5A5A5) + v) & 0xFFFFFFFF) >> 2


async def wait_cycles(dut, n):
    for _ in range(n):
        await RisingEdge(dut.ACLK)


async def reset_dut(dut):
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
    await wait_cycles(dut, 5)
    dut.ARESETn.value = 1
    await wait_cycles(dut, 3)


async def wr(dut, addr, data, wstrb=0xF):
    dut.AWADDR.value = addr
    dut.AWVALID.value = 1
    for _ in range(80):
        await RisingEdge(dut.ACLK)
        if dut.AWREADY.value == 1:
            break
    dut.AWVALID.value = 0
    await RisingEdge(dut.ACLK)

    dut.WDATA.value = data
    dut.WSTRB.value = wstrb
    dut.WVALID.value = 1
    for _ in range(80):
        await RisingEdge(dut.ACLK)
        if dut.WREADY.value == 1:
            break
    dut.WVALID.value = 0
    await RisingEdge(dut.ACLK)

    dut.BREADY.value = 1
    for _ in range(80):
        await RisingEdge(dut.ACLK)
        if dut.BVALID.value == 1:
            break
    bresp = dut.BRESP.value.integer
    dut.BREADY.value = 0
    await RisingEdge(dut.ACLK)
    return bresp


async def rd(dut, addr):
    dut.ARADDR.value = addr
    dut.ARVALID.value = 1
    dut.RREADY.value = 1
    for _ in range(80):
        await RisingEdge(dut.ACLK)
        if dut.ARREADY.value == 1:
            break
    dut.ARVALID.value = 0
    for _ in range(80):
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


@cocotb.test()
async def test_axi_lite_slave_hidden(dut):
    """
    Hard test: interleaves read/write channels, strict AXI hold rules under
    backpressure, WSTRB byte-mask edge cases, retrigger semantics, fixed
    pipeline latency enforcement, and reset mid-flight cancellation.
    """
    clock = Clock(dut.ACLK, 10, unit="ns")
    clock.start(start_high=False)
    await reset_dut(dut)

    # --- A) CTRL masked writes must not trigger ---
    await wr(dut, 0x04, 0x00000011, 0xF)
    await wr(dut, 0x00, 0x00000001, 0x0)  # masked bit0
    await wait_cycles(dut, 20)
    st, _ = await rd(dut, 0x0C)
    out, _ = await rd(dut, 0x08)
    assert st == 0 and out == 0, f"masked CTRL incorrectly triggered: st={st} out={out}"

    # --- B) trigger run #1 then retrigger to run #2 with new operand ---
    await wr(dut, 0x00, 0x1, 0x1)               # run #1 on 0x11
    await wait_cycles(dut, max(2, PIPE_CYC // 4))
    early, _ = await rd(dut, 0x08)
    assert early == 0, f"early DATA_OUT update: {early}"

    await wr(dut, 0x00, 0x0, 0x1)               # clear
    await wr(dut, 0x04, 0x0000002A, 0xF)         # operand for run #2
    await wr(dut, 0x00, 0x1, 0x1)               # run #2

    # --- C) Read-channel hard backpressure/hold ---
    dut.RREADY.value = 0
    dut.ARADDR.value = 0x08
    dut.ARVALID.value = 1
    for _ in range(80):
        await RisingEdge(dut.ACLK)
        if dut.ARREADY.value == 1:
            break
    dut.ARVALID.value = 0

    for _ in range(80):
        await RisingEdge(dut.ACLK)
        if dut.RVALID.value == 1:
            break
    held_rdata = dut.RDATA.value.integer
    held_rresp = dut.RRESP.value.integer
    for _ in range(10):
        await RisingEdge(dut.ACLK)
        assert dut.RVALID.value == 1, "RVALID dropped while RREADY=0"
        assert dut.RDATA.value.integer == held_rdata, "RDATA changed while held"
        assert dut.RRESP.value.integer == held_rresp, "RRESP changed while held"
    dut.RREADY.value = 1
    for _ in range(2):
        await RisingEdge(dut.ACLK)
        if dut.RVALID.value == 0:
            break
    else:
        assert False, "RVALID did not clear after handshake"
    dut.RREADY.value = 0

    # --- D) Write-channel hard backpressure/hold + AWREADY gating ---
    dut.BREADY.value = 0
    dut.AWADDR.value = 0x04
    dut.AWVALID.value = 1
    for _ in range(80):
        await RisingEdge(dut.ACLK)
        if dut.AWREADY.value == 1:
            break
    dut.AWVALID.value = 0
    await RisingEdge(dut.ACLK)

    dut.WDATA.value = 0xDEADBEEF
    dut.WSTRB.value = 0xF
    dut.WVALID.value = 1
    for _ in range(80):
        await RisingEdge(dut.ACLK)
        if dut.WREADY.value == 1:
            break
    dut.WVALID.value = 0

    for _ in range(80):
        await RisingEdge(dut.ACLK)
        if dut.BVALID.value == 1:
            break
    held_bresp = dut.BRESP.value.integer
    for _ in range(10):
        await RisingEdge(dut.ACLK)
        assert dut.BVALID.value == 1, "BVALID dropped while BREADY=0"
        assert dut.BRESP.value.integer == held_bresp, "BRESP changed while held"
        assert dut.AWREADY.value == 0, "AWREADY must stay low while B response pending"
    dut.BREADY.value = 1
    for _ in range(2):
        await RisingEdge(dut.ACLK)
        if dut.BVALID.value == 0:
            break
    else:
        assert False, "BVALID did not clear after handshake"
    for _ in range(2):
        if dut.AWREADY.value == 1:
            break
        await RisingEdge(dut.ACLK)
    else:
        assert False, "AWREADY not restored after B handshake"
    dut.BREADY.value = 0

    # --- E) DATA_IN merge with disjoint WSTRB bytes ---
    await wr(dut, 0x04, 0x11111111, 0xF)
    await wr(dut, 0x04, 0x33445566, 0xC)  # update top two bytes only
    await wait_cycles(dut, max(2, PIPE_CYC // 3))
    mid2, _ = await rd(dut, 0x08)
    assert mid2 == 0, f"DATA_OUT changed before run #2 completion, got {mid2}"

    # --- F) finish run #2; must use latest operand 0x2A ---
    await wait_cycles(dut, PIPE_CYC + 12)
    out2, rr2 = await rd(dut, 0x08)
    assert rr2 == 0, f"RRESP expected OKAY, got {rr2}"
    assert out2 == exp(0x2A), f"run #2 output mismatch, got {out2}, expected {exp(0x2A)}"

    # --- G) reset mid-flight must cancel pending result ---
    await wr(dut, 0x00, 0x0, 0x1)
    await wr(dut, 0x04, 0x00000077, 0xF)
    await wr(dut, 0x00, 0x1, 0x1)
    await wait_cycles(dut, max(2, PIPE_CYC // 4))
    await reset_dut(dut)
    await wait_cycles(dut, PIPE_CYC + 10)
    dout, _ = await rd(dut, 0x08)
    stat, _ = await rd(dut, 0x0C)
    ctrl, _ = await rd(dut, 0x00)
    assert dout == 0 and stat == 0 and ctrl == 0, \
        f"reset cancel failed dout={dout} stat={stat} ctrl={ctrl}"

    # --- H) final clean run using merged DATA_IN from section E ---
    await wr(dut, 0x04, 0x11111111, 0xF)
    await wr(dut, 0x04, 0x33445566, 0xC)
    await wr(dut, 0x00, 0x1, 0x1)
    await wait_cycles(dut, PIPE_CYC + 12)
    outf, rrf = await rd(dut, 0x08)
    assert rrf == 0, f"final RRESP expected OKAY, got {rrf}"
    assert outf == exp(0x33441111), \
        f"final output mismatch got={outf} exp={exp(0x33441111)}"


def test_axi_lite_slave_hidden_runner():
    sim = os.getenv("SIM", "icarus")
    proj_path = Path(__file__).resolve().parent.parent
    # golden/axi_lite_slave.sv is axi_lite_slave_tb only; DUT lives in golden/axi_lite_slave_dut.sv
    sources = [proj_path / "sources/axi_lite_slave_dut.sv"]
    runner = get_runner(sim)
    runner.build(
        sources=sources,
        hdl_toplevel="axi_lite_slave",
        always=True,
    )
    runner.test(hdl_toplevel="axi_lite_slave", test_module="test_axi_lite_slave_hidden")
