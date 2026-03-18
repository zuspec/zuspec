# Zuspec-PSS Scalar Data Types Implementation Status

## Executive Summary

The zuspec-pss codebase has **partial but growing support** for scalar data types:
- **Complete**: int (signed/unsigned, sized/unsized), bool, string
- **Parsing Complete, AST→IR Stubbed**: enum, typedef  
- **Not Started**: bit type as distinct class (currently mapped to DataTypeInt)

All tests pass at the parsing level, but AST→IR translation for enum and typedef are minimal stubs.

---

## 1. IMPLEMENTATION STATUS MATRIX

| Type | Parsing | AST | IR Class | AST→IR | IR→Runtime | Tests | Status |
|------|---------|-----|----------|--------|------------|-------|--------|
| **int** | ✅ | DataTypeInt | DataTypeInt | ✅ | ✅ | 28 tests | Complete |
| **bit** | ✅ | DataTypeInt* | DataTypeInt* | ✅ | ✅ | 28 tests | Complete (as int) |
| **bool** | ✅ | DataTypeBool | DataTypeInt(1-bit) | ✅ | ✅ | 28 tests | Complete |
| **string** | ✅ | DataTypeString | DataTypeString | ✅ | ✅ | 28 tests | Complete |
| **enum** | ✅ | DataTypeEnum | DataTypeEnum | ⚠️ STUB | ⚠️ STUB | 21 tests | Parsing OK, IR stubbed |
| **typedef** | ✅ | TypedefDeclaration | (none) | ⚠️ STUB | ⚠️ STUB | 8 tests | Parsing OK, IR stubbed |

*Note: `bit` type is parsed as DataTypeInt with `is_signed=False`. No distinct DataTypeBit class exists.

---

## 2. IR DATA TYPES STRUCTURE

**File**: `/home/mballance/projects/zuspec/zuspec-pss/packages/zuspec-dataclasses/src/zuspec/dataclasses/ir/data_type.py` (383 lines)

### Core Scalar Types

```python
@dc.dataclass(kw_only=True)
class DataTypeInt(DataType):
    """Integer type with signedness and bit width"""
    bits : int = dc.field(default=-1)        # -1 = unbounded
    signed : bool = dc.field(default=True)   # True for 'int', False for 'bit'

@dc.dataclass(kw_only=True)
class DataTypeString(DataType):
    """String type"""
    ...

@dc.dataclass
class DataTypeEnum(DataType):
    """Enum type - MINIMAL STUB"""
    ...

@dc.dataclass(kw_only=True)
class DataTypeBool(DataType):
    """DOES NOT EXIST - bool is DataTypeInt(bits=1, signed=False)"""
    ...
```

### Related Container Types (not scalars but important)

- `DataTypeUptr` - Platform-sized pointer type (computes width at runtime)
- `DataTypeRef` - Forward reference to types by name
- `DataTypeParameterized` - Uninstantiated templates (e.g., reg_c)
- `DataTypeSpecialized` - Instantiated templates (e.g., reg_c<bit[32], READWRITE, 32>)
- `DataTypeRegister` - Specialized register type
- `DataTypeRegisterGroup` - Register group with offset tracking

### Base Classes

```python
@dc.dataclass(kw_only=True)
class DataType(Base):
    """Base class for all data types"""
    name : Optional[str] = None           # Type name
    py_type : Optional[Any] = None        # Reference to original Python type
```

---

## 3. KEY FILES EXAMINED

### A. IR Classes: `data_type.py` (Complete Content - 383 lines)

The file contains:
- **Basic scalar types**: DataType, DataTypeInt, DataTypeString, DataTypeEnum, DataTypeBool
- **Container types**: DataTypeStruct, DataTypeClass, DataTypeComponent, DataTypeRef
- **Template support**: TemplateParam*, TemplateArg*, DataTypeParameterized, DataTypeSpecialized
- **Register types**: DataTypeRegister, DataTypeRegisterGroup
- **Memory types**: DataTypeMemory, DataTypeAddressSpace, DataTypeAddrHandle
- **Channel types**: DataTypeChannel, DataTypeGetIF, DataTypePutIF
- **Synchronization**: DataTypeLock, DataTypeEvent
- **Protocol**: DataTypeProtocol, DataTypeTuple
- **Helper**: ProcessKind enum, Function class

### B. AST→IR Translation: `ast_to_ir.py` (1195 lines)

**File**: `/home/mballance/projects/zuspec/zuspec-pss/packages/zuspec-fe-pss/python/zuspec/fe/pss/ast_to_ir.py`

#### What IS Implemented:

```python
def _translate_data_type(ctx, dtype_node) -> Optional[ir.DataType]:
    """Handles:"""
    - DataTypeInt → ir.DataTypeInt ✅
    - DataTypeString → ir.DataTypeString ✅
    - DataTypeBool → ir.DataTypeInt(bits=1, signed=False) ✅
    - DataTypeUserDefined → ir.DataTypeRef (for unresolved) ✅
    - TypeIdentifier → ir.DataTypeRegister (for reg_c specialization) ✅
```

#### What's MISSING:

```python
# NO HANDLING FOR:
if isinstance(dtype_node, pss_ast.DataTypeEnum):
    # MISSING - No translation at all
    pass

# NO HANDLING FOR:
if isinstance(dtype_node, pss_ast.TypedefDeclaration):
    # MISSING - Not even checked in _translate_unit()
    pass
```

#### Key Methods:

- `_init_builtin_types()` - Registers bool, int, string, common bit[N] sizes
- `_translate_data_type()` - Main dispatcher (LINE 831-881)
- `_translate_type_identifier()` - Handles template specializations
- `_translate_reg_c()` - Special handling for reg_c<R, ACC, SZ>

#### Line-by-Line Status:

```
Line 156-162: Translates Components, Actions, Structs
            NO handling for EnumDecl, TypedefDeclaration
            
Line 831-881: _translate_data_type main dispatcher
            ✅ DataTypeInt (L841-850)
            ✅ DataTypeUserDefined (L852-870)
            ✅ DataTypeString (L872-873)
            ✅ DataTypeBool (L875-876)
            ⚠️ else → logs "Unsupported" (L878-881)
                (DataTypeEnum falls here!)
```

### C. Runtime Type Map: `types.py` (excerpt)

**File**: `/home/mballance/projects/zuspec/zuspec-pss/packages/zuspec-dataclasses/src/zuspec/dataclasses/types.py` (too large to view fully)

Defines:
- `SignWidth` - Base class with width and signed fields
- `S(width)` - Signed type alias
- `U(width)` - Unsigned type alias  
- `Uptr()` - Platform pointer type
- `TimeUnit` - Time enumerations
- `Time` - Time value class
- Builtin types: `u1, u2, u4, u8, u16, u32, u64, i8, i16, i32, i64`

### D. IR→Runtime: `ir_to_runtime.py` (284 lines)

**File**: `/home/mballance/projects/zuspec/zuspec-pss/packages/zuspec-fe-pss/python/zuspec/fe/pss/ir_to_runtime.py`

Maps IR types to Python runtime types via:

```python
_INT_TYPE_MAP = {
    (1,  False): zdc.u1,      # bit type
    (8,  False): zdc.u8,
    (16, False): zdc.u16,
    (32, False): zdc.u32,
    (64, False): zdc.u64,
    (8,  True):  zdc.i8,      # int type
    (16, True):  zdc.i16,
    (32, True):  zdc.i32,
    (64, True):  zdc.i64,
}
```

---

## 4. TEST FILES & PATTERNS

### A. Data Types Tests
**File**: `packages/zuspec-fe-pss/tests/python/parsing/test_data_types.py` (274 lines)

**Test Pattern**:
```python
def test_type_int(parser):
    """Test int type — verify DataTypeInt and location"""
    code = """
struct test_s {
    rand int value;
};
"""
    root = parse_pss(code, parser=parser)
    sym = get_symbol(root, "test_s")
    field = sym.getChild(sym.symtabAt("value"))
    assert isinstance(field.getType(), ast.DataTypeInt)
```

**Coverage**: 28 tests covering:
- Primitives: int, bit, bool, string, chandle
- Sized types: bit[8,16,32,64], int[8,16,32,64]
- Arrays: fixed-size, multi-dimensional
- Enums as types
- Type composition (structs, components, functions)
- Parameterized tests: 5 sizes × 4 types = scalability

### B. Enum Tests
**File**: `packages/zuspec-fe-pss/tests/python/parsing/test_enums.py` (347 lines)

**Test Pattern**:
```python
def test_enum_multiple_items(parser):
    """Test enum with multiple items"""
    code = """
enum color_e { RED, GREEN, BLUE };
    """
    root = parse_pss(code, parser=parser)
    assert get_symbol(root, "color_e") is not None
```

**Coverage**: 21 tests covering:
- Basic enums (empty, single, multiple items)
- Explicit values (auto, sequential, sparse, negative, mixed)
- Enum extensions (v3.0 feature)
- Usage contexts (structs, actions, constraints, functions, return types)
- Scalability: 3-20 items, multiple enums

**NO AST→IR tests** - Only parsing validation

### C. Typedef Tests
**File**: `packages/zuspec-fe-pss/tests/python/parsing/test_typedef.py` (140 lines)

**Test Pattern**:
```python
def test_typedef_basic_bit(parser):
    """Typedef aliasing a bit type"""
    code = """
typedef bit[32] word_t;
struct s {
    word_t data;
};
"""
    root = parse_pss(code, parser=parser)
    sym = get_symbol(root, "s")
    assert has_symbol(sym, "data")
```

**Coverage**: 8 tests covering:
- Typedef of: bit, int, string, bool
- Scopes: package, component, struct
- Multiple typedefs

**NO AST→IR tests** - Only parsing validation

### D. Enum Extensions Tests (v3.0)
**File**: `packages/zuspec-fe-pss/tests/python/parsing/test_enum_extensions.py` (347 lines)

**Coverage**: ~30 tests for:
- Basic extensions
- Multiple extensions of same enum
- Extensions with explicit values
- Extensions across packages
- Usage in constraints, function params, returns

### E. AST→IR Tests
**File**: `packages/zuspec-fe-pss/tests/python/test_ast_to_ir.py` (669 lines, 24 tests)

**Tests cover**:
- Components, actions, structs
- Functions, inheritance
- Statements (if/while/for, assignments)
- Expressions (arithmetic, logical, conditional)
- Mixed types in components

**MISSING**:
- Enum AST→IR translation tests
- Typedef AST→IR translation tests
- DataTypeEnum IR usage tests

---

## 5. WHAT'S MISSING FOR BIT TYPE

Currently NO distinct implementation. `bit` is represented as:
```python
DataTypeInt(bits=N, signed=False)
```

To add a proper bit type:

1. **In IR** (`data_type.py`):
```python
@dc.dataclass(kw_only=True)
class DataTypeBit(DataType):
    bits : int = dc.field(default=-1)
```

2. **In AST→IR** (`ast_to_ir.py`):
```python
def _translate_data_type(ctx, dtype_node):
    ...
    elif isinstance(dtype_node, pss_ast.DataTypeBit):
        width = dtype_node.getWidth()
        bits = width.getValue() if width else -1
        return ir.DataTypeBit(bits=bits)
```

3. **In IR→Runtime** (`ir_to_runtime.py`):
```python
elif isinstance(ir_type, zdc_ir.DataTypeBit):
    return _INT_TYPE_MAP.get((ir_type.bits, False))
```

Currently handled transparently via DataTypeInt mapping.

---

## 6. WHAT'S MISSING FOR ENUM

### AST Structure (COMPLETE):
- `EnumDecl` - Enum declaration (inherits NamedScopeChild)
- `EnumItem` - Individual enum value (has optional explicit value)
- `DataTypeEnum` - Type reference to enum (with optional range restriction)

### AST→IR Translation (MINIMAL/STUB):

**Currently**:
```python
# In _translate_data_type (LINE 831-881):
# enum types just fall through to unsupported case
if isinstance(dtype_node, pss_ast.DataTypeEnum):
    # NO HANDLING
    return None
```

**Missing in _translate_unit()** (LINE 144-162):
```python
# No handling for EnumDecl at global scope
elif isinstance(child, pss_ast.EnumDecl):
    self._translate_enum(ctx, child)  # NOT IMPLEMENTED
```

### What Needs Implementation:

1. **Enum declaration translation**:
```python
def _translate_enum(ctx: AstToIrContext, enum_decl: pss_ast.EnumDecl):
    name = enum_decl.getName().getId()
    
    # Get enum items
    items = {}
    for i in range(enum_decl.numItems()):
        item = enum_decl.getItem(i)
        item_name = item.getName().getId()
        
        # Optional: get explicit value
        value_expr = item.getValue()
        if value_expr:
            # Translate expression to IR
            items[item_name] = self._translate_expr(ctx, value_expr)
        else:
            items[item_name] = None  # Auto-assigned
    
    enum_type = ir.DataTypeEnum(name=name)
    enum_type.items = items  # Store enum items
    ctx.add_type(name, enum_type)
```

2. **Enum type reference translation**:
```python
elif isinstance(dtype_node, pss_ast.DataTypeEnum):
    tid = dtype_node.getTid()  # Get the enum reference
    type_name = self._get_type_name(tid)
    existing = ctx.get_type(type_name)
    if existing:
        return existing
    else:
        return ir.DataTypeRef(ref_name=type_name)
```

3. **IR class enhancement**:
```python
@dc.dataclass
class DataTypeEnum(DataType):
    items : Dict[str, Optional[ir.Expr]] = dc.field(default_factory=dict)
    # Map enum item name to its value (None = auto-assign)
```

---

## 7. WHAT'S MISSING FOR TYPEDEF

### AST Structure (COMPLETE):
- `TypedefDeclaration` - Has `getName()` → ExprId and `getType()` → DataType

### AST→IR Translation (NOT IMPLEMENTED):

**Currently**:
```python
# In _translate_unit() (LINE 144-162):
# TypedefDeclaration is never checked, never handled

# In AST there's no separate class for typedef translation
# It's just checked at parse time but not translated to IR
```

**Missing implementation**:

1. **Typedef declaration translation**:
```python
def _translate_typedef(ctx: AstToIrContext, typedef_decl: pss_ast.TypedefDeclaration):
    """Translate a typedef to create an alias in the type registry"""
    name = typedef_decl.getName().getId()
    base_type = typedef_decl.getType()
    
    # Translate the base type
    ir_type = self._translate_data_type(ctx, base_type)
    
    if ir_type:
        # Create an alias - either store directly or create TypedefAlias
        ctx.add_type(name, ir_type)
        
        # Optional: store metadata about the typedef
        # For now, typedef is just an alias in the type registry
```

2. **Update _translate_unit()**:
```python
elif isinstance(child, pss_ast.TypedefDeclaration):
    self._translate_typedef(ctx, child)
```

3. **Optional: IR class for typedef metadata**:
```python
@dc.dataclass(kw_only=True)
class DataTypeTypedef(DataType):
    """Typedef creates an alias to another type"""
    base_type : DataType = dc.field()  # What we're aliasing
    alias_name : str = dc.field()      # The new name
```

### Simple Approach:
Just store typedefs as aliases in ctx.type_map without creating a separate IR class. When translating field types, if a typedef name is used, resolve it to the actual type.

---

## 8. TEST INFRASTRUCTURE & PATTERNS

### Test Helpers (`test_helpers.py`):

```python
def parse_pss(code: str, parser=None) -> Any:
    """Parse PSS code and return linked AST root"""
    
def assert_parse_ok(code: str, parser=None) -> Any:
    """Assert PSS code parses without errors"""
    
def get_symbol(root: Any, name: str) -> Any:
    """Get symbol by name from AST"""
    
def has_symbol(scope: Any, name: str) -> bool:
    """Check if symbol exists in scope"""
    
def get_location(sym: Any) -> Tuple[int, int]:
    """Get line/column of symbol"""
```

### Pytest Configuration (`conftest.py`):

```python
@pytest.fixture
def parser():
    """Provide Parser instance for each test"""
    return Parser()
```

### Test Pattern for New Scalar Type Tests:

```python
def test_enum_ast_to_ir(parser):
    """Test enum AST→IR translation"""
    from zuspec.fe.pss.ast_to_ir import AstToIrTranslator
    from zuspec.dataclasses import ir
    
    code = """
    enum status_e { IDLE, BUSY, DONE };
    struct s {
        rand status_e state;
    };
    """
    
    # Parse
    root = parse_pss(code, parser=parser)
    
    # Translate to IR
    translator = AstToIrTranslator()
    ctx = translator.translate(root)
    
    # Verify
    assert "status_e" in ctx.type_map
    enum_type = ctx.type_map["status_e"]
    assert isinstance(enum_type, ir.DataTypeEnum)
    # Check enum items, etc.
```

---

## 9. SUMMARY OF MISSING WORK

### For Enum (Priority: HIGH)

1. **AST→IR Translation**:
   - ✅ AST classes exist (EnumDecl, EnumItem, DataTypeEnum)
   - ❌ `_translate_enum()` method needed
   - ❌ Handling in `_translate_unit()` needed
   - ❌ Update `_translate_data_type()` for DataTypeEnum
   - ❌ Enhanced `DataTypeEnum` IR class with items dict

2. **Tests**:
   - ✅ 21 parsing tests exist
   - ❌ AST→IR translation tests needed (~5-10 tests)
   - ❌ IR→Runtime tests needed (~3-5 tests)

3. **IR→Runtime**:
   - ❌ Build Python enum classes in ClassRegistry
   - ❌ Support enum instances as IR values

**Effort**: ~200 lines code + ~20 tests

### For Typedef (Priority: MEDIUM)

1. **AST→IR Translation**:
   - ✅ AST class exists (TypedefDeclaration)
   - ❌ `_translate_typedef()` method needed
   - ❌ Handling in `_translate_unit()` needed
   - ⚠️ May not need new IR class (just type alias)

2. **Tests**:
   - ✅ 8 parsing tests exist
   - ❌ AST→IR translation tests needed (~5 tests)

3. **IR→Runtime**:
   - ✅ Probably works automatically (typedef → base type alias)

**Effort**: ~50 lines code + ~5 tests

### For Bit Type (Priority: LOW)

1. **Current Status**: Fully working as DataTypeInt with signed=False
2. **Optional Refactoring**: Create distinct DataTypeBit class
   - ⚠️ May break existing code
   - Better: Keep as-is, document the mapping

**Effort**: ~100 lines if done, but optional

---

## 10. CODE LOCATIONS QUICK REFERENCE

| Component | File | Lines | Status |
|-----------|------|-------|--------|
| IR Classes | `packages/zuspec-dataclasses/src/zuspec/dataclasses/ir/data_type.py` | 1-383 | ✅ Complete |
| AST→IR Translator | `packages/zuspec-fe-pss/python/zuspec/fe/pss/ast_to_ir.py` | 1-1195 | ⚠️ Partial |
| _translate_data_type | `ast_to_ir.py` | 831-881 | ⚠️ Missing enum |
| _translate_unit | `ast_to_ir.py` | 144-162 | ⚠️ Missing enum/typedef |
| IR→Runtime | `packages/zuspec-fe-pss/python/zuspec/fe/pss/ir_to_runtime.py` | 1-284 | ⚠️ Minimal |
| Parsing Tests | `packages/zuspec-fe-pss/tests/python/parsing/test_data_types.py` | 1-274 | ✅ 28 tests |
| Enum Tests | `packages/zuspec-fe-pss/tests/python/parsing/test_enums.py` | 1-347 | ✅ 21 tests |
| Typedef Tests | `packages/zuspec-fe-pss/tests/python/parsing/test_typedef.py` | 1-140 | ✅ 8 tests |
| AST→IR Tests | `packages/zuspec-fe-pss/tests/python/test_ast_to_ir.py` | 1-669 | ⚠️ No enum/typedef |

