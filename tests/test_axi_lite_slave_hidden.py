from __future__ import annotations
import os
from pathlib import Path
import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge


async def axi_write(dut, addr, data):
    dut.AWADDR.value = addr
    dut.AWVALID.value = 1
    dut.WVALID.value = 0
    dut.BREADY.value = 1
    for _ in range(50):
        await RisingEdge(dut.ACLK)
        if dut.AWREADY.value == 1:
            break
    dut.AWVALID.value = 0
    await RisingEdge(dut.ACLK)
    dut.WDATA.value = data
    dut.WSTRB.value = 0xF
    dut.WVALID.value = 1
    for _ in range(50):
        await RisingEdge(dut.ACLK)
        if dut.WREADY.value == 1:
            break
    dut.WVALID.value = 0
    await RisingEdge(dut.ACLK)
    for _ in range(50):
        await RisingEdge(dut.ACLK)
        if dut.BVALID.value == 1:
            break
    dut.BREADY.value = 0
    await RisingEdge(dut.ACLK)


async def axi_read(dut, addr):
    dut.ARADDR.value = addr
    dut.ARVALID.value = 1
    dut.RREADY.value = 1
    for _ in range(50):
        await RisingEdge(dut.ACLK)
        if dut.ARREADY.value == 1:
            break
    dut.ARVALID.value = 0
    data = 0
    for _ in range(50):
        if dut.RVALID.value == 1:
            data = dut.RDATA.value.integer
            break
        await RisingEdge(dut.ACLK)
    dut.RREADY.value = 0
    await RisingEdge(dut.ACLK)
    return data


async def reset_dut(dut):
    dut.ARESETn.value = 0
    dut.AWVALID.value = 0
    dut.WVALID.value = 0
    dut.BREADY.value = 0
    dut.ARVALID.value = 0
    dut.RREADY.value = 0
    dut.WSTRB.value = 0xF
    dut.AWADDR.value = 0
    dut.WDATA.value = 0
    dut.ARADDR.value = 0
    for _ in range(5):
        await RisingEdge(dut.ACLK)
    dut.ARESETn.value = 1
    for _ in range(3):
        await RisingEdge(dut.ACLK)


def compute_expected(val):
    return (((val ^ 0xA5A5A5A5) + val) & 0xFFFFFFFF) >> 2


@cocotb.test()
async def test_axi_lite_write_read(dut):
    clock = Clock(dut.ACLK, 10, units="ns")
    clock.start(start_high=False)
    await reset_dut(dut)
    await axi_write(dut, 0x04, 5)
    await axi_write(dut, 0x00, 1)
    for _ in range(50):
        await RisingEdge(dut.ACLK)
    result = await axi_read(dut, 0x08)
    expected = compute_expected(5)
    assert result == expected, f"DATA_OUT was {result}, expected {expected}"


@cocotb.test()
async def test_axi_lite_reset(dut):
    clock = Clock(dut.ACLK, 10, units="ns")
    clock.start(start_high=False)
    await reset_dut(dut)
    ctrl = await axi_read(dut, 0x00)
    assert ctrl == 0, f"CTRL reg should be 0 after reset, got {ctrl}"
    status = await axi_read(dut, 0x0C)
    assert status == 0, f"STATUS reg should be 0 after reset, got {status}"


@cocotb.test()
async def test_axi_lite_multiple_operations(dut):
    clock = Clock(dut.ACLK, 10, units="ns")
    clock.start(start_high=False)
    await reset_dut(dut)
    for input_val in [1, 15, 100, 255]:
        await axi_write(dut, 0x00, 0)
        for _ in range(5):
            await RisingEdge(dut.ACLK)
        await axi_write(dut, 0x04, input_val)
        await axi_write(dut, 0x00, 1)
        for _ in range(50):
            await RisingEdge(dut.ACLK)
        result = await axi_read(dut, 0x08)
        expected = compute_expected(input_val)
        assert result == expected, f"For input {input_val}: got {result}, expected {expected}"


@cocotb.test()
async def test_axi_lite_back_to_back(dut):
    clock = Clock(dut.ACLK, 10, units="ns")
    clock.start(start_high=False)
    await reset_dut(dut)
    await axi_write(dut, 0x04, 7)
    await axi_write(dut, 0x00, 1)
    for _ in range(50):
        await RisingEdge(dut.ACLK)
    result1 = await axi_read(dut, 0x08)
    expected1 = compute_expected(7)
    assert result1 == expected1, f"First op: got {result1}, expected {expected1}"
    await axi_write(dut, 0x00, 0)
    for _ in range(5):
        await RisingEdge(dut.ACLK)
    await axi_write(dut, 0x04, 20)
    await axi_write(dut, 0x00, 1)
    for _ in range(50):
        await RisingEdge(dut.ACLK)
    result2 = await axi_read(dut, 0x08)
    expected2 = compute_expected(20)
    assert result2 == expected2, f"Second op: got {result2}, expected {expected2}"
    await axi_write(dut, 0x00, 0)
    for _ in range(5):
        await RisingEdge(dut.ACLK)
    status = await axi_read(dut, 0x0C)
    assert status == 0, f"Status should be 0 after ctrl clear, got {status}"


def test_axi_lite_slave_hidden_runner():
    sim = os.getenv("SIM", "icarus")
    proj_path = Path(__file__).resolve().parent.parent
    sources = [proj_path / "sources/axi_lite_slave.sv"]
    from cocotb_tools.runner import get_runner
    runner = get_runner(sim)
    runner.build(sources=sources, hdl_toplevel="axi_lite_slave", always=True)
    runner.test(hdl_toplevel="axi_lite_slave", test_module="test_axi_lite_slave_hidden")