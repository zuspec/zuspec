"""05_bus_arbitration_chain.py — Multi-Level Inference Chain

Demonstrates Phase P3 structural inference: a depth-2 (3-action) inference
chain where the runtime recursively selects producers to satisfy a chain of
unbound flow-object inputs.

**Scenario**:
  A bus protocol stack with three sequential actions:
    1. ResetBus    — produces BusResetState (the bus is reset)
    2. ArbitrateBus — consumes BusResetState; produces BusArbitratedState
    3. SendPacket  — consumes BusArbitratedState; sends data

  The user writes only:
    await do(SendPacket)

  The inference engine:
    1. Sees SendPacket.arb_state (BusArbitratedState) is unbound
    2. Finds ArbitrateBus in the ICL as a producer for BusArbitratedState
    3. Recurses: ArbitrateBus.reset_state (BusResetState) is also unbound
    4. Finds ResetBus in the ICL as a producer for BusResetState
    5. Inserts: ResetBus → ArbitrateBus → SendPacket

**PSS LRM reference**: §5.3.3 (state flow objects), Annex E §E.3 (recursive ICL)

**Expected output**:
  [ResetBus    ] resetting bus...
  [ArbitrateBus] bus arbitrated, winner=<N>
  [SendPacket  ] sending packet: dest=0x..., len=..., using arb state from bus <N>
  ✓ Execution order: ResetBus → ArbitrateBus → SendPacket

**How to run**:
  python examples/inference/05_bus_arbitration_chain.py
  python examples/inference/05_bus_arbitration_chain.py --seed 42
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent /
                       "packages/zuspec-dataclasses/src"))

import zuspec.dataclasses as zdc
from zuspec.dataclasses.rt.scenario_runner import ScenarioRunner


# ---------------------------------------------------------------------------
# Component
# ---------------------------------------------------------------------------

@zdc.dataclass
class BusComp(zdc.Component):
    """Bus subsystem component."""
    pass


# ---------------------------------------------------------------------------
# Flow objects: bus protocol state machine
# ---------------------------------------------------------------------------

@zdc.dataclass
class BusResetState(zdc.Buffer):
    """State after the bus has been reset and is idle."""
    bus_id: int = zdc.rand()


@zdc.dataclass
class BusArbitratedState(zdc.Buffer):
    """State after bus arbitration: a winner has been selected."""
    bus_id: int = zdc.rand()
    winner: int = zdc.rand()


# ---------------------------------------------------------------------------
# Actions
# ---------------------------------------------------------------------------

_exec_order: list = []   # capture execution order for validation


@zdc.dataclass
class ResetBus(zdc.Action[BusComp]):
    """Resets the bus to idle state. Produces BusResetState."""
    reset_state: BusResetState = zdc.flow_output()

    async def body(self):
        _exec_order.append("ResetBus")
        print(f"  [ResetBus    ] resetting bus id={self.reset_state.bus_id}...")


@zdc.dataclass
class ArbitrateBus(zdc.Action[BusComp]):
    """Arbitrates bus access: consumes BusResetState, produces BusArbitratedState."""
    reset_state: BusResetState     = zdc.flow_input()
    arb_state:   BusArbitratedState = zdc.flow_output()

    async def body(self):
        _exec_order.append("ArbitrateBus")
        print(f"  [ArbitrateBus] bus arbitrated, winner={self.arb_state.winner}")


@zdc.dataclass
class SendPacket(zdc.Action[BusComp]):
    """Sends a packet: consumes BusArbitratedState (bus must be arbitrated first)."""
    arb_state: BusArbitratedState = zdc.flow_input()
    dest:      int = zdc.rand()
    length:    int = zdc.rand()

    async def body(self):
        _exec_order.append("SendPacket")
        print(f"  [SendPacket  ] sending to dest=0x{self.dest:04x}"
              f"  len={self.length}"
              f"  (bus winner={self.arb_state.winner})")


# ---------------------------------------------------------------------------
# Scenario: only SendPacket listed — full chain inferred
# ---------------------------------------------------------------------------

@zdc.dataclass
class BusArbitrationScenario(zdc.Action[BusComp]):
    """User writes one line; inference inserts ResetBus and ArbitrateBus."""

    async def activity(self):
        await zdc.do(SendPacket)   # depth-2 chain inferred automatically


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main(seed: int = 42) -> None:
    print(f"\nBus Arbitration Chain  (seed={seed})")
    print("=" * 58)
    print("  Activity:  await do(SendPacket)")
    print("  Inferred:  ResetBus → ArbitrateBus → SendPacket")
    print("-" * 58)

    _exec_order.clear()
    comp = BusComp()
    runner = ScenarioRunner(comp, seed=seed)
    asyncio.run(runner.run(BusArbitrationScenario))

    print("-" * 58)

    expected = ["ResetBus", "ArbitrateBus", "SendPacket"]
    actual = _exec_order

    if actual == expected:
        print(f"  ✓ Execution order: {' → '.join(actual)}")
    else:
        print(f"  ✗ Expected {expected}, got {actual}")
        raise AssertionError(f"Execution order wrong: {actual}")
    print()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Bus Arbitration Chain Demo")
    parser.add_argument("--seed", type=int, default=42, help="RNG seed")
    args = parser.parse_args()
    main(seed=args.seed)
