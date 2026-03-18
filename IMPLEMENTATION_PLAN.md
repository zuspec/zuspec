# PSS→IR→Python-Runtime Pipeline: IMPLEMENTATION PLAN

**Status**: Pipeline 80% complete. Core works. Known issues block advanced features.

---

## EXECUTIVE SUMMARY

### ✅ What Works (FULLY TESTED)
- **load_pss()** high-level API
- **PSS parsing** (Parser/link)
- **AST→IR translation** (24 unit tests pass)
- **IR→Python classes**:
  - Structs → @dataclass with `_zdc_struct`
  - Enums → IntEnum
  - Components → zdc.Component
  - Actions → zdc.Action[C] (basic)
- **Constraint solving** (6+ integration tests pass)
  - Randomization respects constraints
  - Full solver pipeline works

### ⚠️ Known Issues (Block advanced use)
1. **Action body execution** — ObjectExecutor.execute_stmts() works, but inspect.getsource() fails on dynamic classes
   - Impact: Can't execute component action bodies
   - Workaround: Pre-compile statements instead of deferring
   
2. **Component init_down execution** — Same issue
   - Impact: Can't run component initialization
   - Workaround: Pre-compile __post_init__

### ❌ Not Implemented
- Port/Export binding
- Process execution (@sync_process, @comb_process)
- Memory/AddressSpace materialization
- Protocol/Interface implementation
- Template instantiation
- Coverage/coverage points

---

## DETAILED IMPLEMENTATION PLAN

### PHASE 1: FIX ACTION/COMPONENT EXECUTION (HIGH PRIORITY)

**Problem**: `inspect.getsource()` fails on classes created with `types.new_class()`.

**Root cause**: Dynamic classes have no source file, so Python's inspect module can't read them.

**Current code** (ir_to_runtime.py line 269–275):
```python
def _build_body_fn(self, func: zdc_ir.Function):
    stmts = func.body
    async def body(self_action):
        ObjectExecutor(self_action).execute_stmts(stmts)
    return body
```

**When it fails**: DataModelFactory._extract_method_body() calls inspect.getsource(cls) on the dynamic action class.

**Solution Options**:

#### Option A: Pre-populate DataModelFactory (RECOMMENDED)
Instead of letting DataModelFactory lazy-build, pre-populate the data_model_factory's type registry when building IR→Runtime.

```python
# In IrToRuntimeBuilder.build():
def build(self) -> ClassRegistry:
    # ... existing build code ...
    
    # NEW: Populate DataModelFactory cache
    from zuspec.dataclasses.data_model_factory import DataModelFactory
    factory = DataModelFactory()
    for cls in self.python_classes.values():
        if hasattr(cls, '_zdc_struct'):
            # Register built classes so DataModelFactory doesn't need to inspect
            factory.register(cls, cls._zdc_struct)
    
    return ClassRegistry(self.python_classes)
```

**Pros**:
- Clean, bypasses the inspect problem
- Cache IR for future randomizations
- No source code needed

**Cons**:
- Requires DataModelFactory.register() API
- Extra step at build time

#### Option B: Attach fake source (WORKAROUND)
Create a fake source attribute on dynamic classes:

```python
def _build_body_fn(self, func: zdc_ir.Function):
    stmts = func.body
    async def body(self_action):
        ObjectExecutor(self_action).execute_stmts(stmts)
    
    # Attach metadata so inspect doesn't fail
    body.__code__ = type(body.__code__)(
        # ... set co_filename to a marker file
    )
    return body
```

**Pros**: Minimal invasive change

**Cons**: Hacky, fragile

#### Option C: Override DataModelFactory.get_method_source() (MITIGATION)
Patch DataModelFactory to handle classes with `_zdc_struct`:

```python
class DataModelFactory:
    def _extract_method_body(self, cls, method_name, scope=None):
        if hasattr(cls, '_zdc_struct'):
            # Already have IR, don't inspect source
            return []  # or pre-built statements
        # ... original inspect logic
```

**Pros**: Localized to DataModelFactory

**Cons**: Only fixes DataModelFactory, not general inspect problem

---

### PHASE 2: VERIFY COMPONENT INITIALIZATION

**Current status**: `__post_init__` method IS created for init_down, but untested.

**Action**: Write integration test:

```python
def test_component_init_down():
    ns = load_pss("""
        component MyC {
            bit[32] val;
            exec init_down { val = 99; }
        }
        component Top {
            MyC c;
            exec init_down { c.val = 42; }
        }
    """)
    
    top = ns.Top()
    assert top.c.val == 42  # Check if init_down ran
    
    c = ns.MyC()
    assert c.val == 99  # Check if init_down ran on component
```

**Expected**: Both should pass (or fail consistently).

---

### PHASE 3: VERIFY CONSTRAINT EXECUTION IN ACTIONS

**Current status**: Constraint solving works for structs. Unknown for actions.

**Action**: Write integration test:

```python
def test_action_constraints():
    ns = load_pss("""
        component MyC {
            action MyA {
                rand bit[8] x;
                rand bit[8] y;
                constraint x < y;
            }
        }
    """)
    
    MyA = ns['MyC::MyA']
    a = MyA()
    
    # Should respect constraint
    randomize(a, seed=42)
    assert a.x < a.y, f"Constraint violated: x={a.x}, y={a.y}"
```

---

### PHASE 4: EXTEND IRRUNTIMEBUILDER FOR MISSING IR TYPES

**Current coverage**:
- ✅ DataTypeEnum
- ✅ DataTypeStruct (non-class)
- ✅ DataTypeComponent
- ✅ DataTypeClass (actions)
- ❌ DataTypeProtocol
- ❌ DataTypeMemory, DataTypeAddressSpace
- ❌ Process (@sync_process, @comb_process)

**Implementation**:

#### 4.1: Processes

**File**: `ir_to_runtime.py`, add method:

```python
def _build_process(self, dt: zdc_ir.DataTypeComponent, func: zdc_ir.Function):
    """Build a process method (sync or comb)."""
    stmts = func.body
    
    def process(self_comp):
        ObjectExecutor(self_comp).execute_stmts(stmts)
    
    process.__name__ = func.name
    # Attach metadata if needed
    if func.process_kind == ProcessKind.SYNC:
        process._is_sync = True
    elif func.process_kind == ProcessKind.COMB:
        process._is_comb = True
    
    return process
```

Update `_build_component()` to attach processes:

```python
def _build_component(self, name: str, dt: zdc_ir.DataTypeComponent):
    # ... existing code ...
    
    # NEW: Build processes
    for func in dt.sync_processes:
        ns[func.name] = self._build_process(dt, func)
    for func in dt.comb_processes:
        ns[func.name] = self._build_process(dt, func)
    
    # ... rest of code
```

#### 4.2: Memory / AddressSpace

**Status**: IR types exist but not materialized into Python classes.

**Decision**: Do NOT implement until use case is clear.
- These are likely specialized for SystemVerilog harness generation
- Not needed for randomization pipeline
- Low priority

#### 4.3: Protocol

**Status**: IR type exists, no build code.

**Decision**: Postpone — depends on use case.
- May be interface definition, not runtime instance
- Could be built as Protocol[...] from typing module
- Requires design decision on interface representation

---

### PHASE 5: ADD PORT/EXPORT BINDING

**Current**: `DataTypeComponent.bind_map` is empty.

**Investigation needed**:
1. How does PSS represent port binding?
   ```pss
   component Top {
       MyComp c1, c2;
       bind c1.port -> c2.export;
   }
   ```

2. What does AST→IR translator populate in bind_map?

3. What should Python runtime do with bindings?

**Action**: 
- Search PSS spec for binding syntax
- Check if test files exist with bindings
- Design Python representation

---

### PHASE 6: VALIDATE CONSTRAINT METADATA EXTRACTION

**Status**: Field.rand_kind, Field.domain are in IR. Constraint solving uses them.

**Testing**:
```python
def test_constraint_metadata():
    ns = load_pss("""
        struct Packet {
            rand bit[8] addr;
            bit[8] data;
            constraint addr in [0, 4, 8, 12, 16];
        }
    """)
    
    pkt_class = ns.Packet
    struct_ir = pkt_class._zdc_struct
    
    addr_field = next(f for f in struct_ir.fields if f.name == 'addr')
    assert addr_field.rand_kind == 'rand'
    assert addr_field.domain is not None
    
    # Verify constraint solving respects domain
    pkt = ns.Packet()
    randomize(pkt, seed=42)
    assert pkt.addr in [0, 4, 8, 12, 16]
```

---

### PHASE 7: PERFORMANCE AND ROBUSTNESS

#### 7.1: Lazy type building in IrToRuntimeBuilder

**Issue**: All types built upfront. Large PSS files may be slow.

**Mitigation**: Profile before optimizing.

#### 7.2: Error handling

**Current**: Errors in AST→IR translation collected in AstToIrContext.errors.

**Need**: Check if errors are reported to user.

```python
def load_pss(pss_text: str) -> ClassRegistry:
    # ...
    ctx = AstToIrTranslator().translate(root)
    
    if ctx.errors:  # Should check this?
        raise RuntimeError(f"IR translation errors: {ctx.errors}")
    
    return IrToRuntimeBuilder(ctx).build()
```

#### 7.3: Type registry collision

**Issue**: What if stdlib and user both define 'Packet'?

**Current**: Later registration overwrites. Likely bug.

**Fix**: Namespace or qualified names.

---

## TESTING ROADMAP

### Existing passing tests:
- ✅ test_ast_to_ir.py (24 tests)
- ✅ test_pss_static_constraints_rt.py (6 tests)
- ✅ test_pss_logical_constraints_rt.py (7+ tests)

### Need to fix:
- ❌ execution/test_action.py — Fix inspect.getsource() issue first

### New tests to add:
1. test_component_init_down() — Component initialization
2. test_action_constraints() — Action constraint solving
3. test_process_execution() — @sync_process, @comb_process
4. test_port_binding() — Port/export bindings (if applicable)
5. test_stdlib_and_user_types() — Registry collision handling
6. test_enum_constraint() — Enum fields in constraints
7. test_nested_components() — Multi-level component hierarchies
8. test_constraint_metadata() — rand_kind, domain extraction

---

## CODE LOCATIONS AND KEY FUNCTIONS

| Component | File | Key Functions |
|-----------|------|----------------|
| **Parser** | parser.py | Parser.parse(), Parser.link() |
| **AST→IR** | ast_to_ir.py | AstToIrTranslator.translate() |
| **IR→Runtime** | ir_to_runtime.py | IrToRuntimeBuilder.build() |
| **IR types** | ../ir/data_type.py | DataTypeStruct, DataTypeComponent, etc. |
| **Field metadata** | ../ir/fields.py | Field.rand_kind, Field.domain |
| **Constraint solving** | ../solver/ | _extract_struct_type(), randomize() |
| **High-level API** | __init__.py | load_pss() |

---

## IMPLEMENTATION PRIORITY

| Phase | Task | Priority | Effort | Blockers |
|-------|------|----------|--------|----------|
| 1 | Fix action body execution | 🔴 HIGH | 1–2h | None |
| 2 | Verify init_down | 🟡 MED | 1h | Phase 1 |
| 3 | Action constraints | 🟡 MED | 2h | Phase 1 |
| 4 | Processes (@sync/@comb) | 🟡 MED | 2–3h | Phase 1 |
| 5 | Port binding | 🟢 LOW | TBD | Design needed |
| 6 | Constraint metadata validation | 🟡 MED | 1h | None |
| 7 | Performance & robustness | 🟢 LOW | 2–4h | None |

---

## KNOWN LIMITATIONS (DOCUMENT FOR USERS)

1. **Dynamic class introspection** — Body/init_down functions are created dynamically and cannot be introspected at runtime by inspect module.
   - Workaround: Pre-compiled IR statements avoid source lookup.

2. **No source generation** — load_pss() builds classes in memory, no .py file output.
   - This is by design (no external file dependencies).
   - Users can use Python's serialize/pickle if needed.

3. **Component inheritance** — Only single inheritance supported (per PSS spec).

4. **Port/export bindings** — Not yet implemented.
   - Impact: Component topology (which ports connect to which) is not validated at runtime.

5. **Process/sensitivity** — @sync_process and @comb_process defined but not executed.
   - These are typically for formal verification or C harness generation.
   - Not needed for random simulation.

---

## SIGN-OFF CHECKLIST

Before declaring the pipeline complete:

- [ ] Phase 1: Action body execution fixed
- [ ] Phase 2: Component init_down verified
- [ ] Phase 3: Action constraints verified
- [ ] New tests written and all pass
- [ ] Documentation updated in README
- [ ] Known limitations documented
- [ ] Performance profiled (if large files used)
- [ ] Error handling validated

