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
ADDR_CTRL        = 0x00
ADDR_DATA_IN     = 0x04
ADDR_DATA_OUT    = 0x08
ADDR_STATUS      = 0x0C
ADDR_SCRATCH     = 0x10
ADDR_IRQ_STATUS  = 0x14
ADDR_TRIGGER_CNT = 0x18

RESP_OKAY   = 0b00
RESP_SLVERR = 0b10

CTRL_START   = (1 << 0)
CTRL_ACC_EN  = (1 << 1)
CTRL_IRQ_EN  = (1 << 2)
CTRL_CNT_CLR = (1 << 3)


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


async def wait_done(dut, timeout=80):
    """Poll STATUS until done. STATUS[0] is read-to-clear."""
    for i in range(timeout):
        rdata, _ = await axi_read(dut, ADDR_STATUS)
        if rdata & 1:
            return rdata   # return full status so caller can check ovf
    raise AssertionError("STATUS.done never set within timeout")


def compute_result(val: int, scratch: int) -> int:
    """4-stage pipeline result with scratch XOR finaliser."""
    xor_val = val ^ 0xA5A5A5A5
    total   = (xor_val + val) & 0x1_FFFF_FFFF
    shifted = (total >> 2) & 0xFFFF_FFFF
    return shifted ^ (scratch & 0x0000_FFFF)   # XOR with lower 16 bits of scratch


def sat_add(a: int, b: int) -> tuple[int, bool]:
    """Saturating 32-bit add. Returns (result, overflow)."""
    s = a + b
    if s > 0xFFFF_FFFF:
        return 0xFFFF_FFFF, True
    return s, False


# ---------------------------------------------------------------------------
# Test 1 — Reset defaults, basic RW, RO protection, SLVERR, RAZ/WI
# ---------------------------------------------------------------------------
@cocotb.test()
async def test_axi_lite_write_read(dut):
    """Register defaults; DATA_IN shadow readback; RO regs; SLVERR; RAZ/WI."""
    clock = Clock(dut.ACLK, 10, unit="ns")
    clock.start(start_high=False)
    await reset_dut(dut)

    # All registers default 0
    for addr, name in [
        (ADDR_CTRL,        "CTRL"),
        (ADDR_DATA_IN,     "DATA_IN"),
        (ADDR_DATA_OUT,    "DATA_OUT"),
        (ADDR_STATUS,      "STATUS"),
        (ADDR_SCRATCH,     "SCRATCH"),
        (ADDR_IRQ_STATUS,  "IRQ_STATUS"),
        (ADDR_TRIGGER_CNT, "TRIGGER_CNT"),
    ]:
        rdata, rresp = await axi_read(dut, addr)
        assert rresp == RESP_OKAY, f"{name}: bad RRESP after reset"
        assert rdata == 0,         f"{name}: expected 0, got 0x{rdata:08X}"

    # DATA_IN write → shadow, read back shadow
    await axi_write(dut, ADDR_DATA_IN, 0xDEAD_BEEF)
    rdata, _ = await axi_read(dut, ADDR_DATA_IN)
    assert rdata == 0xDEAD_BEEF, \
        f"DATA_IN shadow readback: got 0x{rdata:08X}"

    # SCRATCH write/readback
    await axi_write(dut, ADDR_SCRATCH, 0x1234_5678)
    rdata, _ = await axi_read(dut, ADDR_SCRATCH)
    assert rdata == 0x1234_5678, f"SCRATCH: got 0x{rdata:08X}"

    # RO registers — writes silently ignored
    await axi_write(dut, ADDR_DATA_OUT,    0xFFFF_FFFF)
    await axi_write(dut, ADDR_STATUS,      0xFFFF_FFFF)
    await axi_write(dut, ADDR_IRQ_STATUS,  0xFFFF_FFFF)
    await axi_write(dut, ADDR_TRIGGER_CNT, 0xFFFF_FFFF)
    rdata, _ = await axi_read(dut, ADDR_DATA_OUT)
    assert rdata == 0, "DATA_OUT should be RO"
    rdata, _ = await axi_read(dut, ADDR_TRIGGER_CNT)
    assert rdata == 0, "TRIGGER_CNT should be RO"

    # Unmapped → SLVERR
    rdata, rresp = await axi_read(dut, 0x3C)
    assert rresp == RESP_SLVERR, f"Expected SLVERR, got {rresp}"
    assert rdata == 0,           "Expected RDATA=0 for unmapped"

    # CTRL[31:4] RAZ/WI — write 0xFF, upper bits must read 0
    await axi_write(dut, ADDR_CTRL, 0x0000_00FF)
    rdata, _ = await axi_read(dut, ADDR_CTRL)
    assert (rdata & 0xFFFF_FFF0) == 0, \
        f"CTRL upper bits should be RAZ/WI, got 0x{rdata:08X}"


# ---------------------------------------------------------------------------
# Test 2 — Reset clears everything
# ---------------------------------------------------------------------------
@cocotb.test()
async def test_axi_lite_reset(dut):
    """Re-applying reset clears all registers and pipeline state."""
    clock = Clock(dut.ACLK, 10, unit="ns")
    clock.start(start_high=False)
    await reset_dut(dut)

    await axi_write(dut, ADDR_DATA_IN, 0xCAFE_F00D)
    await axi_write(dut, ADDR_SCRATCH, 0xBEEF_CAFE)
    await axi_write(dut, ADDR_CTRL, CTRL_START)
    for _ in range(10):
        await RisingEdge(dut.ACLK)

    dut.ARESETn.value = 0
    for _ in range(5):
        await RisingEdge(dut.ACLK)
    dut.ARESETn.value = 1
    await RisingEdge(dut.ACLK)
    await RisingEdge(dut.ACLK)

    for addr, name in [
        (ADDR_CTRL,        "CTRL"),
        (ADDR_DATA_IN,     "DATA_IN"),
        (ADDR_DATA_OUT,    "DATA_OUT"),
        (ADDR_SCRATCH,     "SCRATCH"),
        (ADDR_IRQ_STATUS,  "IRQ_STATUS"),
        (ADDR_TRIGGER_CNT, "TRIGGER_CNT"),
    ]:
        rdata, _ = await axi_read(dut, addr)
        assert rdata == 0, f"{name} not cleared after reset: 0x{rdata:08X}"

    rdata, _ = await axi_read(dut, ADDR_STATUS)
    assert rdata == 0, f"STATUS not cleared after reset: 0x{rdata:08X}"


# ---------------------------------------------------------------------------
# Test 3 — 4-cycle pipeline, scratch XOR finaliser, STATUS read-to-clear,
#           TRIGGER_CNT, CTRL[3] counter clear
# ---------------------------------------------------------------------------
@cocotb.test()
async def test_axi_lite_multiple_operations(dut):
    """Pipeline result correct with scratch XOR; STATUS RTC; TRIGGER_CNT counts."""
    clock = Clock(dut.ACLK, 10, unit="ns")
    clock.start(start_high=False)
    await reset_dut(dut)

    # Set scratch to a known value — it affects the result
    scratch_val = 0x0000_ABCD
    await axi_write(dut, ADDR_SCRATCH, scratch_val)

    test_vectors = [
        0x0000_0000,
        0xFFFF_FFFF,
        0x1234_5678,
        0xA5A5_A5A5,
        0x0000_0001,
        0x8000_0000,
    ]

    for idx, val in enumerate(test_vectors):
        await axi_write(dut, ADDR_DATA_IN, val)
        await axi_write(dut, ADDR_CTRL, CTRL_START)

        # wait_done consumes done bit (RTC)
        await wait_done(dut, timeout=80)

        # Verify DATA_OUT
        rdata, _ = await axi_read(dut, ADDR_DATA_OUT)
        exp = compute_result(val, scratch_val)
        assert rdata == exp, \
            f"val=0x{val:08X} scratch=0x{scratch_val:08X}: " \
            f"DATA_OUT=0x{rdata:08X}, expected 0x{exp:08X}"

        # STATUS.done must now be 0 (was consumed by wait_done)
        rdata, _ = await axi_read(dut, ADDR_STATUS)
        assert (rdata & 1) == 0, \
            f"STATUS.done should be 0 after RTC read, got 0x{rdata:08X}"

        # CTRL[0] self-cleared
        rdata, _ = await axi_read(dut, ADDR_CTRL)
        assert (rdata & 1) == 0, \
            f"CTRL[0] should self-clear, got 0x{rdata:08X}"

        # TRIGGER_CNT increments each trigger
        rdata, _ = await axi_read(dut, ADDR_TRIGGER_CNT)
        assert rdata == idx + 1, \
            f"TRIGGER_CNT: expected {idx+1}, got {rdata}"

    # CTRL[3] clears TRIGGER_CNT
    await axi_write(dut, ADDR_CTRL, CTRL_CNT_CLR)
    rdata, _ = await axi_read(dut, ADDR_TRIGGER_CNT)
    assert rdata == 0, f"TRIGGER_CNT should be 0 after CNT_CLR, got {rdata}"

    # Verify scratch changes affect result
    new_scratch = 0x0000_1234
    await axi_write(dut, ADDR_SCRATCH, new_scratch)
    await axi_write(dut, ADDR_DATA_IN, 0x1234_5678)
    await axi_write(dut, ADDR_CTRL, CTRL_START)
    await wait_done(dut)
    rdata, _ = await axi_read(dut, ADDR_DATA_OUT)
    exp = compute_result(0x1234_5678, new_scratch)
    assert rdata == exp, \
        f"Scratch XOR finaliser: expected 0x{exp:08X}, got 0x{rdata:08X}"


# ---------------------------------------------------------------------------
# Test 4 — Saturating accumulator, IRQ, shadow buffering, byte strobes
# ---------------------------------------------------------------------------
@cocotb.test()
async def test_axi_lite_back_to_back(dut):
    """Saturating acc; ovf flag; IRQ RTC; shadow buffer stalls DATA_IN write;
    byte strobes on SCRATCH/DATA_IN; back-to-back reads/writes."""
    clock = Clock(dut.ACLK, 10, unit="ns")
    clock.start(start_high=False)
    await reset_dut(dut)

    scratch_val = 0x0000_0000   # zero scratch so XOR doesn't change result

    # ---- Saturating accumulator ----
    # Pick a value whose result is large, then add until overflow
    big_val = 0xFFFF_FFFF
    exp_first = compute_result(big_val, scratch_val)

    await axi_write(dut, ADDR_DATA_IN, big_val)
    await axi_write(dut, ADDR_CTRL, CTRL_START | CTRL_ACC_EN)
    await wait_done(dut)

    rdata, _ = await axi_read(dut, ADDR_DATA_OUT)
    assert rdata == exp_first, \
        f"First acc trigger: expected 0x{exp_first:08X}, got 0x{rdata:08X}"

    # Trigger again with same value — should saturate since exp_first is large
    await axi_write(dut, ADDR_DATA_IN, big_val)
    await axi_write(dut, ADDR_CTRL, CTRL_START | CTRL_ACC_EN)
    status = await wait_done(dut)

    exp_acc, overflowed = sat_add(exp_first, exp_first)
    rdata, _ = await axi_read(dut, ADDR_DATA_OUT)
    assert rdata == exp_acc, \
        f"Saturating acc: expected 0x{exp_acc:08X}, got 0x{rdata:08X}"

    if overflowed:
        # ovf flag should have been set — it was consumed by wait_done's STATUS read
        # so check it was included in the status returned by wait_done
        assert (status & 0x4) != 0, \
            f"STATUS.ovf should be set on saturation, status=0x{status:08X}"

    # ---- IRQ read-to-clear ----
    await axi_write(dut, ADDR_DATA_IN, 0x0000_0001)
    await axi_write(dut, ADDR_CTRL, CTRL_START | CTRL_IRQ_EN)
    await wait_done(dut)

    rdata, _ = await axi_read(dut, ADDR_IRQ_STATUS)
    assert (rdata & 1) == 1, \
        f"IRQ_STATUS[0] should be set, got 0x{rdata:08X}"
    rdata, _ = await axi_read(dut, ADDR_IRQ_STATUS)
    assert (rdata & 1) == 0, \
        f"IRQ_STATUS[0] should clear after read, got 0x{rdata:08X}"

    # ---- acc_en sticky — persists without re-writing CTRL ----
    # Write acc_en=1 once, trigger 3 times, result must keep accumulating
    await axi_write(dut, ADDR_CTRL, CTRL_ACC_EN)   # set acc_en, no start
    # Reset DATA_OUT by doing a non-acc trigger first
    await axi_write(dut, ADDR_CTRL, CTRL_START)     # acc_en already set → still acc
    # Instead, re-reset via hardware reset trick: just check acc persists
    # Simplest: do two triggers, each reading back and verifying accumulation

    # First: clear acc by doing a reset
    dut.ARESETn.value = 0
    for _ in range(4): await RisingEdge(dut.ACLK)
    dut.ARESETn.value = 1
    for _ in range(2): await RisingEdge(dut.ACLK)

    val_a = 0x0000_0100
    val_b = 0x0000_0200
    await axi_write(dut, ADDR_DATA_IN, val_a)
    await axi_write(dut, ADDR_CTRL, CTRL_START | CTRL_ACC_EN)
    await wait_done(dut)
    result_a = compute_result(val_a, 0)
    rdata, _ = await axi_read(dut, ADDR_DATA_OUT)
    assert rdata == result_a, \
        f"Sticky acc trig1: expected 0x{result_a:08X}, got 0x{rdata:08X}"

    # Trigger again — acc_en sticky so just write start, not acc_en again
    await axi_write(dut, ADDR_DATA_IN, val_b)
    await axi_write(dut, ADDR_CTRL, CTRL_START)   # acc_en stays from CTRL register
    await wait_done(dut)
    result_b    = compute_result(val_b, 0)
    expected, _ = sat_add(result_a, result_b)
    rdata, _ = await axi_read(dut, ADDR_DATA_OUT)
    assert rdata == expected, \
        f"Sticky acc trig2: expected 0x{expected:08X}, got 0x{rdata:08X}"

    # ---- Shadow buffer: DATA_IN write while busy must stall then apply ----
    # Trigger a computation, immediately try to write DATA_IN (should stall),
    # then verify the new DATA_IN is used on the NEXT trigger
    await axi_write(dut, ADDR_CTRL, 0x00)  # clear acc_en
    dut.ARESETn.value = 0
    for _ in range(4): await RisingEdge(dut.ACLK)
    dut.ARESETn.value = 1
    for _ in range(2): await RisingEdge(dut.ACLK)

    # Trigger with val=0x1111_1111
    await axi_write(dut, ADDR_DATA_IN, 0x1111_1111)
    await axi_write(dut, ADDR_CTRL, CTRL_START)
    # Immediately write new DATA_IN while pipeline is busy (will stall)
    await axi_write(dut, ADDR_DATA_IN, 0x2222_2222)
    await wait_done(dut)

    # DATA_OUT should be result of 0x1111_1111 (pipeline used pre-write value)
    rdata, _ = await axi_read(dut, ADDR_DATA_OUT)
    exp = compute_result(0x1111_1111, 0)
    assert rdata == exp, \
        f"Shadow: pipeline should use old DATA_IN, expected 0x{exp:08X}, got 0x{rdata:08X}"

    # Shadow readback should show 0x2222_2222
    rdata, _ = await axi_read(dut, ADDR_DATA_IN)
    assert rdata == 0x2222_2222, \
        f"Shadow readback: expected 0x22222222, got 0x{rdata:08X}"

    # Next trigger uses the new value
    await axi_write(dut, ADDR_CTRL, CTRL_START)
    await wait_done(dut)
    rdata, _ = await axi_read(dut, ADDR_DATA_OUT)
    exp = compute_result(0x2222_2222, 0)
    assert rdata == exp, \
        f"After shadow apply: expected 0x{exp:08X}, got 0x{rdata:08X}"

    # ---- Byte strobes on SCRATCH ----
    await axi_write(dut, ADDR_SCRATCH, 0xFFFF_FFFF, strb=0xF)
    await axi_write(dut, ADDR_SCRATCH, 0x0000_00AB, strb=0x1)
    rdata, _ = await axi_read(dut, ADDR_SCRATCH)
    assert rdata == 0xFFFF_FFAB, \
        f"SCRATCH low-byte: expected 0xFFFFFFAB, got 0x{rdata:08X}"

    # ---- Back-to-back reads consistent ----
    await axi_write(dut, ADDR_SCRATCH, 0xABCD_1234, strb=0xF)
    r1, _ = await axi_read(dut, ADDR_SCRATCH)
    r2, _ = await axi_read(dut, ADDR_SCRATCH)
    assert r1 == r2 == 0xABCD_1234, \
        f"Back-to-back reads: r1=0x{r1:08X} r2=0x{r2:08X}"

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
    sources = [proj_path / "golden" / "axi_lite_slave.sv"]

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