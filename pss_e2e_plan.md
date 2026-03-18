# PSS → RT Test Coverage Plan

## Goal
Tests look exactly like end-user code: define a PSS struct in a Python string,
instantiate it, randomize it, assert constraints are satisfied.

```python
ns = load_pss("struct Packet { rand bit[8] addr; constraint addr%4==0; }")
pkt = ns.Packet()
randomize(pkt)
assert pkt.addr % 4 == 0
```

## Problem
Every constraint feature is missing a PSS FE → RT test. Two things block it:

1. `IrToRuntimeBuilder` only handles `DataTypeComponent` and `DataTypeClass` (actions).
   It does **not** handle `DataTypeStruct` (pure data structs).
2. Generated classes don't have `_ir_struct` attached, so `randomize()` can't
   find the IR metadata.

## Implementation Plan

### A. Extend `IrToRuntimeBuilder` to support `DataTypeStruct`
**File:** `packages/zuspec-fe-pss/python/zuspec/fe/pss/ir_to_runtime.py`

Add `_build_struct(name, dt: DataTypeStruct)` method:
- Creates a plain Python `@dataclasses.dataclass` (no `zdc.Component` base)
- Fields are plain `int`/`str` attributes defaulting to `0` (the IR carries all
  rand/domain/constraint metadata — no `rand()` decorator needed on the class)
- Attaches `cls._zdc_struct = dt` — standardized attach point used by both
  Zuspec FE and PSS FE paths (the PSS FE attaches eagerly at build time;
  Zuspec FE attaches lazily on first use — same attribute, different timing)
- Registers the class in `python_classes` so it's accessible in the `ClassRegistry`

Also clean up `_extract_struct_type()` in `solver/api.py`: remove the `_ir_struct`
fallback branch (lines ~199-200) since everything now uses `_zdc_struct`.

### B. Add `load_pss()` public convenience function
**File:** `packages/zuspec-fe-pss/python/zuspec/fe/pss/__init__.py` (or new `loader.py`)

```python
def load_pss(pss_text: str) -> ClassRegistry:
    """Parse PSS source and return a registry of randomizable Python classes."""
    parser = Parser()
    parser.parses([('inline.pss', pss_text)])
    root = parser.link()
    ctx = AstToIrTranslator().translate(root)
    return IrToRuntimeBuilder(ctx).build()
```

This is a real public API — it's exactly what end users (and tests) need.

### C. Test files
Create one file per constraint category in
`packages/zuspec-fe-pss/tests/python/integration/`:

| File | Features covered | Checklist LRM |
|------|-----------------|---------------|
| `test_pss_static_constraints_rt.py` | named/unnamed static constraints | §16.1.1 |
| `test_pss_logical_constraints_rt.py` | &&, \|\|, implication (->) | §16.1.4–5 |
| `test_pss_conditional_constraints_rt.py` | if-else in constraints | §16.1.6 |
| `test_pss_set_constraints_rt.py` | in-set, in-range | §8.5.9 |
| `test_pss_unique_constraints_rt.py` | unique { } | §16.1.9 |
| `test_pss_foreach_constraints_rt.py` | foreach constraints (may block) | §16.1.7 |

Each test uses the same pattern:
```python
from zuspec.fe.pss import load_pss
from zuspec.dataclasses import randomize

def test_addr_alignment():
    ns = load_pss("""
        struct Packet {
            rand bit[8] addr;
            constraint addr % 4 == 0;
        }
    """)
    pkt = ns.Packet()
    randomize(pkt, seed=42)
    assert pkt.addr % 4 == 0
```

### D. pytest.ini
Add `packages/zuspec-fe-pss/tests/python/integration` to `testpaths`.

## Todos (in order)

1. `extend-ir-to-runtime` — Add DataTypeStruct support + _ir_struct to IrToRuntimeBuilder
2. `add-load-pss` — Add load_pss() public function to zuspec.fe.pss
3. `test-static-rt` — PSS→RT tests: static constraints
4. `test-logical-rt` — PSS→RT tests: logical + implication
5. `test-conditional-rt` — PSS→RT tests: if-else
6. `test-set-rt` — PSS→RT tests: in-set and in-range
7. `test-unique-rt` — PSS→RT tests: unique
8. `test-foreach-rt` — PSS→RT tests: foreach (may reveal wiring gaps)
9. `update-pytest-ini` — Add integration path to pytest.ini
10. `update-checklist` — Update PSS_FEATURE_CHECKLIST.md

## Notes
- Use fixed seeds in all randomize() calls for deterministic tests
- foreach tests may surface solver wiring gaps; treat as a potential blocker
- Do NOT modify existing tests
- `IrToRuntimeBuilder._build_struct()` should NOT use `rand()` decorators —
  the IR already carries all rand/domain/constraint info; the Python class is
  just a value container that randomize() writes into via setattr()
