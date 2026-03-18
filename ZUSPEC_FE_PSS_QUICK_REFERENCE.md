# zuspec-fe-pss Quick Reference

## Quick Start

```python
from zuspec.fe.pss import Parser, ParseException
from zuspec.fe.pss.ast_to_ir import AstToIrTranslator
from zuspec.fe.pss.utils import SymbolScopeUtil

# 1. Create parser
parser = Parser()

# 2. Parse PSS code
parser.parses([
    ("design.pss", """
        component pss_top {
            action Setup {
                bit[32] addr;
                
                exec body {
                    print("Setting up");
                }
            }
        }
    """)
])

# 3. Link to resolve symbols
try:
    root = parser.link()
except ParseException as e:
    print(f"Parse error: {e}")
    for marker in e.markers:
        print(f"  {marker['file']}:{marker['line']}: {marker['message']}")

# 4. Navigate symbol tree
util = SymbolScopeUtil(root)
setup_action = util.getQname("pss_top::Setup")
print(f"Found action: {setup_action.getName()}")

# 5. Translate to IR (optional)
translator = AstToIrTranslator()
ir_ctx = translator.translate(root)
for name, dtype in ir_ctx.type_map.items():
    print(f"Type: {name}")
```

## File Locations Reference

### Main Entry Points
- `/home/mballance/projects/zuspec/zuspec-pss/packages/zuspec-fe-pss/python/zuspec/fe/pss/parser.py` - Parser class
- `/home/mballance/projects/zuspec/zuspec-pss/packages/zuspec-fe-pss/python/zuspec/fe/pss/__init__.py` - Public API
- `/home/mballance/projects/zuspec/zuspec-pss/packages/zuspec-fe-pss/python/zuspec/fe/pss/ast_to_ir.py` - AST to IR translator

### Utilities
- `/home/mballance/projects/zuspec/zuspec-pss/packages/zuspec-fe-pss/python/zuspec/fe/pss/utils/symbol_scope_util.py` - Symbol navigation
- `/home/mballance/projects/zuspec/zuspec-pss/packages/zuspec-fe-pss/python/zuspec/fe/pss/utils/symbol_type_scope_util.py` - Type scope utilities

### Tests & Helpers
- `/home/mballance/projects/zuspec/zuspec-pss/packages/zuspec-fe-pss/tests/python/test_helpers.py` - Test utilities
- `/home/mballance/projects/zuspec/zuspec-pss/packages/zuspec-fe-pss/tests/python/conftest.py` - pytest configuration
- `/home/mballance/projects/zuspec/zuspec-pss/packages/zuspec-fe-pss/tests/python/execution/test_action.py` - Action execution tests

### C++ Source
- `/home/mballance/projects/zuspec/zuspec-pss/packages/zuspec-fe-pss/src/AstLinker.h/cpp` - Symbol linking
- `/home/mballance/projects/zuspec/zuspec-pss/packages/zuspec-fe-pss/src/NameResolver.h/cpp` - Name resolution
- `/home/mballance/projects/zuspec/zuspec-pss/packages/zuspec-fe-pss/src/PSSParser.g4` - PSS grammar

## Core API Summary

### Parser Class
```python
Parser()                              # Create parser instance
.parse(files: List[str])             # Parse from disk
.parses(files: List[Tuple[str,str]]) # Parse from strings
.link() -> RootSymbolScope           # Link symbols
.enable_profiling(bool)              # Enable ANTLR profiling
.get_profile_info()                  # Get profiling metrics
.markers -> List[dict]               # Get parse markers
```

### Symbol Navigation
```python
# After linking:
root = parser.link()

# Access symbols
if root.symtabHas("ComponentName"):
    idx = root.symtabAt("ComponentName")
    component = root.getChild(idx)

# Navigate hierarchy
for child in root.children():
    print(child.getName())

# Use SymbolScopeUtil for qualified names
util = SymbolScopeUtil(root)
component = util.getQname("module::Component")
super_scope = util.getRoot()
```

### AST Node Access
```python
# For components
component.getName() -> ExprId
component.getSuper_t() -> TypeRef or None
component.children() -> Iterable[Symbol]

# For actions
action.getName() -> ExprId
action.children() -> Iterable[Field/ExecScope]

# For fields
field.getName() -> ExprId
field.getType() -> DataType
field.getInit() -> Expr or None

# For exec blocks
exec_scope.children() -> Iterable[Stmt]

# For data types
dtype.getWidth() -> Expr or int    # For int types
dtype.getIs_signed() -> bool       # For int types
dtype.getType_id() -> ExprId       # For user-defined types
```

### Expression Access
```python
# Check expression type
isinstance(expr, ExprId)         # Identifier
isinstance(expr, ExprNumber)     # Number literal
isinstance(expr, ExprString)     # String literal
isinstance(expr, ExprBool)       # Boolean literal
isinstance(expr, ExprBin)        # Binary operation
isinstance(expr, ExprUnary)      # Unary operation
isinstance(expr, ExprCond)       # Ternary/conditional
isinstance(expr, ExprCast)       # Type cast
isinstance(expr, ExprSubscript)  # Array subscript
isinstance(expr, ExprBitSlice)   # Bit slice

# Get expression values
expr.getId()        # For ExprId
expr.getValue()     # For literals
expr.getLhs()       # Left operand
expr.getRhs()       # Right operand
expr.getOp()        # Operator (as int code)
```

### AST to IR Translation
```python
from zuspec.fe.pss.ast_to_ir import AstToIrTranslator, AstToIrContext
from zuspec.dataclasses import ir

translator = AstToIrTranslator(debug=False)
ctx = translator.translate(root)  # root is AST RootSymbolScope

# Access IR types
for name, dtype in ctx.type_map.items():
    if isinstance(dtype, ir.DataTypeComponent):
        print(f"Component: {name}")
    elif isinstance(dtype, ir.DataTypeClass):
        print(f"Action: {name}")
    elif isinstance(dtype, ir.DataTypeStruct):
        print(f"Struct: {name}")

# Check for errors
for error in ctx.errors:
    print(f"Translation error: {error}")

# Access IR structure
for field in dtype.fields:
    print(f"Field: {field.name} : {field.datatype}")
```

## Test Helpers

### Parsing
```python
from tests.python.test_helpers import *

# Parse PSS code
root = parse_pss("component C { }")

# Parse multiple files
files = [("a.pss", "struct S { }"), ("b.pss", "component C { }")]
root = parse_multi_file(files)

# Assert parse succeeds
root = assert_parse_ok("component C { }")

# Assert parse fails
assert_parse_error("invalid pss", "error substring")
```

### Symbol Access
```python
# Get symbol
sym = get_symbol(root, "ComponentName")
sym = get_symbol(root, "module::ComponentName")  # Qualified name

# Check symbol exists
if has_symbol(root, "Component"):
    print("Found!")

# Assert symbol linked
sym = assert_linked(root, "Component")
```

### Code Generation
```python
# Generate test PSS code
code = generate_actions(5)  # 5 actions
code = generate_components(3)  # 3 components
code = generate_constraints(4)  # 4 constraints
code = generate_struct_hierarchy(2)  # Nested structs
```

### Debugging
```python
# Print symbol tree recursively
print_symbol_tree(root, indent=0)

# Dump all symbols in scope
dump_scope_symbols(root)
```

## Running Tests

```bash
# All tests
pytest tests/python/

# Specific test file
pytest tests/python/test_parser.py

# Specific test
pytest tests/python/test_parser.py::TestParser::test_smoke

# Fast tests only (exclude slow)
pytest tests/python/ -m "not slow"

# Profiling tests
pytest tests/python/ -m profiling

# With verbose output
pytest tests/python/ -vv

# With pytest fixtures from conftest.py
# Tests can use: parser, factory, debug_parser, sample_component, multi_file_project
```

## Error Handling

```python
from zuspec.fe.pss import Parser, ParseException

parser = Parser()

try:
    parser.parses([("test.pss", "invalid pss")])
    root = parser.link()
except ParseException as e:
    # e.message contains error description
    # e.markers is list of structured error info
    for marker in e.markers:
        print(f"  Severity: {marker['severity']}")      # "error", "warning", etc.
        print(f"  Message: {marker['message']}")        # Error text
        print(f"  File: {marker['file']}")              # Filename
        print(f"  Line: {marker['line']}")              # 1-based line number
        print(f"  Col: {marker['col']}")                # 1-based column number

# Check for warnings/info after successful parse
for marker in parser.markers:
    if marker['severity'] == 'warning':
        print(f"Warning: {marker['message']}")
```

## Linker Output Structure

After `parser.link()`, the returned `RootSymbolScope` has:

```
RootSymbolScope
├── numUnits() -> int              # Number of global scope units
├── getUnit(i) -> GlobalScope      # Get unit i
└── As SymbolChildrenScope:
    ├── numChildren() -> int       # Number of top-level symbols
    ├── getChild(idx) -> Symbol    # Get child by index
    ├── symtabHas(name) -> bool    # Check if symbol exists
    ├── symtabAt(name) -> int      # Get symbol index (then use getChild)
    └── children() -> Iterable     # Iterate all children
```

Each symbol (Component, Action, Struct, etc.) also implements SymbolChildrenScope, 
allowing hierarchical navigation.

## Built-in Types in Registers

When translating `reg_c<T, ACC, SZ>` templates:
- Functions automatically added: `read()`, `write(val)`, `read_val()`, `write_val(val)`
- Offsets computed with 4-byte alignment
- Register groups get: `get_offset_of_instance()`, `get_offset_of_instance_array()`

## Key Files Summary

| File | Lines | Purpose |
|------|-------|---------|
| parser.py | 183 | Main Parser class - entry point |
| ast_to_ir.py | 1164 | Full AST to IR translation |
| test_helpers.py | 439 | Shared test utilities |
| conftest.py | 112 | pytest configuration |
| symbol_scope_util.py | 62 | Symbol navigation |
| AstLinker.cpp | Core | Symbol linking (C++) |
| NameResolver.cpp | Core | Name resolution (C++) |
| PSSParser.g4 | Core | PSS grammar (ANTLR) |

