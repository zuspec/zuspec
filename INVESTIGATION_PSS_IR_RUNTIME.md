# COMPLETE PSS→IR→Python-Runtime Pipeline Investigation

## 1. PACKAGE STRUCTURE

**Base directory**: `/home/mballance/projects/zuspec/zuspec-pss/packages/zuspec-fe-pss/`

### Python files in zuspec-fe-pss:

```
python/zuspec/fe/pss/
├── __init__.py                    # Main API: load_pss()
├── parser.py                      # PSS parser (C++ bindings)
├── ast_to_ir.py                   # AST → IR translator
├── ir_to_runtime.py               # IR → Python runtime builder
├── ast_ext.py                     # AST extensions
├── pkginfo.py, __version__.py     # Package metadata
├── utils/                         # Symbol/scope utilities
└── ast.pyi, core.pyi              # Type stubs (C++ bindings)

tests/python/
├── test_load.py                   # Basic parser tests
├── test_ast_to_ir.py              # AST→IR translation (24 tests, all pass)
├── execution/test_action.py       # Component+action execution
├── integration/
│   ├── test_pss_static_constraints_rt.py    # (6 tests, all pass)
│   ├── test_pss_logical_constraints_rt.py
│   ├── test_pss_conditional_constraints_rt.py
│   ├── test_pss_foreach_constraints_rt.py
│   ├── test_pss_set_constraints_rt.py
│   └── test_pss_unique_constraints_rt.py
└── parsing/                       # Syntax parsing tests
```

---

## 2. IrToRuntimeBuilder (CORE COMPONENT)

**File**: `/home/mballance/projects/zuspec/zuspec-pss/packages/zuspec-fe-pss/python/zuspec/fe/pss/ir_to_runtime.py`

### What it builds:
- **Enums** → `IntEnum` with `dt.py_type = cls` attached
- **Structs** → Plain dataclasses with `_zdc_struct` attached for randomization
- **Components** → `zdc.Component` subclasses with optional `init_down` function
- **Actions** → `zdc.Action[ComponentType]` subclasses with optional `body`, `pre_solve`, `post_solve` functions

### Key IR types handled:

```python
# From zuspec.dataclasses.ir:
- DataTypeStruct       # Pure data structs (PSS struct)
- DataTypeClass       # Classes/polymorphic structs (PSS action inheritance)
- DataTypeComponent   # Structural building blocks (PSS component)
- DataTypeEnum        # Integer enums (PSS enum)
- DataTypeInt         # Scalar integers (bit[N], int, signed/unsigned)
- DataTypeRef         # Forward references by name
- DataTypeArray/List/Map/Set   # Collection types
- DataTypeString/Chandle       # Other primitive types
```

### Key methods:

```python
class IrToRuntimeBuilder:
    def build() -> ClassRegistry
        """Main entry point. Returns dict-like ClassRegistry of built classes."""
        # Build order:
        # 1. Enums (dependencies for fields)
        # 2. Pure structs (non-class structs, topologically sorted)
        # 3. Components (topologically sorted)
        # 4. Actions (attached to component classes as attributes)
    
    def _build_struct(name, dt) -> type
        """Plain Python dataclass, NO zuspec base. Annotated _zdc_struct = dt"""
        
    def _build_enum(name, dt) -> IntEnum
        """Python IntEnum. Stores dt.py_type = cls for reflection"""
        
    def _build_component(name, dt) -> type  
        """Subclass of zdc.Component. Has optional __post_init__"""
        
    def _build_action(dt, parent_comp_name) -> type
        """Subclass of zdc.Action[ComponentType]. Builds body/pre_solve/post_solve"""
    
    def _build_body_fn(func) -> async function
        """Action body: async def body(self_action): ObjectExecutor(...).execute_stmts()"""
        
    def _build_post_init(func) -> sync function
        """Component init_down: def __post_init__(self_comp): ObjectExecutor(...)"""
    
    def _field_to_plain(f) -> (py_type, default)
        """For structs: returns stdlib-compatible type & default (no zdc.field())"""
        
    def _field_to_zdc(f) -> (py_type, default)
        """For components/actions: returns type & zdc.field() or zdc.inst()"""
```

### Return value (build()):

```python
ClassRegistry(dict)  # Dict-like with attribute access:
  - Components: keyed by name ('Top', 'MyC')
  - Actions: keyed by 'CompName::ActionName' (also available as MyC.MyA attribute)
  - Structs: keyed by name ('Packet')
  - Enums: keyed by name ('MyEnum')
```

### Examples of built classes:

```python
# Struct → Plain dataclass:
@dataclass
class Packet:
    addr: u8 = 0
    data: u8 = 0
    _zdc_struct = <IR DataTypeStruct>  # Attached for randomize()

# Component → zdc.Component subclass:
@dataclass
class MyC(zdc.Component):
    pkt: Packet = zdc.inst()
    __post_init__: function (if init_down exists)

# Action → zdc.Action[ComponentType] subclass:
class MyA(zdc.Action[MyC]):
    result: u32 = zdc.field()
    async def body(self): <execute body statements>
    def pre_solve(self): <optional>
    def post_solve(self): <optional>

# Attached to component:
MyC.MyA = <Action class>  # Also in registry['MyC::MyA']
```

---

## 3. Parser / Linker API

**File**: `/home/mballance/projects/zuspec/zuspec-pss/packages/zuspec-fe-pss/python/zuspec/fe/pss/parser.py`

### Usage pattern:

```python
from zuspec.fe.pss import Parser

# Parse from files:
parser = Parser()
parser.parse(['file1.pss', 'file2.pss'])  # From disk

# Parse from strings:
parser.parses([('file1.pss', text1), ('file2.pss', text2)])

# Link AST symbols:
root = parser.link()  # Returns: zsp_ast.RootSymbolScope

# Error handling:
try:
    parser.parse(['file.pss'])
except ParseException as e:
    for marker in e.markers:
        print(f"{marker['severity']} at {marker['file']}:{marker['line']}:{marker['col']}: {marker['message']}")
```

### Key classes:

```python
class Parser:
    def parse(files: List[str]) -> bool
    def parses(files: List[Tuple[str, str]]) -> bool
    def link() -> RootSymbolScope
    @property markers -> List[Dict]  # Structured error markers
    
class ParseException(Exception):
    markers: List[Dict]  # Structured error info
```

---

## 4. __init__.py Exports

**File**: `/home/mballance/projects/zuspec/zuspec-pss/packages/zuspec-fe-pss/python/zuspec/fe/pss/__init__.py`

### Main API:

```python
def load_pss(pss_text: str) -> ClassRegistry:
    """Parse PSS text → IR → Python runtime.
    
    Returns ClassRegistry of randomizable classes.
    
    Example:
        from zuspec.fe.pss import load_pss
        from zuspec.dataclasses import randomize
        
        ns = load_pss('''
            struct Packet {
                rand bit[8] addr;
                constraint addr % 4 == 0;
            }
        ''')
        pkt = ns.Packet()
        randomize(pkt, seed=42)
        assert pkt.addr % 4 == 0
    """
    parser = Parser()
    parser.parses([('inline.pss', pss_text)])
    root = parser.link()
    ctx = AstToIrTranslator().translate(root)
    return IrToRuntimeBuilder(ctx).build()

# Also exported for direct use:
from .parser import Parser, ParseException
from .ast_to_ir import AstToIrTranslator, AstToIrContext
from .ir_to_runtime import IrToRuntimeBuilder, ClassRegistry
```

---

## 5. AstToIrContext

**File**: `/home/mballance/projects/zuspec/zuspec-pss/packages/zuspec-fe-pss/python/zuspec/fe/pss/ast_to_ir.py`

### Context structure:

```python
class AstToIrContext:
    type_map: Dict[str, ir.DataType]           # Name → IR type
    symbol_table: Dict[str, Any]               # Symbol → value
    errors: List[str]                          # Translation errors
    scope_stack: List[ir.DataType]             # Current scope chain
    ir_context: Optional[ir.Context]           # Global IR context
    parent_comp_names: Dict[str, str]          # 'MyC::MyA' → 'MyC'
    local_vars: set                            # Local variable names
    
    def push_scope(scope: ir.DataType): ...
    def current_scope() -> Optional[ir.DataType]: ...
    def add_type(name: str, dtype: ir.DataType): ...
```

### Translator:

```python
class AstToIrTranslator:
    def translate(ast_root: GlobalScope) -> AstToIrContext:
        # Initializes builtin types (bool, int, string)
        # Walks AST and populates context.type_map
        # Returns context with all IR nodes populated
```

---

## 6. Existing Tests

### Summary:

| Test file | Type | Count | Status |
|-----------|------|-------|--------|
| `test_ast_to_ir.py` | Unit | 24 | ✅ ALL PASS |
| `test_pss_static_constraints_rt.py` | Integration | 6 | ✅ ALL PASS |
| `test_pss_logical_constraints_rt.py` | Integration | 7+ | ✅ (spot-checked) |
| `execution/test_action.py` | Integration | 1 | ❌ FAILS (activity extraction) |
| `test_load.py` | Smoke | 1 | ✅ PASSES |

### Working integration test example:

```python
# test_pss_static_constraints_rt.py::test_unnamed_constraint
def test_unnamed_constraint():
    """Unnamed inline constraint: constraint expr;"""
    ns = load_pss("""
        struct Packet {
            rand bit[8] addr;
            constraint addr % 4 == 0;
        }
    """)
    pkt = ns.Packet()
    randomize(pkt, seed=42)
    assert pkt.addr % 4 == 0, f"addr not aligned: {pkt.addr}"
    # ✅ PASSES - full PSS → IR → Python → Solver → Randomization works
```

### Known broken test:

```python
# execution/test_action.py::test_action
def test_action():
    # Builds MyC component with MyA action using IrToRuntimeBuilder
    # Creates Top instance
    # Tries to execute action:
    #   async def run():
    #       a = await MyA()(top)  # Fails when building 'activity' method from dynamically-created class
    # ❌ FAILS: DataModelFactory.inspect.getsource() → can't get source of dynamic class
```

---

## 7. `_extract_struct_type` in zuspec-dataclasses

**File**: `/home/mballance/projects/zuspec/zuspec-pss/packages/zuspec-dataclasses/src/zuspec/dataclasses/solver/_core_solve.py`

### Implementation (lines 56–93):

```python
def _extract_struct_type(obj: Any) -> DataTypeStruct:
    """Return the IR DataTypeStruct attached to *obj* or its class.
    
    Raises RandomizationError when the struct cannot be found.
    """
    # Priority 1: Check instance attribute
    if hasattr(obj, "_zdc_struct"):
        return obj._zdc_struct
    
    # Priority 2: Check class attribute
    cls = obj.__class__
    if hasattr(cls, "_zdc_struct"):
        return cls._zdc_struct
    
    # Priority 3: Check Component base class
    from ..types import Component
    if isinstance(obj, Component):
        if hasattr(obj, "_zdc_struct"):
            return obj._zdc_struct
        if hasattr(cls, "_zdc_struct"):
            return cls._zdc_struct
    
    # Priority 4: Last resort — build on demand via DataModelFactory
    try:
        from ..data_model_factory import DataModelFactory
        factory = DataModelFactory()
        ctx = factory.build([cls])
        type_name = f"{cls.__module__}.{cls.__qualname__}"
        struct = ctx.type_m.get(type_name) or ctx.type_m.get(cls.__qualname__)
        if struct:
            cls._zdc_struct = struct  # Cache for next time
            return struct
    except Exception as exc:
        raise RandomizationError(
            f"Cannot extract IR struct type from {cls.__name__}: {exc}"
        ) from exc
    
    raise RandomizationError(
        f"Cannot extract IR struct type from {cls.__name__}. "
        "Ensure the class is decorated with @dataclass from zuspec.dataclasses"
    )
```

### What attribute does it look for?
- **`_zdc_struct`** — The IR `DataTypeStruct` (or subclass) attached by `IrToRuntimeBuilder`
- Falls back to lazy build via `DataModelFactory` if not found

---

## 8. Zuspec IR Types

**File**: `/home/mballance/projects/zuspec/zuspec-pss/packages/zuspec-dataclasses/src/zuspec/dataclasses/ir/data_type.py`

### Key IR classes:

```python
@dataclass
class DataType(Base):
    """Base class for all IR types"""
    name: Optional[str] = None
    py_type: Optional[Any] = None  # Reference to Python class (enum only)

# Struct types:
@dataclass
class DataTypeStruct(DataType):
    """PSS struct — pure data type"""
    super: Optional[DataType]           # Base type
    fields: List[Field]                 # Field definitions
    functions: List[Function]           # Methods
    is_abstract: bool = False

@dataclass
class DataTypeClass(DataTypeStruct):
    """Polymorphic class (inherits from struct)"""
    pass

@dataclass
class DataTypeComponent(DataTypeClass):
    """Structural building block (PSS component)"""
    bind_map: List[Bind]                # Port/export bindings
    sync_processes: List[Function]      # Sync processes
    comb_processes: List[Function]      # Combinational processes

# Reference types:
@dataclass
class DataTypeRef(DataType):
    """Forward reference by name"""
    ref_name: str

# Scalar types:
@dataclass
class DataTypeInt(DataType):
    bits: int                           # Bit width (-1 if variable)
    signed: bool = True

@dataclass
class DataTypeEnum(DataType):
    """Integer enum with named members"""
    items: dict  # {name: int_value, ...}  (OrderedDict preserves order)

@dataclass
class DataTypeString(DataType): ...

@dataclass
class DataTypeChandle(DataType):
    """Opaque C handle (PSS §7.7)"""
    pass

# Collection types:
@dataclass
class DataTypeArray(DataType):
    element_type: Optional[DataType]
    size: int  # -1 if variable-size

@dataclass
class DataTypeList(DataType):
    element_type: Optional[DataType]

@dataclass
class DataTypeMap(DataType):
    key_type: Optional[DataType]
    value_type: Optional[DataType]

@dataclass
class DataTypeSet(DataType):
    element_type: Optional[DataType]
```

### Field class (fields.py):

```python
@dataclass
class Field(Base):
    """Represents a struct/component/action field"""
    name: str
    datatype: DataType
    kind: FieldKind = FieldKind.Field  # Field, Port, Export
    bindset: BindSet = <factory>
    direction: Optional[SignalDirection] = None
    clock: Optional[Expr] = None
    initial_value: Optional[Expr] = None
    width_expr: Optional[Expr] = None
    kwargs_expr: Optional[Expr] = None
    is_const: bool = False
    
    # CONSTRAINT SOLVER metadata:
    rand_kind: Optional[str] = None        # "rand", "randc", or None
    domain: Optional[tuple] = None         # (min, max) or list of values
    size: Optional[int] = None             # Fixed array size
    max_size: Optional[int] = None         # Max for variable arrays
    is_variable_size: bool = False         # Variable-size flag
```

### Function class:

```python
@dataclass
class Function(Base):
    name: str
    args: Arguments = None
    body: List[Stmt] = []               # IR statement list
    returns: Optional[DataType] = None
    is_async: bool = False
    # ... plus metadata, import/solve flags
```

---

## 9. IrToRuntimeBuilder.build() return path

### Full lifecycle:

```python
# Entry point:
registry = IrToRuntimeBuilder(ctx).build()  # Line 117

# Inside build():
self.python_classes: Dict[str, Any] = {}

# Build all types:
for name, dt in ctx.type_map.items():
    if isinstance(dt, DataTypeEnum):
        cls = self._build_enum(name, dt)      # → IntEnum
        self.python_classes[name] = cls
    elif isinstance(dt, DataTypeStruct) and not isinstance(dt, DataTypeClass):
        cls = self._build_struct(name, dt)    # → @dataclass
        self.python_classes[name] = cls
    elif isinstance(dt, DataTypeComponent):
        cls = self._build_component(name, dt) # → zdc.Component subclass
        self.python_classes[name] = cls
    elif isinstance(dt, DataTypeClass) and '::' in k:
        cls = self._build_action(dt, parent_name)  # → zdc.Action subclass
        self.python_classes[qname] = cls
        setattr(self.python_classes[parent_name], dt.name, cls)  # Attach to component

# Return wrapper:
return ClassRegistry(self.python_classes)  # Line 164
```

### ClassRegistry wrapper:

```python
class ClassRegistry:
    """Dict-like container with attribute access"""
    def __init__(self, classes: Dict[str, Any]):
        object.__setattr__(self, '_classes', classes)
    
    def __getitem__(self, key: str) -> Any:
        return self._classes[key]  # registry['Packet'] or registry['MyC::MyA']
    
    def __getattr__(self, name: str) -> Any:
        classes = object.__getattribute__(self, '_classes')
        if name in classes:
            return classes[name]
        raise AttributeError(f"No class named '{name}' in registry")
    
    # registry.Top, registry.Packet, registry.MyC, registry.MyC.MyA all work
```

---

## 10. Examples and Demos

### File: `examples/ast_to_ir_demo.py`

Shows manual step-by-step translation:
```python
from zuspec.fe.pss import Parser, AstToIrTranslator

pss_code = """
component MySystem {
    int counter;
    bit[8] status;
    
    function void init() { return; }
}
"""

parser = Parser()
parser.parses([("example.pss", pss_code)])
ast_root = parser.link()

translator = AstToIrTranslator(debug=False)
ctx = translator.translate(ast_root)

# Access IR directly:
for comp_name in ctx.type_map.keys():
    comp = ctx.type_map[comp_name]
    print(f"Component: {comp.name}")
    for field in comp.fields:
        print(f"  Field: {field.name}")
```

### High-level example: `load_pss()`

```python
from zuspec.fe.pss import load_pss
from zuspec.dataclasses import randomize

# Full pipeline in one call:
ns = load_pss("""
    struct Packet {
        rand bit[8] addr;
        bit[8] data;
        constraint addr % 2 == 0;
    }
    
    component MyC {
        Packet pkt;
        action MyA {
            bit[32] result;
            exec body { result = 42; }
        }
    }
    
    component Top {
        MyC c;
    }
""")

# Access built classes:
Top = ns.Top
MyC = ns.MyC
MyA = ns.MyC.MyA  # or ns['MyC::MyA']
Packet = ns.Packet

# Instantiate and randomize:
top = Top()
pkt = ns.Packet()
randomize(pkt, seed=42)
assert pkt.addr % 2 == 0
```

---

## SUMMARY: What Works, What's Missing

### ✅ WORKS (fully tested):

1. **PSS parsing** (parse/parses/link)
2. **AST → IR translation** (24 passing tests)
3. **IR → Python runtime classes**:
   - Structs → plain dataclasses with `_zdc_struct`
   - Enums → Python IntEnum
   - Components → `zdc.Component` subclasses
   - Actions → `zdc.Action[C]` subclasses (basic)
4. **Constraint solving via randomize()** (6+ passing integration tests)
5. **Standard library loading** (stdlib types available in registry)
6. **Error markers** (structured error API)

### ⚠️  PARTIAL/NEEDS WORK:

1. **Action body execution** — Test fails because `inspect.getsource()` can't read dynamically-created classes from `types.new_class()`
   - Body functions ARE created as `async def body(self): ObjectExecutor(...).execute_stmts(stmts)`
   - The ObjectExecutor exists but finding its source at runtime is problematic
   
2. **Component init_down execution** — Similar issue; method source not available at runtime

3. **Pre-solve/post-solve** — Synchronous versions, untested in action context

### ❌ MISSING:

1. **Port/Export binding** — `bind_map` in DataTypeComponent is empty/not populated
2. **Process execution** (`@sync_process`, `@comb_process`) — Listed but not built
3. **Memory/AddressSpace** — IR types defined but not handled in IrToRuntimeBuilder
4. **Protocol/Interface** — IR types defined but not in pipeline
5. **Template instantiation** — Template parameter support in IR but no template type building
6. **Cover/Coverage** — IR types defined but not in pipeline
7. **Sensitivity lists** — Defined but not used
8. **Import/solve functions** — Metadata exists but not materialized

---

## COMPLETE PICTURE: PSS→IR→Python Pipeline

```
┌──────────────────────────────────────────────────────────────────┐
│  USER CALLS: load_pss(pss_text_string)                           │
└──────────────────────────────────────────────────────────────────┘
                              ↓
┌──────────────────────────────────────────────────────────────────┐
│  STEP 1: PARSE                                                   │
│  Parser().parses([(filename, text)]) → parses PSS syntax         │
│  Calls C++ parser via zuspec.fe.pss.core (SWIG bindings)        │
│  Output: AST (zuspec.fe.pss.ast)                                │
└──────────────────────────────────────────────────────────────────┘
                              ↓
┌──────────────────────────────────────────────────────────────────┐
│  STEP 2: LINK                                                    │
│  Parser.link() → links AST symbols, resolves references          │
│  Output: RootSymbolScope (zuspec.fe.pss.ast)                    │
└──────────────────────────────────────────────────────────────────┘
                              ↓
┌──────────────────────────────────────────────────────────────────┐
│  STEP 3: AST → IR TRANSLATION                                    │
│  AstToIrTranslator().translate(ast_root)                         │
│  Walks AST, builds IR nodes (DataTypeStruct, DataTypeComponent)  │
│  Output: AstToIrContext with populated type_map                  │
└──────────────────────────────────────────────────────────────────┘
                              ↓
┌──────────────────────────────────────────────────────────────────┐
│  STEP 4: IR → PYTHON RUNTIME                                     │
│  IrToRuntimeBuilder(ctx).build()                                 │
│                                                                   │
│  For each IR node in ctx.type_map:                               │
│  - DataTypeEnum → Python IntEnum (attach py_type)               │
│  - DataTypeStruct → @dataclass (attach _zdc_struct)             │
│  - DataTypeComponent → zdc.Component subclass                    │
│  - DataTypeClass/Action → zdc.Action[ComponentType] subclass    │
│                                                                   │
│  Functions become:                                               │
│  - body → async def (contains ObjectExecutor.execute_stmts)     │
│  - init_down → __post_init__ (sync, same executor)              │
│  - pre_solve/post_solve → sync methods                           │
│                                                                   │
│  Output: ClassRegistry (dict-like, attribute access)             │
└──────────────────────────────────────────────────────────────────┘
                              ↓
┌──────────────────────────────────────────────────────────────────┐
│  PYTHON RUNTIME CLASSES (created in memory)                      │
│                                                                   │
│  Example:                                                        │
│  @dataclass                                                      │
│  class Packet:  # From PSS struct Packet                         │
│      addr: u8 = 0                                                │
│      data: u8 = 0                                                │
│      _zdc_struct = <IR DataTypeStruct>                           │
│                                                                   │
│  @dataclass                                                      │
│  class MyC(zdc.Component):  # From PSS component MyC             │
│      pkt: Packet = zdc.inst()                                    │
│      __post_init__: method (if init_down exists)                │
│                                                                   │
│  class MyA(zdc.Action[MyC]):  # From PSS action MyC::MyA        │
│      result: u32 = zdc.field()                                   │
│      async def body(self): ObjectExecutor(self).execute_stmts(...) │
│      def pre_solve(self): ...                                    │
│      def post_solve(self): ...                                   │
│                                                                   │
│  MyC.MyA = MyA  # Attached to component class                    │
└──────────────────────────────────────────────────────────────────┘
                              ↓
┌──────────────────────────────────────────────────────────────────┐
│  RANDOMIZATION / CONSTRAINT SOLVING                              │
│                                                                   │
│  User calls: randomize(instance, seed=42)                        │
│                                                                   │
│  randomize():                                                    │
│  1. Calls _extract_struct_type(instance)                         │
│     → Looks for _zdc_struct on instance or class                │
│     → Falls back to lazy build if not found                      │
│  2. Builds ConstraintSystem from IR metadata                     │
│  3. Runs PropagationEngine + BacktrackingSearch                  │
│  4. Assigns random values respecting constraints                 │
│  5. Sets instance fields to solution values                      │
│                                                                   │
│  ✅ WORKS: 6+ passing integration tests prove this               │
└──────────────────────────────────────────────────────────────────┘
```

---

## CRITICAL FINDINGS FOR IMPLEMENTATION PLAN

### 1. **Attribute Attachment Strategy**
- IrToRuntimeBuilder ONLY attaches `_zdc_struct` to **structs** (line 189)
- IrToRuntimeBuilder DOES NOT attach `_zdc_struct` to **components or actions**
- But `_extract_struct_type` doesn't need it for components (checks `isinstance(obj, Component)`)
- **Action classes**: Need to check if they need `_zdc_struct` (likely not, they inherit from Action[C])

### 2. **Action Body Execution Blocker**
- The body method IS created correctly as async def
- But when randomize() tries to introspect it for the DataModelFactory, it fails
- **Solution**: Pre-compile ObjectExecutor statements into the body function, or defer introspection

### 3. **Registry Key Conventions**
- Components: simple name ('Top', 'MyC')
- Actions: qualified name ('MyC::MyA')
- Structs: simple name ('Packet')
- Enums: simple name ('MyEnum')
- Standard library: qualified names ('std_pkg::actor_c'), simple names ('actor_c'), both

### 4. **Standard Library**
- Parser automatically loads stdlib (~60+ types)
- Includes Channel, Actor, AddressSpace, Reg, Executor, etc.
- All registered in final ClassRegistry
- Can filter user types by checking if action name has '::'

### 5. **Constraint Metadata**
- Field.rand_kind: "rand", "randc", or None
- Field.domain: (min, max) tuple or list
- Constraints are converted to IR statements, stored in dt.functions
- Solver converts to CSP variables and constraints

### 6. **Build Order Matters**
- Enums first (dependencies)
- Structs second, topologically sorted (for field types)
- Components third, topologically sorted (for field types)
- Actions last (need parent components already built)

