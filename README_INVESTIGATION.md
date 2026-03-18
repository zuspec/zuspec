# zuspec-fe-pss Comprehensive Investigation Report

## Overview

This directory contains a complete investigation of the **zuspec-fe-pss** package - the PSS (Portable Stimulus Specification) frontend for the Zuspec framework.

## Generated Documentation

### 📄 Main Investigation Report
**File**: `ZUSPEC_FE_PSS_INVESTIGATION.md` (1084 lines)

Complete deep-dive investigation covering all 8 requested areas:

1. **Package Structure** - Full directory tree showing all files and components
2. **PSS Parser API** - Entry points (Parser class, parse(), parses(), link())
3. **AST/IR Structure** - Complete data model showing Component, Action, Field, Struct, Function, Statements, Expressions
4. **Execution Tests** - Description of tests in tests/python/execution/
5. **test_helpers.py** - Full content (439 lines) of all test helper functions
6. **Linker/Symbol Resolution** - Architecture of symbol resolution, linking phases, symbol table API
7. **Code Generation** - AST to IR translator (1164 lines of AstToIrTranslator class)
8. **conftest.py** - Pytest configuration and fixtures (112 lines)

### 📖 Quick Reference Guide
**File**: `ZUSPEC_FE_PSS_QUICK_REFERENCE.md`

Quick lookup guide including:
- Quick start example
- Core API summary  
- File locations for all key components
- AST node access patterns
- Expression access patterns
- IR translation example
- Test helper usage
- Error handling patterns
- Running tests with pytest

---

## Key Files Referenced

### Main API Entry Points
- `python/zuspec/fe/pss/parser.py` - Parser class (main entry point)
- `python/zuspec/fe/pss/__init__.py` - Public API exports
- `python/zuspec/fe/pss/ast_to_ir.py` - AST to IR translator (1164 lines)

### Utilities
- `python/zuspec/fe/pss/utils/symbol_scope_util.py` - Symbol navigation with qualified names
- `python/zuspec/fe/pss/utils/symbol_type_scope_util.py` - Type scope utilities
- `python/zuspec/fe/pss/utils/symbol_children_scope_util.py` - Child scope navigation

### Tests & Configuration
- `tests/python/test_helpers.py` - Shared test utilities (439 lines)
- `tests/python/conftest.py` - Pytest configuration (112 lines)
- `tests/python/execution/test_action.py` - Action execution tests
- `tests/python/test_parser.py` - Parser tests
- `tests/python/test_ast_to_ir.py` - AST-to-IR translation tests

### C++ Source (for reference)
- `src/AstLinker.h/cpp` - Symbol linking implementation
- `src/NameResolver.h/cpp` - Name resolution implementation
- `src/AstSymbolTable.h/cpp` - Symbol table implementation
- `src/PSSParser.g4` - ANTLR PSS grammar

---

## Quick Start Example

```python
from zuspec.fe.pss import Parser, ParseException
from zuspec.fe.pss.utils import SymbolScopeUtil

# Create parser and parse PSS code
parser = Parser()
parser.parses([
    ("design.pss", """
        component pss_top {
            action Setup {
                bit[32] addr;
            }
        }
    """)
])

# Link to resolve symbols
try:
    root = parser.link()
except ParseException as e:
    print(f"Parse error: {e}")
    for marker in e.markers:
        print(f"  {marker['file']}:{marker['line']}: {marker['message']}")
    exit(1)

# Navigate symbol tree
util = SymbolScopeUtil(root)
setup = util.getQname("pss_top::Setup")
print(f"Found action: {setup.getName()}")

# Access fields
for child in setup.children():
    print(f"  Field: {child.getName()}")
```

---

## Architecture Overview

### Parsing & Linking Pipeline

```
PSS Source Code
       ↓
  Parser.parses() / Parser.parse()
       ↓
  ANTLR Lexer/Parser
       ↓
  AstBuilder (AST construction)
       ↓
  GlobalScope (AST per file)
       ↓
  Parser.link()
       ↓
  AstLinker (C++ linking phase)
       │
       ├─ AstMerger (merge files)
       ├─ TaskResolveImports (import resolution)
       ├─ NameResolver (symbol resolution)
       ├─ TaskResolveRef (reference resolution)
       └─ Symbol table population
       ↓
  RootSymbolScope (linked symbol tree)
       ↓
  Navigation with SymbolScopeUtil
```

### Code Generation Pipeline

```
RootSymbolScope (linked AST)
       ↓
  AstToIrTranslator.translate()
       ↓
  AstToIrContext
  ├─ type_map: Dict[name → ir.DataType]
  ├─ scope_stack: List[ir.DataType]
  ├─ symbol_table: Dict
  └─ errors: List[str]
```

---

## Key Concepts

### Symbol Resolution
- **SymbolScopeUtil** - Navigate symbol tree with qualified names (e.g., `"module::Component"`)
- **Symbol Tables** - Each scope (Component, Struct, etc.) has a symbol table
- **Linking** - Multi-phase process that resolves references across files
- **Extensions** - Supports `extend` keyword for type extension

### AST Node Types
- **Container Types**: Component, Action, Struct, Namespace
- **Field Types**: Field, Parameter
- **Function Types**: FunctionDefinition, FunctionPrototype
- **Execution**: ExecScope, ExecTarget
- **Expression Types**: ExprId, ExprNumber, ExprBin, ExprUnary, ExprCond, ExprCast, etc.
- **Statement Types**: StmtReturn, StmtAssignment, StmtIf, StmtWhile, StmtBreak, StmtContinue, etc.

### IR Translation
- **AstToIrTranslator** converts PSS AST to Zuspec IR
- **DataTypeComponent** - IR component type
- **DataTypeClass** - IR action type
- **DataTypeStruct** - IR struct type
- **DataTypeRegister** - IR register (from `reg_c<T, ACC, SZ>` template)
- Special handling for registers with auto-generated functions

---

## Test Framework

### Fixtures (conftest.py)
- `parser` - Fresh parser instance for each test
- `factory` - Global Factory instance (session scope)
- `debug_parser` - Parser with debug output
- `profiling_parser` - Parser with ANTLR profiling enabled
- `sample_component` - Sample PSS component
- `multi_file_project` - Multi-file project example

### Test Helpers (test_helpers.py)
- **Parsing**: `parse_pss()`, `parse_multi_file()`, `assert_parse_ok()`, `assert_parse_error()`
- **Symbol Access**: `get_symbol()`, `has_symbol()`, `assert_linked()`
- **Code Generation**: `generate_actions()`, `generate_components()`, `generate_constraints()`
- **Debugging**: `print_symbol_tree()`, `dump_scope_symbols()`

### Test Categories
- `tests/python/parsing/` - Parsing feature tests
- `tests/python/execution/` - Action execution tests
- `tests/python/source_references/` - Location tracking tests
- `tests/python/performance/` - Performance benchmarks

---

## Public API Summary

### Parser
```python
parser = Parser()
parser.parse(files)              # Parse from disk
parser.parses(files)             # Parse from strings
root = parser.link()             # Link symbols
parser.enable_profiling(bool)    # Enable profiling
info = parser.get_profile_info() # Get profiling metrics
markers = parser.markers         # Get error markers
```

### Symbol Navigation
```python
util = SymbolScopeUtil(root)
component = util.getQname("module::Component")
root_scope = util.getRoot()

# Direct symbol table access
if scope.symtabHas("name"):
    idx = scope.symtabAt("name")
    symbol = scope.getChild(idx)

for child in scope.children():
    print(child.getName())
```

### AST to IR
```python
translator = AstToIrTranslator(debug=True)
ctx = translator.translate(root)

for name, dtype in ctx.type_map.items():
    if isinstance(dtype, ir.DataTypeComponent):
        print(f"Component: {name} with {len(dtype.fields)} fields")

for error in ctx.errors:
    print(f"Translation error: {error}")
```

---

## Running Tests

```bash
# All tests
pytest tests/python/

# Fast tests only
pytest tests/python/ -m "not slow"

# Specific test file
pytest tests/python/test_parser.py

# Specific test
pytest tests/python/test_parser.py::TestParser::test_smoke

# With profiling
pytest tests/python/ -m profiling

# Verbose output
pytest tests/python/ -vv
```

---

## File Statistics

| Component | Lines | Files |
|-----------|-------|-------|
| Parser API | 183 | parser.py |
| AST to IR Translation | 1164 | ast_to_ir.py |
| Test Helpers | 439 | test_helpers.py |
| Pytest Configuration | 112 | conftest.py |
| Symbol Utilities | ~150 | utils/*.py |
| C++ Source | ~5000+ | src/*.h/.cpp |
| ANTLR Grammars | ~500+ | src/*.g4 |

---

## Additional Resources

### Examples
- `examples/ast_to_ir_demo.py` - Demonstration of AST to IR translation

### Standard Library
- `src/stdlib/executor_pkg.pss` - Built-in PSS executor package
- `src/stdlib/mk_pssstdlib.py` - Standard library generator

### Package Setup
- `setup.py` - Python package setup (Cython extensions)
- `pyproject.toml` or `setup.cfg` - Modern Python packaging

---

## Information Completeness

✅ **Section 1**: Package structure with full directory tree  
✅ **Section 2**: PSS Parser API with all entry points and signatures  
✅ **Section 3**: AST/IR structure with all node types and inheritance  
✅ **Section 4**: Execution tests description and test categories  
✅ **Section 5**: test_helpers.py complete 439-line content  
✅ **Section 6**: Linker/symbol resolution architecture  
✅ **Section 7**: Code generation with all translator methods  
✅ **Section 8**: conftest.py complete 112-line content with fixtures  

---

## Document Navigation

- Start with **ZUSPEC_FE_PSS_QUICK_REFERENCE.md** for quick lookups
- Refer to **ZUSPEC_FE_PSS_INVESTIGATION.md** for detailed information
- Use this **README_INVESTIGATION.md** as a navigation guide

---

Generated: 2024
Repository: /home/mballance/projects/zuspec/zuspec-pss
Package: packages/zuspec-fe-pss
