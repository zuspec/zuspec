# PSS→IR→Python-Runtime Pipeline: Investigation Index

**Investigation Date**: March 18, 2025
**Status**: Complete with actionable implementation plan

---

## Quick Navigation

### 🚀 Start Here (5-10 minutes)
- **EXECUTIVE_SUMMARY.txt** — High-level findings, what works, known issues, next steps

### 📚 Detailed Reading (30-60 minutes)
- **QUICK_REFERENCE.md** — Cheat sheet with key data structures, pipeline flow, debug checklist
- **IMPLEMENTATION_PLAN.md** — 7-phase plan with specific code locations and effort estimates

### 🔬 Deep Dive (2+ hours)
- **INVESTIGATION_PSS_IR_RUNTIME.md** — Complete technical documentation with file contents

---

## Document Descriptions

### EXECUTIVE_SUMMARY.txt (Critical Reading)
**Length**: ~150 lines | **Reading Time**: 10 minutes

Essential information for decision-making:
- Status: 80% complete, core working, one blocker identified
- What works: All core pipeline pieces tested and verified
- What doesn't: Action body execution, component init_down
- Key insight: Problem is Python inspect limitation, not design flaw
- Next steps: 3 prioritized actions (2-3 hours each)

**Best for**: Project managers, tech leads, quick assessment

---

### QUICK_REFERENCE.md (Developer Cheat Sheet)
**Length**: ~160 lines | **Reading Time**: 10-15 minutes

Practical information for implementation:
- File list with line counts and purposes
- Key data structures (ClassRegistry, DataTypeStruct, Field)
- Complete pipeline flow diagram
- Attribute attachment strategy (what gets attached where)
- The inspect.getsource() problem explained
- Quick debug checklist (7 verifications)
- Priority ranking of files to modify

**Best for**: Developers who need to implement fixes

---

### IMPLEMENTATION_PLAN.md (Action Plan)
**Length**: ~380 lines | **Reading Time**: 30-45 minutes

Complete implementation roadmap:
- Executive summary of status
- PHASE 1: Fix action/component execution (3 options analyzed)
- PHASE 2-7: Extending functionality with effort estimates
- Code locations matrix (what file, what function)
- Testing roadmap with specific test cases
- Performance and robustness considerations
- Known limitations for documentation
- Sign-off checklist

**Best for**: Developers writing code, project planners

---

### INVESTIGATION_PSS_IR_RUNTIME.md (Technical Deep Dive)
**Length**: ~762 lines | **Reading Time**: 2+ hours

Complete technical documentation:
1. Package structure (all Python files listed)
2. IrToRuntimeBuilder deep dive (methods, examples, return values)
3. Parser/Linker API (usage patterns, error handling)
4. __init__.py exports (load_pss function)
5. AstToIrContext structure
6. Zuspec IR types (all classes defined)
7. _extract_struct_type implementation
8. IrToRuntimeBuilder.build() return path
9. Example demonstrations
10. Complete PSS→IR→Python pipeline diagram
11. Critical findings and limitations

**Best for**: Architects, reviewers, future maintainers

---

## Key Findings Summary

### ✅ What Works (Verified)
- PSS parsing and linking
- AST→IR translation (24 unit tests)
- Struct creation with _zdc_struct metadata
- Component and action creation
- Constraint solving (6+ integration tests)
- randomize() with constraints

### ⚠️ Known Issues (One Blocker)
- Dynamic class introspection fails in DataModelFactory
- Action body execution blocked by inspect.getsource()
- Component init_down blocked by same issue
- Solution identified: Pre-populate cache or detect _zdc_struct

### ❌ Not Implemented (Lower Priority)
- Port/export binding
- Process execution (@sync_process, @comb_process)
- Memory/AddressSpace materialization
- Protocol/Interface implementation
- Template instantiation
- Coverage point tracking

---

## Quick Action Items

### 🔴 PRIORITY 1: FIX INSPECT BLOCKER (2–3 hours)
```bash
cd /home/mballance/projects/zuspec/zuspec-pss
python -m pytest packages/zuspec-fe-pss/tests/python/execution/test_action.py -xvs
```
Understand the exact error, then choose:
- Option A: Populate DataModelFactory cache (RECOMMENDED)
- Option B: Skip source lookup if _zdc_struct present (simpler)
- Option C: Monkey-patch inspect (not recommended)

### 🟡 PRIORITY 2: VALIDATE INIT_DOWN & ACTION CONSTRAINTS (2–3 hours)
Write integration tests:
- test_component_init_down()
- test_action_constraints()

### 🟢 PRIORITY 3: ADD PROCESS SUPPORT (2–3 hours, optional)
- Add _build_process() method
- Build @sync_process and @comb_process

---

## File Locations

| Component | File | Lines | Key Functions |
|-----------|------|-------|----------------|
| High-level API | `__init__.py` | 52 | load_pss() |
| Parser | `parser.py` | 184 | Parser.parse/link |
| AST→IR | `ast_to_ir.py` | 120+ | AstToIrTranslator |
| **IR→Runtime** | **ir_to_runtime.py** | **394** | **IrToRuntimeBuilder** |
| Constraint Solver | `solver/_core_solve.py` | ~100 | _extract_struct_type() |
| IR Types | `ir/data_type.py` | 250+ | DataTypeStruct, etc. |
| Fields | `ir/fields.py` | 60 | Field metadata |

---

## Test Results

| Test File | Tests | Status | Notes |
|-----------|-------|--------|-------|
| test_ast_to_ir.py | 24 | ✅ ALL PASS | AST→IR translation verified |
| test_pss_static_constraints_rt.py | 6 | ✅ ALL PASS | Basic constraints verified |
| test_pss_logical_constraints_rt.py | 7+ | ✅ PASS | Logical ops verified |
| execution/test_action.py | 1 | ❌ FAILS | inspect.getsource() blocker |

---

## Data Structure Overview

### ClassRegistry
```python
registry['Packet']           # Struct
registry['MyC::MyA']         # Action
registry.Top                 # Component (attribute access)
registry.MyC.MyA             # Nested action (attribute access)
```

### DataTypeStruct (Core IR Node)
```python
@dataclass
class DataTypeStruct:
    name: str
    super: Optional[DataType]           # Base type
    fields: List[Field]                 # With rand_kind, domain metadata
    functions: List[Function]           # body, init_down, pre_solve, post_solve
```

### Field (Constraint Metadata)
```python
@dataclass
class Field:
    name: str
    datatype: DataType
    rand_kind: Optional[str]    # "rand", "randc", or None
    domain: Optional[tuple]     # (min, max) or list of values
    size: Optional[int]         # Array size
```

---

## Pipeline Overview

```
PSS Text String
    ↓
Parser (C++ via SWIG)
    ↓
AST (zuspec.fe.pss.ast)
    ↓
Linker (symbol resolution)
    ↓
RootSymbolScope
    ↓
AstToIrTranslator.translate()
    ↓
AstToIrContext (type_map populated)
    ↓
IrToRuntimeBuilder.build()
    ├─ _build_enum()         → IntEnum
    ├─ _build_struct()       → @dataclass + _zdc_struct
    ├─ _build_component()    → zdc.Component subclass
    ├─ _build_action()       → zdc.Action[C] subclass
    └─ _build_body_fn()      → async def body()
    ↓
ClassRegistry (dict-like)
    ↓
randomize(instance, seed)
    ├─ _extract_struct_type()   [Find _zdc_struct]
    ├─ ConstraintSystemBuilder  [Build CSP]
    ├─ PropagationEngine        [Propagate]
    └─ BacktrackingSearch       [Solve]
    ↓
Constrained Random Values
```

---

## Critical Implementation Points

### 1. Attribute Attachment
- **Structs**: `_zdc_struct` attached by IrToRuntimeBuilder
- **Enums**: `py_type` attached by IrToRuntimeBuilder
- **Components**: Inherit from `zdc.Component`
- **Actions**: Inherit from `zdc.Action[ParentComponent]`

### 2. Build Order
Must follow: Enums → Structs → Components → Actions

### 3. Constraint Metadata
- `Field.rand_kind`: Set during AST→IR translation
- `Field.domain`: Set during AST→IR translation
- Solver uses these during constraint system construction

### 4. The inspect Problem
- Dynamic classes (types.new_class) have no __file__
- inspect.getsource() → OSError
- Solution: Cache IR instead of lazy-building

---

## How to Use This Documentation

### For Bug Fixes
1. Start with QUICK_REFERENCE.md
2. Find file location in matrix
3. Look up specific code in INVESTIGATION_PSS_IR_RUNTIME.md
4. Reference IMPLEMENTATION_PLAN.md for approach

### For Architecture Review
1. Read EXECUTIVE_SUMMARY.txt (findings)
2. Review INVESTIGATION_PSS_IR_RUNTIME.md (complete picture)
3. Check test results in QUICK_REFERENCE.md

### For Implementation
1. Start with IMPLEMENTATION_PLAN.md (phases & priorities)
2. Reference QUICK_REFERENCE.md (debug checklist)
3. Use INVESTIGATION_PSS_IR_RUNTIME.md (detailed APIs)
4. Run tests to verify

### For Onboarding New Developers
1. Have them read QUICK_REFERENCE.md first
2. Point them to relevant sections in INVESTIGATION document
3. Have them run the debug checklist
4. Assign them from IMPLEMENTATION_PLAN.md phases

---

## Terminology

- **PSS**: Portable Stimulus Specification (domain-specific language)
- **IR**: Intermediate Representation (zuspec.dataclasses.ir types)
- **Runtime**: Python classes generated in memory (not source files)
- **_zdc_struct**: Metadata attribute linking Python class to IR
- **ObjectExecutor**: Executes IR statements at runtime
- **DataModelFactory**: Lazy IR builder (has inspect problem)
- **ClassRegistry**: Dict-like container of generated classes

---

## Contact / Questions

If sections are unclear:
1. Check if concept is in QUICK_REFERENCE.md glossary
2. Search INVESTIGATION document for term
3. Look for example code in IMPLEMENTATION_PLAN.md

---

**Generated**: March 18, 2025 | **Status**: Complete | **Next Review**: After Phase 1 completion
