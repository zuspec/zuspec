# PSS→IR→Python-Runtime Pipeline: QUICK REFERENCE

## Files Investigated

| File | Lines | Purpose |
|------|-------|---------|
| `ir_to_runtime.py` | 394 | Core IR→Python builder |
| `parser.py` | 184 | PSS parser (C++ wrapper) |
| `__init__.py` | 52 | High-level `load_pss()` API |
| `ast_to_ir.py` | 120+ | AST→IR translator |
| `_core_solve.py` (solver) | ~100 | `_extract_struct_type()` |
| `data_type.py` (IR) | 250+ | IR type definitions |
| `fields.py` (IR) | 60 | Field metadata |

## Key Data Structures

### ClassRegistry (return type of build())
```python
class ClassRegistry(dict):
    # Access by key or attribute
    registry['Packet']       # Struct
    registry['MyC::MyA']     # Action
    registry.Top             # Component
    registry.MyC.MyA         # Nested access
```

### DataTypeStruct (core IR node)
```python
@dataclass
class DataTypeStruct:
    name: str
    super: Optional[DataType]
    fields: List[Field]              # With rand_kind, domain metadata
    functions: List[Function]        # Body, pre_solve, post_solve
    is_abstract: bool
```

### Field (holds constraint metadata)
```python
@dataclass
class Field:
    name: str
    datatype: DataType
    rand_kind: Optional[str]         # "rand", "randc", or None
    domain: Optional[tuple]          # (min, max) or list
    size: Optional[int]              # Array size
```

## Core Pipeline

```
load_pss(text)
  └→ Parser().parses() / link()          [C++ parser]
  └→ AstToIrTranslator().translate()     [Walk AST, build IR]
  └→ IrToRuntimeBuilder().build()        [IR → Python classes]
     └→ _build_enum()        [IntEnum]
     └→ _build_struct()      [@dataclass + _zdc_struct]
     └→ _build_component()   [zdc.Component subclass]
     └→ _build_action()      [zdc.Action[C] subclass]
     └→ _build_body_fn()     [async def body()]
  └→ ClassRegistry             [Dict with attribute access]
     └→ randomize(instance)   [Extract _zdc_struct, solve constraints]
```

## What Gets Attached Where

| Type | Attribute | Purpose |
|------|-----------|---------|
| Struct class | `_zdc_struct` | IR for randomization |
| Enum class | `py_type` | Python IntEnum reference |
| Component | Inherits from `zdc.Component` | Runtime type system |
| Action | Inherits from `zdc.Action[C]` | Async execution |
| Action | `body`, `pre_solve`, `post_solve` | Compiled methods |

## How Constraints Work

1. **Parse PSS**: `constraint addr % 4 == 0;` → AST node
2. **Translate to IR**: AST → Function.body (statement list)
3. **Extract metadata**: Field.rand_kind="rand", Field.domain inferred or explicit
4. **Solver builds CSP**: randomize() calls _extract_struct_type() → ConstraintSystem
5. **Solve & assign**: BacktrackingSearch finds valid assignment
6. **Apply to instance**: solver.py writes values back to object fields

## Critical Points for Implementation

### 1. Attribute Lookup Strategy (_extract_struct_type)
```
Priority:
1. obj._zdc_struct        # Attached to instance
2. obj.__class__._zdc_struct  # Attached to class
3. isinstance(obj, Component)  # Component base
4. DataModelFactory().build([cls])  # Lazy build & cache
```

### 2. Action/Component Build Order
Must be:
1. Enums (field type dependencies)
2. Structs (field type dependencies)  
3. Components (field type dependencies)
4. Actions (need parent component built first)

### 3. Function Materialization
- `body` (action) → async def with ObjectExecutor
- `init_down` (component) → __post_init__ with ObjectExecutor
- `pre_solve`, `post_solve` (action) → sync def with ObjectExecutor
- ObjectExecutor.execute_stmts() runs IR statements at runtime

### 4. The inspect.getsource() Problem
When randomize() → DataModelFactory tries to build IR from dynamic classes:
- Dynamic classes created with `types.new_class()` have no source file
- inspect.getsource(cls) fails with OSError
- **Solution**: Attach pre-built IR, or use DataModelFactory.register()

## Tests That Pass

| File | Count | Status |
|------|-------|--------|
| test_ast_to_ir.py | 24 | ✅ ALL PASS |
| test_pss_static_constraints_rt.py | 6 | ✅ ALL PASS |
| test_pss_logical_constraints_rt.py | 7+ | ✅ SPOT-CHECK PASS |
| execution/test_action.py | 1 | ❌ FAILS |

## Quick Debug Checklist

- [ ] Parser loads stdlib? (should see 60+ types in registry)
- [ ] _zdc_struct attached to Packet? `hasattr(ns.Packet, '_zdc_struct')`
- [ ] randomize() works on struct? `randomize(instance, seed=42)`
- [ ] Constraints respected? `assert instance.x % 4 == 0`
- [ ] Action class exists? `ns['MyC::MyA']` or `ns.MyC.MyA`
- [ ] Action has body method? `hasattr(ns.MyC.MyA, 'body')`
- [ ] Component has init_down? `hasattr(ns.MyC.__post_init__)`

## Files to Modify (Priority)

| Priority | File | Reason |
|----------|------|--------|
| 🔴 HIGH | ir_to_runtime.py | Fix action body execution |
| 🔴 HIGH | test_action.py | Fix test |
| 🟡 MED | ir_to_runtime.py | Add process building |
| 🟡 MED | tests/ | Add new integration tests |
| 🟢 LOW | ast_to_ir.py | Enhance (if needed) |

