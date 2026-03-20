"""01_dma_buffer_inference.py — Buffer Inference Showcase

Demonstrates Phase P2 structural inference for Buffer flow objects.

**What this shows**:
  The user writes only ``await do(ReadData)`` inside their scenario activity.
  ReadData has an unbound ``DataBuffer`` input — no explicit WriteData
  predecessor is listed.  The PSS inference engine detects the unbound slot,
  searches the ICL table, selects WriteData as the compatible producer, and
  automatically inserts it as a sequential predecessor before ReadData runs.

**PSS LRM reference**: §5.3.2 (buffer flow objects), §17.1, Annex E (ICL)

**Expected output** (values will vary by seed):
  [WriteData ] body: wrote addr=0x... size=...
  [ReadData  ] body: reading from addr=0x... size=...
  ✓ ReadData received the same buffer that WriteData produced

**How to run**:
  python examples/inference/01_dma_buffer_inference.py
  python examples/inference/01_dma_buffer_inference.py --seed 42
"""
from __future__ import annotations

import argparse
import asyncio
import dataclasses as dc
import sys
from pathlib import Path

# Allow running directly from the repo root
sys.path.insert(0, str(Path(__file__).parent.parent.parent /
                       "packages/zuspec-dataclasses/src"))

import zuspec.dataclasses as zdc
from zuspec.dataclasses.rt.scenario_runner import ScenarioRunner


# ---------------------------------------------------------------------------
# Component
# ---------------------------------------------------------------------------

@zdc.dataclass
class DmaComp(zdc.Component):
    """DMA subsystem component."""
    pass


# ---------------------------------------------------------------------------
# Flow object: DataBuffer
# ---------------------------------------------------------------------------

@zdc.dataclass
class DataBuffer(zdc.Buffer):
    """A DMA data transfer descriptor."""
    addr: int = zdc.rand()
    size: int = zdc.rand()


# ---------------------------------------------------------------------------
# Actions
# ---------------------------------------------------------------------------

@zdc.dataclass
class WriteData(zdc.Action[DmaComp]):
    """Produces a DataBuffer (fills it with data to transfer)."""
    buf: DataBuffer = zdc.flow_output()

    async def body(self):
        # Simulate writing data to the buffer
        print(f"  [WriteData ] body: wrote    addr=0x{self.buf.addr:08x}  "
              f"size={self.buf.size}")


@zdc.dataclass
class ReadData(zdc.Action[DmaComp]):
    """Consumes a DataBuffer (reads data transferred by the producer)."""
    buf: DataBuffer = zdc.flow_input()

    async def body(self):
        print(f"  [ReadData  ] body: reading   addr=0x{self.buf.addr:08x}  "
              f"size={self.buf.size}")


# ---------------------------------------------------------------------------
# Scenario: only ReadData is listed — WriteData is inferred automatically
# ---------------------------------------------------------------------------

@zdc.dataclass
class DmaReadScenario(zdc.Action[DmaComp]):
    """Top-level scenario.

    The user does NOT mention WriteData here.  The inference engine sees that
    ReadData.buf is unbound, finds WriteData in the ICL as a compatible
    producer, and inserts it as a sequential predecessor.
    """

    async def activity(self):
        await zdc.do(ReadData)   # WriteData will be inferred automatically


# ---------------------------------------------------------------------------
# Validation helper
# ---------------------------------------------------------------------------

_write_buf_id: list = []
_read_buf_id: list = []

_original_write_body = WriteData.body
_original_read_body = ReadData.body


async def _capturing_write_body(self):
    _write_buf_id.append(id(self.buf))
    await _original_write_body(self)


async def _capturing_read_body(self):
    _read_buf_id.append(id(self.buf))
    await _original_read_body(self)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main(seed: int = 42) -> None:
    print(f"\nDMA Buffer Inference Demo  (seed={seed})")
    print("=" * 55)
    print("  User's activity:  await do(ReadData)")
    print("  Inferred:         WriteData → ReadData")
    print("-" * 55)

    comp = DmaComp()

    # Patch bodies to capture buffer identity
    WriteData.body = _capturing_write_body
    ReadData.body = _capturing_read_body
    _write_buf_id.clear()
    _read_buf_id.clear()

    try:
        runner = ScenarioRunner(comp, seed=seed)
        asyncio.run(runner.run(DmaReadScenario))
    finally:
        WriteData.body = _original_write_body
        ReadData.body = _original_read_body

    print("-" * 55)

    if _write_buf_id and _read_buf_id:
        same_instance = (_write_buf_id[0] == _read_buf_id[0])
        marker = "✓" if same_instance else "✗"
        print(f"  {marker} ReadData received the same buffer that WriteData produced")
        if not same_instance:
            raise AssertionError("Buffer identity check failed!")
    else:
        raise AssertionError("WriteData or ReadData body was not called!")

    print()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="DMA Buffer Inference Demo")
    parser.add_argument("--seed", type=int, default=42, help="RNG seed")
    args = parser.parse_args()
    main(seed=args.seed)
