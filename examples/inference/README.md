# PSS Inference Examples

These end-to-end examples demonstrate the **structural inference** feature of
the `zuspec-dataclasses` Python runtime.  Each example can be run directly and
prints a short summary of what happened.

## What Is Structural Inference?

When a PSS action has an unbound *flow-input* field (e.g. a `Buffer` it needs
to read), the runtime automatically searches for another action type in the
component that can produce that flow object and inserts it *before* the
consumer in the sequence.  The mechanism is:

1. **ActionRegistry** — discovers every action type reachable from the root
   component.
2. **ICLTable** (Interface-Connection List) — pre-computes which action types
   can satisfy which consumer slots.
3. **StructuralSolver** — performs a DFS over the ICL to find a feasible chain
   of producers (with cycle guard and depth limit).

## Running the Examples

```bash
cd examples/inference
source ../../packages/python/bin/activate    # activate the venv

python 01_dma_buffer_inference.py
python 02_spi_state_inference.py
python 04_multichannel_dma.py
python 05_bus_arbitration_chain.py
```

All scripts accept `--seed N` to reproduce a specific randomization.

> **Note**: Example 03 (`03_streaming_codec.py`) — Stream flow-object
> inference — is not yet implemented.  Stream inference requires concurrent
> coroutine scheduling and is tracked as a future work item.

---

## Example Overview

### `01_dma_buffer_inference.py` — Basic buffer inference

**Concept:** A `ReadData` action requires a `DataBuffer` flow-input.  The user
writes only `do(ReadData)`.  The runtime infers `WriteData` (which produces a
`DataBuffer`) and inserts it before `ReadData` automatically.

**Key features demonstrated:**
- Single-level producer inference
- The inferred `WriteData` and explicit `ReadData` share the *same*
  `DataBuffer` object instance (verified by `assert`)
- Scalar fields (`addr`, `size`) are randomized by the solver

```
Execution:  [inferred] WriteData  →  [user-specified] ReadData
```

---

### `02_spi_state_inference.py` — State flow-object inference

**Concept:** A `FlashRead` action requires a `ChipSelectedState` flow-input
(the SPI bus must have chip-select asserted before a read can happen).  The
user writes only `do(FlashRead)`.  The runtime infers `SelectChip` (which
produces the `ChipSelectedState`) and inserts it before `FlashRead`.

**Key features demonstrated:**
- `zdc.State` flow objects (persistent device state, not one-shot data)
- Inferred predecessor produces state that the consumer reads
- The exact same state instance is handed from producer to consumer

```
Execution:  [inferred] SelectChip  →  [user-specified] FlashRead
```

---

### `04_multichannel_dma.py` — Parallel inference with resource locking

**Concept:** Two `DmaXfer` actions run in parallel.  Each `DmaXfer` internally
lists only `ReadData`; `WriteData` is inferred per arm.  `DmaXfer` holds a
`DmaChannel` lock so the **BindingSolver** ensures the two arms use *different*
channels (AllDifferent).

**Key features demonstrated:**
- Structural inference inside parallel branches
- Per-branch independent buffer objects
- Resource pool + AllDifferent via `zdc.lock()`

```
parallel {
    DmaXfer(chan=0):  [inferred] WriteData  →  ReadData
    DmaXfer(chan=1):  [inferred] WriteData  →  ReadData
}
```

---

### `05_bus_arbitration_chain.py` — Two-level chained inference

**Concept:** `SendPacket` requires an `ArbitratedBusState` flow-input.
`ArbitrateBus` produces `ArbitratedBusState` but itself requires a
`ResetBusState` flow-input.  `ResetBus` produces `ResetBusState`.  The user
writes only `do(SendPacket)` — the solver builds the full chain.

**Key features demonstrated:**
- Multi-level (depth-2) recursive inference
- Flow-object handoff across three sequential actions
- Cross-action state propagation (bus ID flows from `ResetBus` → `ArbitrateBus`)

```
[inferred] ResetBus  →  [inferred] ArbitrateBus  →  [user] SendPacket
```
