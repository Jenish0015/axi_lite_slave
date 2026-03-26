

from __future__ import annotations
import os
import random
from pathlib import Path
import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, ClockCycles, ReadOnly
from cocotb_tools.runner import get_runner

LANGUAGE = os.getenv("HDL_TOPLEVEL_LANG", "verilog").lower().strip()

# Helper addresses
ADDR_FIFO_PUSH   = 0x00
ADDR_FIFO_STATUS = 0x04
ADDR_FIFO_POP    = 0x08
ADDR_FIFO_SUM    = 0x0C
ADDR_INVALID     = 0x14

@cocotb.test()
async def test_axi_lite_fifo_hard(dut):
    """
    Highly rigorous test for AXI-Lite FIFO challenge:
    1. Independent AW and W handshakes
    2. WSTRB padding rules
    3. Push / Pop correctly updating STATUS and SUM
    4. Edge cases: Full FIFO, Empty FIFO
    5. Backpressure and exact-once popping logic
    """

    clock = Clock(dut.ACLK, 10, units="ns")
    clock.start(start_high=False)
    
    # Reset
    dut.ARESETn.value = 0
    dut.AWVALID.value = 0
    dut.WVALID.value  = 0
    dut.BREADY.value  = 0
    dut.ARVALID.value = 0
    dut.RREADY.value  = 0
    dut.AWADDR.value  = 0
    dut.WDATA.value   = 0
    dut.WSTRB.value   = 0xF
    dut.ARADDR.value  = 0
    
    await ClockCycles(dut.ACLK, 5)
    dut.ARESETn.value = 1
    await ClockCycles(dut.ACLK, 5)

    # -------------------------------------------------------------
    # Custom AXI-Lite Drivers to force edge cases
    # -------------------------------------------------------------
    AXI_TIMEOUT_CYCLES = 100

    async def write_custom(addr, data, wstrb=0xF, aw_delay=0, w_delay=0, b_delay=0):
        # We drive AW and W independently
        # AW task
        async def drive_aw():
            if aw_delay > 0:
                await ClockCycles(dut.ACLK, aw_delay)
            dut.AWADDR.value = addr
            dut.AWVALID.value = 1
            for _ in range(AXI_TIMEOUT_CYCLES):
                await ReadOnly()
                if dut.AWREADY.value == 1:
                    await RisingEdge(dut.ACLK)
                    dut.AWVALID.value = 0
                    break
                await RisingEdge(dut.ACLK)
            else:
                dut.AWVALID.value = 0
                assert False, "Timeout waiting for AWREADY"
        
        # W task
        async def drive_w():
            if w_delay > 0:
                await ClockCycles(dut.ACLK, w_delay)
            dut.WDATA.value = data
            dut.WSTRB.value = wstrb
            dut.WVALID.value = 1
            for _ in range(AXI_TIMEOUT_CYCLES):
                await ReadOnly()
                if dut.WREADY.value == 1:
                    await RisingEdge(dut.ACLK)
                    dut.WVALID.value = 0
                    break
                await RisingEdge(dut.ACLK)
            else:
                dut.WVALID.value = 0
                assert False, "Timeout waiting for WREADY"

        await cocotb.start(drive_aw())
        await cocotb.start(drive_w())
        
        if b_delay > 0:
            await ClockCycles(dut.ACLK, b_delay)
        dut.BREADY.value = 1
        bresp = 0
        for _ in range(AXI_TIMEOUT_CYCLES):
            await ReadOnly()
            if dut.BVALID.value == 1:
                bresp = dut.BRESP.value.integer
                await RisingEdge(dut.ACLK)
                dut.BREADY.value = 0
                break
            await RisingEdge(dut.ACLK)
        else:
            dut.BREADY.value = 0
            assert False, "Timeout waiting for BVALID"
        return bresp

    async def read_custom(addr, r_delay=0):
        dut.ARADDR.value = addr
        dut.ARVALID.value = 1
        for _ in range(AXI_TIMEOUT_CYCLES):
            await ReadOnly()
            if dut.ARREADY.value == 1:
                await RisingEdge(dut.ACLK)
                dut.ARVALID.value = 0
                break
            await RisingEdge(dut.ACLK)
        else:
            dut.ARVALID.value = 0
            assert False, "Timeout waiting for ARREADY"
        
        if r_delay > 0:
            await ClockCycles(dut.ACLK, r_delay)
        dut.RREADY.value = 1
        rdata, rresp = 0, 0
        for _ in range(AXI_TIMEOUT_CYCLES):
            await ReadOnly()
            if dut.RVALID.value == 1:
                rdata = dut.RDATA.value.integer
                rresp = dut.RRESP.value.integer
                await RisingEdge(dut.ACLK)
                dut.RREADY.value = 0
                break
            await RisingEdge(dut.ACLK)
        else:
            dut.RREADY.value = 0
            assert False, "Timeout waiting for RVALID"
        return rdata, rresp

    # =============================================================
    # Test 1: Empty FIFO behaviors
    # =============================================================
    v1_sum, r1_sum = await read_custom(ADDR_FIFO_SUM)
    assert r1_sum == 0 and v1_sum == 0, f"Empty SUM should be 0, got {v1_sum}"

    v1_pop, r1_pop = await read_custom(ADDR_FIFO_POP)
    assert r1_pop == 2, f"Pop from empty should return SLVERR (2), got {r1_pop}"
    assert v1_pop == 0xDEADBEEF, f"Pop from empty should return 0xDEADBEEF, got {hex(v1_pop)}"

    v1_status, r1_status = await read_custom(ADDR_FIFO_STATUS)
    assert r1_status == 0, f"STATUS read should be OKAY, got {r1_status}"
    # Empty flag is bit 5 (0x20)
    assert (v1_status & 0x20) != 0, f"Empty flag not set in STATUS, got {hex(v1_status)}"
    assert (v1_status & 0x1F) == 0, f"Count not 0 in STATUS, got {hex(v1_status)}"

    # =============================================================
    # Test 2: WSTRB Padding AND Decoupled Writes
    # =============================================================
    # Write W before AW by 2 cycles
    bresp = await write_custom(ADDR_FIFO_PUSH, 0xAABBCCDD, wstrb=0x5, aw_delay=2, w_delay=0)
    assert bresp == 0, f"Push should succeed (OKAY), got {bresp}"

    # Verify STATUS count is 1
    v2_status, _ = await read_custom(ADDR_FIFO_STATUS)
    count = v2_status & 0xF
    assert count == 1, f"Count should be 1, got {count}"
    assert (v2_status & 0x20) == 0, "Empty flag should be cleared"

    v2_sum, _ = await read_custom(ADDR_FIFO_SUM)
    assert v2_sum == 0x00BB00DD, f"Sum should be padded WSTRB val, got {hex(v2_sum)}"

    # =============================================================
    # Test 3: Fill FIFO entirely
    # =============================================================
    # Already 1 item. Push 7 more.
    for i in range(7):
        bresp = await write_custom(ADDR_FIFO_PUSH, i+1, wstrb=0xF)
        assert bresp == 0, f"Push {i} failed"

    # Push to full FIFO
    bresp2 = await write_custom(ADDR_FIFO_PUSH, 0x99999999, wstrb=0xF)
    assert bresp2 == 2, f"Full push should SLVERR, got {bresp2}"

    # Verify STATUS is FULL
    v3_status, _ = await read_custom(ADDR_FIFO_STATUS)
    assert (v3_status & 0x10) != 0, f"Full flag not set in STATUS, got {hex(v3_status)}"
    assert (v3_status & 0xF) == 8, f"Count should be 8, got {v3_status & 0xF}"

    # SUM should be 0x00BB00DD + 1 + 2 + 3 + 4 + 5 + 6 + 7 = 0x00BB00DD + 28
    v3_sum, _ = await read_custom(ADDR_FIFO_SUM)
    assert v3_sum == 0x00BB00DD + 28, f"SUM incorrect, got {hex(v3_sum)}"

    # =============================================================
    # Test 4: Verify single POP despite backpressure
    # =============================================================
    # Delay RREADY by 5 cycles to mimic backpressure
    popped, rresp = await read_custom(ADDR_FIFO_POP, r_delay=5)
    assert rresp == 0, "Pop returned non-OKAY"
    assert popped == 0x00BB00DD, f"Oldest element should be 0x00BB00DD, got {hex(popped)}"

    v4_status, _ = await read_custom(ADDR_FIFO_STATUS)
    assert (v4_status & 0xF) == 7, f"Count should decrease to 7, got {v4_status & 0xF}"
    assert (v4_status & 0x10) == 0, "Full flag should be cleared"

    # =============================================================
    # Test 5: Verify Unmapped Addresses Returns SLVERR
    # =============================================================
    bresp3 = await write_custom(ADDR_INVALID, 0x12345678, wstrb=0xF)
    assert bresp3 == 2, f"Unmapped write should SLVERR, got {bresp3}"

    v5_unmap, r5_unmap = await read_custom(ADDR_INVALID)
    assert r5_unmap == 2, f"Unmapped read should SLVERR, got {r5_unmap}"

    # Empty the rest of the FIFO
    for i in range(7):
        popped_val, ret_code = await read_custom(ADDR_FIFO_POP)
        assert ret_code == 0
        assert popped_val == i+1, f"Popped value {popped_val} mismatch expected {i+1}"

    v6_status, _ = await read_custom(ADDR_FIFO_STATUS)
    assert (v6_status & 0xF) == 0, f"FIFO should be empty, got count = {v6_status & 0xF}"
    assert (v6_status & 0x20) != 0, "Empty flag should be set"

def test_axi_lite_slave_hidden_runner():
    proj_path = Path(__file__).resolve().parent.parent
    sources = [proj_path / "golden/axi_lite_slave.sv"]
    
    runner = get_runner(os.getenv("SIM", "icarus"))
    runner.build(
        sources=sources,
        hdl_toplevel="axi_lite_slave",
        always=True,
    )
    runner.test(hdl_toplevel="axi_lite_slave", test_module="test_axi_lite_slave_hidden")