from __future__ import annotations

import os
import random
from pathlib import Path

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, ClockCycles
from cocotb_tools.runner import get_runner


# ─────────────────────────────────────────────────────────────────────────────
# Shared AXI-Lite helpers  (mirrors cocotb reference style)
# ─────────────────────────────────────────────────────────────────────────────

async def _reset(dut, cycles: int = 6):
    """Drive all inputs low, assert reset for `cycles` clocks, then release."""
    dut.ARESETn.value = 0
    for sig in (dut.AWVALID, dut.WVALID, dut.BREADY,
                dut.ARVALID, dut.RREADY):
        sig.value = 0
    for sig in (dut.AWADDR, dut.WDATA, dut.ARADDR):
        sig.value = 0
    dut.WSTRB.value = 0
    await ClockCycles(dut.ACLK, cycles)
    dut.ARESETn.value = 1
    await RisingEdge(dut.ACLK)


async def _aw_handshake(dut, addr, timeout=40):
    dut.AWADDR.value  = addr
    dut.AWVALID.value = 1
    for _ in range(timeout):
        await RisingEdge(dut.ACLK)
        if dut.AWREADY.value == 1:
            dut.AWVALID.value = 0
            return
    dut.AWVALID.value = 0
    raise AssertionError(f"AWREADY timeout addr=0x{addr:02X}")


async def _w_handshake(dut, data, strb=0xF, timeout=40):
    dut.WDATA.value  = data
    dut.WSTRB.value  = strb
    dut.WVALID.value = 1
    for _ in range(timeout):
        await RisingEdge(dut.ACLK)
        if dut.WREADY.value == 1:
            dut.WVALID.value = 0
            return
    dut.WVALID.value = 0
    raise AssertionError(f"WREADY timeout data=0x{data:08X}")


async def _b_handshake(dut, timeout=40):
    dut.BREADY.value = 1
    for _ in range(timeout):
        await RisingEdge(dut.ACLK)
        if dut.BVALID.value == 1:
            bresp = int(dut.BRESP.value)
            dut.BREADY.value = 0
            await RisingEdge(dut.ACLK)
            return bresp
    dut.BREADY.value = 0
    raise AssertionError("BVALID timeout")


async def axi_write(dut, addr, data, strb=0xF):
    """Full AXI-Lite write (AW → W → B).  Returns BRESP."""
    await _aw_handshake(dut, addr)
    await _w_handshake(dut, data, strb)
    return await _b_handshake(dut)


async def axi_read(dut, addr, timeout=40):
    """Full AXI-Lite read (AR → R).  Returns (RDATA, RRESP)."""
    dut.ARADDR.value  = addr
    dut.ARVALID.value = 1
    for _ in range(timeout):
        await RisingEdge(dut.ACLK)
        if dut.ARREADY.value == 1:
            dut.ARVALID.value = 0
            break
    else:
        dut.ARVALID.value = 0
        raise AssertionError(f"ARREADY timeout addr=0x{addr:02X}")

    dut.RREADY.value = 1
    for _ in range(timeout):
        await RisingEdge(dut.ACLK)
        if dut.RVALID.value == 1:
            rdata = int(dut.RDATA.value)
            rresp = int(dut.RRESP.value)
            dut.RREADY.value = 0
            await RisingEdge(dut.ACLK)
            return rdata, rresp
    dut.RREADY.value = 0
    raise AssertionError(f"RVALID timeout addr=0x{addr:02X}")


# ─────────────────────────────────────────────────────────────────────────────
# TEST 1 – Reset de-asserts all output valids and clears registers
# ─────────────────────────────────────────────────────────────────────────────
@cocotb.test()
async def test_reset_state(dut):
    """All valid signals must be 0 and writable registers must be 0 after reset."""
    cocotb.start_soon(Clock(dut.ACLK, 10, unit="ns").start(start_high=False))

    dut.ARESETn.value = 0
    for sig in (dut.AWVALID, dut.WVALID, dut.BREADY, dut.ARVALID, dut.RREADY):
        sig.value = 0
    dut.WSTRB.value  = 0
    dut.AWADDR.value = 0
    dut.WDATA.value  = 0
    dut.ARADDR.value = 0
    await ClockCycles(dut.ACLK, 4)

    # Sample while still in reset
    assert int(dut.AWREADY.value) == 0, "AWREADY must be 0 in reset"
    assert int(dut.WREADY.value)  == 0, "WREADY must be 0 in reset"
    assert int(dut.BVALID.value)  == 0, "BVALID must be 0 in reset"
    assert int(dut.RVALID.value)  == 0, "RVALID must be 0 in reset"

    dut.ARESETn.value = 1
    await ClockCycles(dut.ACLK, 3)

    # Registers must read back as zero
    val0, _ = await axi_read(dut, 0x00)
    val4, _ = await axi_read(dut, 0x04)
    assert val0 == 0, f"CTRL not zeroed after reset: 0x{val0:08X}"
    assert val4 == 0, f"DATA_IN not zeroed after reset: 0x{val4:08X}"


# ─────────────────────────────────────────────────────────────────────────────
# TEST 2 – AWREADY asserts within a few cycles of reset release
# ─────────────────────────────────────────────────────────────────────────────
@cocotb.test()
async def test_awready_asserts_after_reset(dut):
    """Slave must signal it is ready to accept an AW beat almost immediately."""
    cocotb.start_soon(Clock(dut.ACLK, 10, unit="ns").start(start_high=False))
    await _reset(dut)

    seen = False
    for _ in range(4):
        await RisingEdge(dut.ACLK)
        if int(dut.AWREADY.value) == 1:
            seen = True
            break
    assert seen, "AWREADY never asserted within 4 cycles of reset release"


# ─────────────────────────────────────────────────────────────────────────────
# TEST 3 – Basic write + readback for CTRL (0x00) and DATA_IN (0x04)
# ─────────────────────────────────────────────────────────────────────────────
@cocotb.test()
async def test_basic_write_readback(dut):
    """Write distinct values to both writable registers and read them back."""
    cocotb.start_soon(Clock(dut.ACLK, 10, unit="ns").start(start_high=False))
    await _reset(dut)

    await axi_write(dut, 0x00, 0xDEADBEEF)
    await axi_write(dut, 0x04, 0xCAFEBABE)

    val, resp = await axi_read(dut, 0x00)
    assert val  == 0xDEADBEEF, f"CTRL wrong: 0x{val:08X}"
    assert resp == 0,          f"RRESP non-zero: {resp}"

    val, resp = await axi_read(dut, 0x04)
    assert val  == 0xCAFEBABE, f"DATA_IN wrong: 0x{val:08X}"
    assert resp == 0,          f"RRESP non-zero: {resp}"


# ─────────────────────────────────────────────────────────────────────────────
# TEST 4 – Byte-lane strobes (WSTRB granularity)
# ─────────────────────────────────────────────────────────────────────────────
@cocotb.test()
async def test_byte_strobes(dut):
    """Each WSTRB bit must gate exactly one byte; other bytes must be unchanged."""
    cocotb.start_soon(Clock(dut.ACLK, 10, unit="ns").start(start_high=False))
    await _reset(dut)

    # Seed CTRL with all-ones
    await axi_write(dut, 0x00, 0xFFFFFFFF, strb=0xF)

    # Overwrite byte-0 only → expect 0xFFFFFF00
    await axi_write(dut, 0x00, 0x00000000, strb=0x1)
    val, _ = await axi_read(dut, 0x00)
    assert val == 0xFFFFFF00, f"Byte-0 strobe fail: 0x{val:08X}"

    # Overwrite byte-2 only → expect 0xFFAAFF00
    await axi_write(dut, 0x00, 0x00AA0000, strb=0x4)
    val, _ = await axi_read(dut, 0x00)
    assert val == 0xFFAAFF00, f"Byte-2 strobe fail: 0x{val:08X}"

    # Overwrite bytes 1+3 only → expect 0xBBAABB00
    await axi_write(dut, 0x00, 0xBB00BB00, strb=0xA)
    val, _ = await axi_read(dut, 0x00)
    assert val == 0xBBAABB00, f"Bytes-1+3 strobe fail: 0x{val:08X}"


# ─────────────────────────────────────────────────────────────────────────────
# TEST 5 – WSTRB = 0x0 must not change any bit (complete NOP)
# ─────────────────────────────────────────────────────────────────────────────
@cocotb.test()
async def test_zero_strobe_nop(dut):
    """A write with WSTRB=0 must leave the register completely unchanged."""
    cocotb.start_soon(Clock(dut.ACLK, 10, unit="ns").start(start_high=False))
    await _reset(dut)

    await axi_write(dut, 0x04, 0x12345678, strb=0xF)
    await axi_write(dut, 0x04, 0xFFFFFFFF, strb=0x0)   # should be NOP

    val, _ = await axi_read(dut, 0x04)
    assert val == 0x12345678, f"Zero-strobe changed register: 0x{val:08X}"


# ─────────────────────────────────────────────────────────────────────────────
# TEST 6 – Unmapped read address must return SLVERR (RRESP == 2'b10)
# ─────────────────────────────────────────────────────────────────────────────
@cocotb.test()
async def test_unmapped_read_slverr(dut):
    """Reads to addresses outside {0x00,0x04,0x08,0x0C} must return SLVERR."""
    cocotb.start_soon(Clock(dut.ACLK, 10, unit="ns").start(start_high=False))
    await _reset(dut)

    for addr in [0x10, 0x14, 0x18, 0x1C, 0x20, 0x3C]:
        val, resp = await axi_read(dut, addr)
        assert resp == 0b10, \
            f"Expected SLVERR for addr=0x{addr:02X}, got RRESP={resp}"
        assert val == 0, \
            f"Expected RDATA=0 for unmapped addr=0x{addr:02X}, got 0x{val:08X}"


# ─────────────────────────────────────────────────────────────────────────────
# TEST 7 – BRESP must be OKAY (2'b00) for every valid-address write
# ─────────────────────────────────────────────────────────────────────────────
@cocotb.test()
async def test_bresp_okay_valid_addresses(dut):
    """Writes to 0x00 and 0x04 must always return BRESP=OKAY."""
    cocotb.start_soon(Clock(dut.ACLK, 10, unit="ns").start(start_high=False))
    await _reset(dut)

    for addr in [0x00, 0x04]:
        for data in [0x00000000, 0xFFFFFFFF, 0xA5A5A5A5, 0x5A5A5A5A]:
            resp = await axi_write(dut, addr, data)
            assert resp == 0b00, \
                f"BRESP={resp:#04b} for addr=0x{addr:02X} data=0x{data:08X}"


# ─────────────────────────────────────────────────────────────────────────────
# TEST 8 – BVALID held high until BREADY (write back-pressure)
# ─────────────────────────────────────────────────────────────────────────────
@cocotb.test()
async def test_bvalid_held_under_backpressure(dut):
    """BVALID must stay asserted across multiple cycles while BREADY=0."""
    cocotb.start_soon(Clock(dut.ACLK, 10, unit="ns").start(start_high=False))
    await _reset(dut)

    # Complete AW + W without asserting BREADY
    await _aw_handshake(dut, 0x00)
    await _w_handshake(dut, 0xABCDABCD)

    # Wait for BVALID
    bvalid_seen = False
    for _ in range(20):
        await RisingEdge(dut.ACLK)
        if int(dut.BVALID.value) == 1:
            bvalid_seen = True
            break
    assert bvalid_seen, "BVALID never asserted"

    # Hold BREADY low for 8 more cycles — BVALID must not drop
    for cycle in range(8):
        await RisingEdge(dut.ACLK)
        assert int(dut.BVALID.value) == 1, \
            f"BVALID dropped at hold-cycle {cycle} without BREADY"

    # Accept response
    dut.BREADY.value = 1
    await RisingEdge(dut.ACLK)
    dut.BREADY.value = 0
    await RisingEdge(dut.ACLK)
    assert int(dut.BVALID.value) == 0, "BVALID still asserted after BREADY"


# ─────────────────────────────────────────────────────────────────────────────
# TEST 9 – RVALID + RDATA stable until RREADY (read back-pressure)
# ─────────────────────────────────────────────────────────────────────────────
@cocotb.test()
async def test_rvalid_rdata_held_under_backpressure(dut):
    """RVALID and RDATA must not change until RREADY is seen."""
    cocotb.start_soon(Clock(dut.ACLK, 10, unit="ns").start(start_high=False))
    await _reset(dut)

    await axi_write(dut, 0x04, 0x5A5A5A5A)

    # Start AR, withhold RREADY
    dut.ARADDR.value  = 0x04
    dut.ARVALID.value = 1
    for _ in range(30):
        await RisingEdge(dut.ACLK)
        if int(dut.ARREADY.value) == 1:
            break
    dut.ARVALID.value = 0

    # Wait for RVALID without granting RREADY
    rvalid_seen = False
    for _ in range(20):
        await RisingEdge(dut.ACLK)
        if int(dut.RVALID.value) == 1:
            rvalid_seen = True
            break
    assert rvalid_seen, "RVALID never asserted"

    captured = int(dut.RDATA.value)
    assert captured == 0x5A5A5A5A, f"RDATA wrong before RREADY: 0x{captured:08X}"

    # Hold 10 cycles — data must be stable
    for hold in range(10):
        await RisingEdge(dut.ACLK)
        assert int(dut.RVALID.value) == 1,         f"RVALID dropped at hold {hold}"
        assert int(dut.RDATA.value)  == 0x5A5A5A5A, "RDATA changed during hold"

    dut.RREADY.value = 1
    await RisingEdge(dut.ACLK)
    dut.RREADY.value = 0
    await RisingEdge(dut.ACLK)
    assert int(dut.RVALID.value) == 0, "RVALID still high after RREADY"


# ─────────────────────────────────────────────────────────────────────────────
# TEST 10 – Mid-transaction reset recovery
# ─────────────────────────────────────────────────────────────────────────────
@cocotb.test()
async def test_mid_transaction_reset_recovery(dut):
    """Reset mid-write must leave slave able to complete a fresh transaction."""
    cocotb.start_soon(Clock(dut.ACLK, 10, unit="ns").start(start_high=False))
    await _reset(dut)

    # Start AW, never complete W
    await _aw_handshake(dut, 0x00)

    # Assert reset during W phase
    dut.ARESETn.value = 0
    await ClockCycles(dut.ACLK, 5)
    dut.ARESETn.value = 1
    await ClockCycles(dut.ACLK, 2)

    # Fresh write must succeed
    resp = await axi_write(dut, 0x00, 0xFEEDFACE)
    assert resp == 0, f"BRESP after mid-tx recovery: {resp}"

    val, _ = await axi_read(dut, 0x00)
    assert val == 0xFEEDFACE, f"Register wrong after recovery: 0x{val:08X}"


# ─────────────────────────────────────────────────────────────────────────────
# TEST 11 – Second reset clears registers written before it
# ─────────────────────────────────────────────────────────────────────────────
@cocotb.test()
async def test_second_reset_clears_registers(dut):
    """A second reset must zero all writable registers."""
    cocotb.start_soon(Clock(dut.ACLK, 10, unit="ns").start(start_high=False))
    await _reset(dut)

    await axi_write(dut, 0x00, 0xDEADBEEF)
    await axi_write(dut, 0x04, 0xCAFEBABE)

    await _reset(dut, cycles=6)   # second reset

    val0, _ = await axi_read(dut, 0x00)
    val4, _ = await axi_read(dut, 0x04)
    assert val0 == 0, f"CTRL not cleared by 2nd reset: 0x{val0:08X}"
    assert val4 == 0, f"DATA_IN not cleared by 2nd reset: 0x{val4:08X}"


# ─────────────────────────────────────────────────────────────────────────────
# TEST 12 – DATA_OUT (0x08) and STATUS (0x0C) must read 0 (no datapath)
# ─────────────────────────────────────────────────────────────────────────────
@cocotb.test()
async def test_data_out_status_read_zero(dut):
    """DATA_OUT and STATUS must stay 0: RTL intentionally omits the datapath."""
    cocotb.start_soon(Clock(dut.ACLK, 10, unit="ns").start(start_high=False))
    await _reset(dut)

    await axi_write(dut, 0x00, 0x00000001)
    await axi_write(dut, 0x04, 0xDEADC0DE)
    await ClockCycles(dut.ACLK, 10)

    val, resp = await axi_read(dut, 0x08)
    assert val  == 0, f"DATA_OUT non-zero: 0x{val:08X}"
    assert resp == 0, f"DATA_OUT RRESP wrong: {resp}"

    val, resp = await axi_read(dut, 0x0C)
    assert val  == 0, f"STATUS non-zero: 0x{val:08X}"
    assert resp == 0, f"STATUS RRESP wrong: {resp}"


# ─────────────────────────────────────────────────────────────────────────────
# TEST 13 – WREADY must de-assert after the W handshake
# ─────────────────────────────────────────────────────────────────────────────
@cocotb.test()
async def test_wready_deasserts_after_handshake(dut):
    """WREADY must go low the cycle after the W handshake (non-pipelined slave)."""
    cocotb.start_soon(Clock(dut.ACLK, 10, unit="ns").start(start_high=False))
    await _reset(dut)

    await _aw_handshake(dut, 0x00)

    dut.WDATA.value  = 0x1
    dut.WSTRB.value  = 0xF
    dut.WVALID.value = 1
    beat_done = False
    for _ in range(20):
        await RisingEdge(dut.ACLK)
        if int(dut.WREADY.value) == 1:
            beat_done = True
            break
    assert beat_done, "WREADY never asserted"
    dut.WVALID.value = 0

    # One cycle later WREADY must be low
    await RisingEdge(dut.ACLK)
    assert int(dut.WREADY.value) == 0, "WREADY still high after W handshake"

    dut.BREADY.value = 1
    await ClockCycles(dut.ACLK, 4)
    dut.BREADY.value = 0


# ─────────────────────────────────────────────────────────────────────────────
# TEST 14 – ARREADY must de-assert after the AR handshake
# ─────────────────────────────────────────────────────────────────────────────
@cocotb.test()
async def test_arready_deasserts_after_handshake(dut):
    """ARREADY must de-assert the cycle after capturing the read address."""
    cocotb.start_soon(Clock(dut.ACLK, 10, unit="ns").start(start_high=False))
    await _reset(dut)

    dut.ARADDR.value  = 0x00
    dut.ARVALID.value = 1
    for _ in range(20):
        await RisingEdge(dut.ACLK)
        if int(dut.ARREADY.value) == 1:
            break

    await RisingEdge(dut.ACLK)
    assert int(dut.ARREADY.value) == 0, \
        "ARREADY still high one cycle after AR handshake"

    dut.ARVALID.value = 0
    dut.RREADY.value  = 1
    await ClockCycles(dut.ACLK, 5)
    dut.RREADY.value  = 0


# ─────────────────────────────────────────────────────────────────────────────
# TEST 15 – Simultaneous AWVALID + WVALID (pipelined presentation)
# ─────────────────────────────────────────────────────────────────────────────
@cocotb.test()
async def test_simultaneous_aw_w_valid(dut):
    """Asserting AWVALID and WVALID together must not cause a deadlock."""
    cocotb.start_soon(Clock(dut.ACLK, 10, unit="ns").start(start_high=False))
    await _reset(dut)

    dut.AWADDR.value  = 0x04
    dut.AWVALID.value = 1
    dut.WDATA.value   = 0xFACEFACE
    dut.WSTRB.value   = 0xF
    dut.WVALID.value  = 1
    dut.BREADY.value  = 1

    bvalid_seen = False
    for _ in range(50):
        await RisingEdge(dut.ACLK)
        if int(dut.BVALID.value) == 1:
            bvalid_seen = True
            break

    dut.AWVALID.value = 0
    dut.WVALID.value  = 0
    dut.BREADY.value  = 0

    assert bvalid_seen, "BVALID never seen with simultaneous AW+W"

    val, _ = await axi_read(dut, 0x04)
    assert val == 0xFACEFACE, f"DATA_IN wrong after simultaneous AW+W: 0x{val:08X}"


# ─────────────────────────────────────────────────────────────────────────────
# TEST 16 – Back-to-back writes with no idle gap
# ─────────────────────────────────────────────────────────────────────────────
@cocotb.test()
async def test_back_to_back_writes(dut):
    """Four consecutive writes with no idle cycle must all commit correctly."""
    cocotb.start_soon(Clock(dut.ACLK, 10, unit="ns").start(start_high=False))
    await _reset(dut)

    seq = [
        (0x00, 0xAAAAAAAA),
        (0x04, 0xBBBBBBBB),
        (0x00, 0x11223344),
        (0x04, 0x55667788),
    ]
    for addr, data in seq:
        resp = await axi_write(dut, addr, data)
        assert resp == 0, f"BRESP={resp} addr=0x{addr:02X}"

    val, _ = await axi_read(dut, 0x00)
    assert val == 0x11223344, f"CTRL wrong: 0x{val:08X}"
    val, _ = await axi_read(dut, 0x04)
    assert val == 0x55667788, f"DATA_IN wrong: 0x{val:08X}"


# ─────────────────────────────────────────────────────────────────────────────
# TEST 17 – Read-after-write with zero idle gap (RAW hazard)
# ─────────────────────────────────────────────────────────────────────────────
@cocotb.test()
async def test_read_after_write_hazard(dut):
    """A read issued immediately after a write must see the updated value."""
    cocotb.start_soon(Clock(dut.ACLK, 10, unit="ns").start(start_high=False))
    await _reset(dut)

    await axi_write(dut, 0x00, 0xDEADC0DE)
    val, resp = await axi_read(dut, 0x00)   # no extra clock gap
    assert val  == 0xDEADC0DE, f"RAW hazard: 0x{val:08X}"
    assert resp == 0


# ─────────────────────────────────────────────────────────────────────────────
# TEST 18 – AWREADY re-asserts after every completed write (no permanent lock)
# ─────────────────────────────────────────────────────────────────────────────
@cocotb.test()
async def test_awready_reasserts_after_each_write(dut):
    """AWREADY must return high between each consecutive write transaction."""
    cocotb.start_soon(Clock(dut.ACLK, 10, unit="ns").start(start_high=False))
    await _reset(dut)

    for i in range(5):
        await axi_write(dut, 0x00, i)
        seen = False
        for _ in range(4):
            await RisingEdge(dut.ACLK)
            if int(dut.AWREADY.value) == 1:
                seen = True
                break
        assert seen, f"AWREADY did not re-assert after write {i}"


# ─────────────────────────────────────────────────────────────────────────────
# TEST 19 – Interleaved reads and writes (alternating channels)
# ─────────────────────────────────────────────────────────────────────────────
@cocotb.test()
async def test_interleaved_read_write(dut):
    """Alternating write/read pairs must always return the latest written value."""
    cocotb.start_soon(Clock(dut.ACLK, 10, unit="ns").start(start_high=False))
    await _reset(dut)

    rng = random.Random(0xBEEF)
    for _ in range(20):
        data = rng.randint(0, 0xFFFF_FFFF)
        await axi_write(dut, 0x00, data)
        val, _ = await axi_read(dut, 0x00)
        assert val == data, \
            f"Interleaved mismatch: wrote 0x{data:08X} read 0x{val:08X}"


# ─────────────────────────────────────────────────────────────────────────────
# TEST 20 – Random stress: 60 writes with random strobes checked by Python model
# ─────────────────────────────────────────────────────────────────────────────
@cocotb.test()
async def test_random_stress(dut):
    """60 random writes with random strobes verified against a cycle-accurate model."""
    cocotb.start_soon(Clock(dut.ACLK, 10, unit="ns").start(start_high=False))
    await _reset(dut)

    rng      = random.Random(0xC0FFEE42)
    expected = {0x00: 0, 0x04: 0}

    for _ in range(60):
        addr = rng.choice([0x00, 0x04])
        data = rng.randint(0, 0xFFFF_FFFF)
        strb = rng.randint(1, 0xF)

        mask = 0
        for bit, byte_shift in enumerate([0, 8, 16, 24]):
            if strb & (1 << bit):
                mask |= 0xFF << byte_shift
        expected[addr] = (expected[addr] & ~mask) | (data & mask)

        await axi_write(dut, addr, data, strb=strb)

    for addr, exp in expected.items():
        val, resp = await axi_read(dut, addr)
        assert resp == 0, f"RRESP={resp} addr=0x{addr:02X}"
        assert val  == exp, \
            f"Stress mismatch addr=0x{addr:02X}: exp=0x{exp:08X} got=0x{val:08X}"


# ─────────────────────────────────────────────────────────────────────────────
# Runner  (mirrors the reference cocotb runner pattern exactly)
# ─────────────────────────────────────────────────────────────────────────────

def test_axi_lite_slave_runner():
    sim       = os.getenv("SIM", "icarus")
    proj_path = Path(__file__).resolve().parent.parent

    sources = [proj_path / "golden" / "axi_lite_slave.v"]

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