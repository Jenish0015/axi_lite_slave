from __future__ import annotations

import os
from pathlib import Path

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge
from cocotb_tools.runner import get_runner

# ---------------------------------------------------------------------------
# Register map
# ---------------------------------------------------------------------------
ADDR_CTRL       = 0x00
ADDR_DATA_IN    = 0x04
ADDR_DATA_OUT   = 0x08
ADDR_STATUS     = 0x0C
ADDR_SCRATCH    = 0x10
ADDR_IRQ_STATUS = 0x14

RESP_OKAY   = 0b00
RESP_SLVERR = 0b10

CTRL_START  = (1 << 0)
CTRL_ACC_EN = (1 << 1)
CTRL_IRQ_EN = (1 << 2)


# ---------------------------------------------------------------------------
# AXI-Lite helpers
# ---------------------------------------------------------------------------

async def axi_write(dut, addr, data, strb=0xF):
    await RisingEdge(dut.ACLK)
    dut.AWADDR.value  = addr
    dut.AWVALID.value = 1
    dut.WDATA.value   = data
    dut.WSTRB.value   = strb
    dut.WVALID.value  = 1

    while True:
        await RisingEdge(dut.ACLK)
        if dut.AWREADY.value == 1:
            break
    dut.AWVALID.value = 0

    while True:
        if dut.WREADY.value == 1:
            break
        await RisingEdge(dut.ACLK)
    dut.WVALID.value = 0

    dut.BREADY.value = 1
    while True:
        await RisingEdge(dut.ACLK)
        if dut.BVALID.value == 1:
            break
    bresp = int(dut.BRESP.value)
    await RisingEdge(dut.ACLK)
    dut.BREADY.value = 0
    return bresp


async def axi_read(dut, addr):
    await RisingEdge(dut.ACLK)
    dut.ARADDR.value  = addr
    dut.ARVALID.value = 1

    while True:
        await RisingEdge(dut.ACLK)
        if dut.ARREADY.value == 1:
            break
    dut.ARVALID.value = 0

    dut.RREADY.value = 1
    while True:
        if dut.RVALID.value == 1:
            break
        await RisingEdge(dut.ACLK)
    rdata = int(dut.RDATA.value)
    rresp = int(dut.RRESP.value)
    await RisingEdge(dut.ACLK)
    dut.RREADY.value = 0
    return rdata, rresp


async def reset_dut(dut, cycles=6):
    dut.ARESETn.value = 0
    dut.AWADDR.value  = 0;  dut.AWVALID.value = 0
    dut.WDATA.value   = 0;  dut.WSTRB.value   = 0xF; dut.WVALID.value = 0
    dut.BREADY.value  = 0
    dut.ARADDR.value  = 0;  dut.ARVALID.value = 0
    dut.RREADY.value  = 0
    for _ in range(cycles):
        await RisingEdge(dut.ACLK)
    dut.ARESETn.value = 1
    await RisingEdge(dut.ACLK)
    await RisingEdge(dut.ACLK)


async def wait_done(dut, timeout=60):
    """Poll STATUS until done bit set. STATUS[0] is read-to-clear so
    the first read that sees it high also clears it."""
    for i in range(timeout):
        rdata, _ = await axi_read(dut, ADDR_STATUS)
        if rdata & 1:
            return i + 1
    raise AssertionError("STATUS.done never set within timeout")


def compute_result(val: int) -> int:
    xor_val = val ^ 0xA5A5A5A5
    total   = (xor_val + val) & 0x1_FFFF_FFFF
    return (total >> 2) & 0xFFFF_FFFF


# ---------------------------------------------------------------------------
# Test 1 — Reset defaults and basic register access
# ---------------------------------------------------------------------------
@cocotb.test()
async def test_axi_lite_write_read(dut):
    """All registers reset to 0; RW regs work; RO regs protected; SLVERR."""
    clock = Clock(dut.ACLK, 10, unit="ns")
    clock.start(start_high=False)
    await reset_dut(dut)

    # All registers must default to 0 after reset
    for addr, name in [
        (ADDR_CTRL,       "CTRL"),
        (ADDR_DATA_IN,    "DATA_IN"),
        (ADDR_DATA_OUT,   "DATA_OUT"),
        (ADDR_STATUS,     "STATUS"),
        (ADDR_SCRATCH,    "SCRATCH"),
        (ADDR_IRQ_STATUS, "IRQ_STATUS"),
    ]:
        rdata, rresp = await axi_read(dut, addr)
        assert rresp == RESP_OKAY, f"{name}: bad RRESP after reset"
        assert rdata == 0,         f"{name}: expected 0 after reset, got 0x{rdata:08X}"

    # DATA_IN write/readback
    await axi_write(dut, ADDR_DATA_IN, 0xDEAD_BEEF)
    rdata, _ = await axi_read(dut, ADDR_DATA_IN)
    assert rdata == 0xDEAD_BEEF, f"DATA_IN readback: got 0x{rdata:08X}"

    # SCRATCH write/readback
    await axi_write(dut, ADDR_SCRATCH, 0x1234_5678)
    rdata, _ = await axi_read(dut, ADDR_SCRATCH)
    assert rdata == 0x1234_5678, f"SCRATCH readback: got 0x{rdata:08X}"

    # DATA_OUT, STATUS, IRQ_STATUS are read-only
    await axi_write(dut, ADDR_DATA_OUT,   0xFFFF_FFFF)
    await axi_write(dut, ADDR_STATUS,     0xFFFF_FFFF)
    await axi_write(dut, ADDR_IRQ_STATUS, 0xFFFF_FFFF)
    rdata, _ = await axi_read(dut, ADDR_DATA_OUT)
    assert rdata == 0, "DATA_OUT should be read-only"

    # Unmapped address → SLVERR
    rdata, rresp = await axi_read(dut, 0x3C)
    assert rresp == RESP_SLVERR, f"Expected SLVERR for unmapped read, got {rresp}"
    assert rdata == 0,           "Expected RDATA=0 for unmapped read"

    # CTRL upper bits [31:3] are RAZ/WI
    await axi_write(dut, ADDR_CTRL, 0x0000_00FF)
    rdata, _ = await axi_read(dut, ADDR_CTRL)
    assert (rdata & 0xFFFF_FFF8) == 0, \
        f"CTRL upper bits should be RAZ/WI, got 0x{rdata:08X}"


# ---------------------------------------------------------------------------
# Test 2 — Reset clears all state
# ---------------------------------------------------------------------------
@cocotb.test()
async def test_axi_lite_reset(dut):
    """Re-applying reset clears all registers including SCRATCH and DATA_OUT."""
    clock = Clock(dut.ACLK, 10, unit="ns")
    clock.start(start_high=False)
    await reset_dut(dut)

    await axi_write(dut, ADDR_DATA_IN, 0xCAFE_F00D)
    await axi_write(dut, ADDR_SCRATCH, 0xBEEF_CAFE)
    await axi_write(dut, ADDR_CTRL,    CTRL_START)
    for _ in range(8):
        await RisingEdge(dut.ACLK)

    # Re-apply reset
    dut.ARESETn.value = 0
    for _ in range(5):
        await RisingEdge(dut.ACLK)
    dut.ARESETn.value = 1
    await RisingEdge(dut.ACLK)
    await RisingEdge(dut.ACLK)

    for addr, name in [
        (ADDR_CTRL,       "CTRL"),
        (ADDR_DATA_IN,    "DATA_IN"),
        (ADDR_DATA_OUT,   "DATA_OUT"),
        (ADDR_SCRATCH,    "SCRATCH"),
        (ADDR_IRQ_STATUS, "IRQ_STATUS"),
    ]:
        rdata, _ = await axi_read(dut, addr)
        assert rdata == 0, f"{name} not cleared after reset: got 0x{rdata:08X}"

    rdata, _ = await axi_read(dut, ADDR_STATUS)
    assert rdata == 0, f"STATUS not cleared after reset: got 0x{rdata:08X}"


# ---------------------------------------------------------------------------
# Test 3 — 3-cycle pipeline, STATUS read-to-clear, CTRL self-clear
# ---------------------------------------------------------------------------
@cocotb.test()
async def test_axi_lite_multiple_operations(dut):
    """Pipeline result correct; STATUS.done is read-to-clear (not level);
    CTRL[0] self-clears; multiple sequential operations."""
    clock = Clock(dut.ACLK, 10, unit="ns")
    clock.start(start_high=False)
    await reset_dut(dut)

    test_vectors = [
        0x0000_0000,
        0xFFFF_FFFF,
        0x1234_5678,
        0xA5A5_A5A5,
        0x0000_0001,
        0x8000_0000,
    ]

    for val in test_vectors:
        await axi_write(dut, ADDR_DATA_IN, val)
        await axi_write(dut, ADDR_CTRL, CTRL_START)

        # wait_done consumes the done bit (read-to-clear)
        await wait_done(dut, timeout=60)

        # Verify DATA_OUT
        rdata, _ = await axi_read(dut, ADDR_DATA_OUT)
        exp = compute_result(val)
        assert rdata == exp, \
            f"DATA_IN=0x{val:08X}: DATA_OUT=0x{rdata:08X}, expected 0x{exp:08X}"

        # STATUS.done must now be 0 (was cleared by wait_done read)
        rdata, _ = await axi_read(dut, ADDR_STATUS)
        assert (rdata & 1) == 0, \
            f"STATUS.done should be cleared after read, got 0x{rdata:08X}"

        # CTRL[0] self-cleared
        rdata, _ = await axi_read(dut, ADDR_CTRL)
        assert (rdata & 1) == 0, \
            f"CTRL[0] should self-clear, got 0x{rdata:08X}"


# ---------------------------------------------------------------------------
# Test 4 — Accumulator, IRQ, byte strobes, back-to-back
# ---------------------------------------------------------------------------
@cocotb.test()
async def test_axi_lite_back_to_back(dut):
    """acc_en accumulates; IRQ latches on done and clears on read;
    byte strobes; back-to-back read/write consistency."""
    clock = Clock(dut.ACLK, 10, unit="ns")
    clock.start(start_high=False)
    await reset_dut(dut)

    # ---- Accumulator mode: two triggers ----
    await axi_write(dut, ADDR_DATA_IN, 0x0000_0010)
    await axi_write(dut, ADDR_CTRL, CTRL_START | CTRL_ACC_EN | CTRL_IRQ_EN)
    await wait_done(dut)

    first_result = compute_result(0x0000_0010)
    rdata, _ = await axi_read(dut, ADDR_DATA_OUT)
    assert rdata == first_result, \
        f"1st acc trigger: expected 0x{first_result:08X}, got 0x{rdata:08X}"

    await axi_write(dut, ADDR_DATA_IN, 0x0000_0020)
    await axi_write(dut, ADDR_CTRL, CTRL_START | CTRL_ACC_EN | CTRL_IRQ_EN)
    await wait_done(dut)

    second_result = compute_result(0x0000_0020)
    expected_acc  = (first_result + second_result) & 0xFFFF_FFFF
    rdata, _ = await axi_read(dut, ADDR_DATA_OUT)
    assert rdata == expected_acc, \
        f"2nd acc trigger: expected 0x{expected_acc:08X}, got 0x{rdata:08X}"

    # ---- IRQ_STATUS read-to-clear ----
    rdata, _ = await axi_read(dut, ADDR_IRQ_STATUS)
    assert (rdata & 1) == 1, \
        f"IRQ_STATUS[0] should be set after irq_en trigger, got 0x{rdata:08X}"
    rdata, _ = await axi_read(dut, ADDR_IRQ_STATUS)
    assert (rdata & 1) == 0, \
        f"IRQ_STATUS[0] should clear after read, got 0x{rdata:08X}"

    # ---- Non-accumulating mode overwrites ----
    await axi_write(dut, ADDR_DATA_IN, 0x0000_0030)
    await axi_write(dut, ADDR_CTRL, CTRL_START)
    await wait_done(dut)

    overwrite_result = compute_result(0x0000_0030)
    rdata, _ = await axi_read(dut, ADDR_DATA_OUT)
    assert rdata == overwrite_result, \
        f"Normal mode after acc: expected 0x{overwrite_result:08X}, got 0x{rdata:08X}"

    # ---- Byte strobe on SCRATCH ----
    await axi_write(dut, ADDR_SCRATCH, 0xFFFF_FFFF, strb=0xF)
    await axi_write(dut, ADDR_SCRATCH, 0x0000_00AB, strb=0x1)
    rdata, _ = await axi_read(dut, ADDR_SCRATCH)
    assert rdata == 0xFFFF_FFAB, \
        f"SCRATCH low-byte strobe: expected 0xFFFFFFAB, got 0x{rdata:08X}"

    await axi_write(dut, ADDR_SCRATCH, 0x0000_0000, strb=0xF)
    await axi_write(dut, ADDR_SCRATCH, 0xCD00_0000, strb=0x8)
    rdata, _ = await axi_read(dut, ADDR_SCRATCH)
    assert rdata == 0xCD00_0000, \
        f"SCRATCH high-byte strobe: expected 0xCD000000, got 0x{rdata:08X}"

    # ---- Byte strobe on DATA_IN ----
    await axi_write(dut, ADDR_DATA_IN, 0xFFFF_FFFF, strb=0xF)
    await axi_write(dut, ADDR_DATA_IN, 0x0000_00EF, strb=0x1)
    rdata, _ = await axi_read(dut, ADDR_DATA_IN)
    assert rdata == 0xFFFF_FFEF, \
        f"DATA_IN low-byte strobe: expected 0xFFFFFFEF, got 0x{rdata:08X}"

    # ---- Back-to-back reads consistent ----
    await axi_write(dut, ADDR_SCRATCH, 0xABCD_1234, strb=0xF)
    r1, _ = await axi_read(dut, ADDR_SCRATCH)
    r2, _ = await axi_read(dut, ADDR_SCRATCH)
    assert r1 == r2 == 0xABCD_1234, \
        f"Back-to-back reads inconsistent: r1=0x{r1:08X}, r2=0x{r2:08X}"

    # ---- Back-to-back writes: last wins ----
    await axi_write(dut, ADDR_SCRATCH, 0xAAAA_AAAA)
    await axi_write(dut, ADDR_SCRATCH, 0x5555_5555)
    rdata, _ = await axi_read(dut, ADDR_SCRATCH)
    assert rdata == 0x5555_5555, \
        f"Back-to-back writes: expected 0x55555555, got 0x{rdata:08X}"


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------
def test_axi_lite_slave_hidden_runner():
    sim = os.getenv("SIM", "icarus")
    proj_path = Path(__file__).resolve().parent.parent
    sources = [proj_path / "sources" / "axi_lite_slave.sv"]

    runner = get_runner(sim)
    runner.build(
        sources=sources,
        hdl_toplevel="axi_lite_slave",
        always=True,
    )
    runner.test(
        hdl_toplevel="axi_lite_slave",
        test_module="test_axi_lite_slave_hidden",
    )