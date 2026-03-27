from __future__ import annotations

import os
import random
from pathlib import Path

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import FallingEdge, RisingEdge, Timer
from cocotb_tools.runner import get_runner


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
LANGUAGE = os.getenv("HDL_TOPLEVEL_LANG", "verilog").lower().strip()


def _lfsr_step(state: int) -> int:
    """8-bit LFSR (x^8 + x^6 + x^5 + x^4 + 1) for deterministic hard patterns."""
    bit = ((state >> 7) ^ (state >> 5) ^ (state >> 4) ^ (state >> 3)) & 1
    return ((state << 1) & 0xFF) | bit


# ---------------------------------------------------------------------------
# Test 1 – d propagates to q
# ---------------------------------------------------------------------------
@cocotb.test()
async def dff_simple_test(dut):
    """Test that d propagates to q"""

    # Set initial input value to prevent it from floating
    dut.d.value = 0

    # Create a 10us period clock driver on port `clk`
    clock = Clock(dut.clk, 10, units="us")

    # Start the clock. Start it low to avoid issues on the first RisingEdge
    clock.start(start_high=False)

    # Synchronize with the clock. This will register the initial `d` value
    await RisingEdge(dut.clk)

    expected_val = 0  # Matches initial input value

    for i in range(10):
        val = random.randint(0, 1)
        dut.d.value = val  # Assign the random value val to the input port d
        await RisingEdge(dut.clk)
        assert dut.q.value == expected_val, (
            f"output q was incorrect on the {i}th cycle"
        )
        expected_val = val  # Save random value for next RisingEdge

    # Check the final input on the next clock
    await RisingEdge(dut.clk)
    assert dut.q.value == expected_val, "output q was incorrect on the last cycle"


# ---------------------------------------------------------------------------
# Test 2 – long randomized stream with deterministic seed
# ---------------------------------------------------------------------------
@cocotb.test()
async def dff_long_random_stream_test(dut):
    """Stress test with a long, seeded random stream."""

    rng = random.Random(12345)
    dut.d.value = 0

    clock = Clock(dut.clk, 2, units="us")
    clock.start(start_high=False)

    await RisingEdge(dut.clk)
    expected_val = 0

    for i in range(200):
        next_d = rng.randint(0, 1)
        dut.d.value = next_d
        await RisingEdge(dut.clk)
        assert dut.q.value == expected_val, f"q mismatch at cycle {i}"
        expected_val = next_d

    await RisingEdge(dut.clk)
    assert dut.q.value == expected_val, "q mismatch on final verification edge"


# ---------------------------------------------------------------------------
# Test 3 – q must stay stable between rising edges
# ---------------------------------------------------------------------------
@cocotb.test()
async def dff_midcycle_glitch_stability_test(dut):
    """Toggle d in middle of cycle; q must not change until rising edge."""

    dut.d.value = 0
    clock = Clock(dut.clk, 10, units="us")
    clock.start(start_high=False)

    await RisingEdge(dut.clk)
    baseline_q = int(dut.q.value)

    for i in range(40):
        await FallingEdge(dut.clk)
        dut.d.value = (i & 1)
        await Timer(1, units="us")
        assert int(dut.q.value) == baseline_q, (
            f"q changed between edges at iteration {i}"
        )

        await RisingEdge(dut.clk)
        assert int(dut.q.value) == baseline_q, (
            f"q did not present prior d at iteration {i}"
        )
        baseline_q = (i & 1)


# ---------------------------------------------------------------------------
# Test 4 – rapid edge-to-edge toggling patterns
# ---------------------------------------------------------------------------
@cocotb.test()
async def dff_back_to_back_pattern_test(dut):
    """Use difficult toggle patterns around consecutive edges."""

    patterns = [
        [0, 1, 0, 1, 0, 1, 0, 1],
        [1, 1, 1, 0, 0, 0, 1, 0],
        [0, 0, 1, 1, 0, 1, 1, 0],
    ]

    dut.d.value = 0
    clock = Clock(dut.clk, 4, units="us")
    clock.start(start_high=False)
    await RisingEdge(dut.clk)

    expected_q = 0
    cycle = 0
    for pattern in patterns:
        for bit in pattern:
            dut.d.value = bit
            await RisingEdge(dut.clk)
            assert int(dut.q.value) == expected_q, f"q mismatch at cycle {cycle}"
            expected_q = bit
            cycle += 1

    await RisingEdge(dut.clk)
    assert int(dut.q.value) == expected_q, "q mismatch after pattern completion"


# ---------------------------------------------------------------------------
# Test 5 – deterministic pseudo-random sequence + jittered updates
# ---------------------------------------------------------------------------
@cocotb.test()
async def dff_lfsr_jitter_test(dut):
    """
    Drive a long deterministic sequence while changing d at varied times in-cycle.
    This catches accidental level-sensitive behavior and clock-edge races.
    """

    dut.d.value = 0
    clock = Clock(dut.clk, 8, units="us")
    clock.start(start_high=False)
    await RisingEdge(dut.clk)

    lfsr = 0xA5
    expected_q = 0

    for i in range(128):
        lfsr = _lfsr_step(lfsr)
        next_d = (lfsr >> (i % 8)) & 1

        # Alternate update points: near falling edge vs. near rising edge.
        if i % 2 == 0:
            await FallingEdge(dut.clk)
            await Timer(1, units="us")
        else:
            await FallingEdge(dut.clk)
            await Timer(3, units="us")

        dut.d.value = next_d

        # q must stay stable until rising edge.
        await Timer(1, units="us")
        assert int(dut.q.value) == expected_q, f"q changed early at step {i}"

        await RisingEdge(dut.clk)
        assert int(dut.q.value) == expected_q, f"q mismatch at step {i}"
        expected_q = next_d

    await RisingEdge(dut.clk)
    assert int(dut.q.value) == expected_q, "q mismatch after LFSR stress run"


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------
def test_simple_dff_hidden_runner():
    sim = os.getenv("SIM", "icarus")

    proj_path = Path(__file__).resolve().parent.parent

    sources = [proj_path / "sources/axi_lite_slave.sv"]

    runner = get_runner(sim)
    runner.build(
        sources=sources,
        hdl_toplevel="dff",
        always=True,
    )
    runner.test(hdl_toplevel="dff", test_module="test_axi_lite_slave_hidden")