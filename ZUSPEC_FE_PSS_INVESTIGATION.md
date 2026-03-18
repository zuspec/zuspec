# zuspec-fe-pss Package Investigation Report

## 1. PACKAGE STRUCTURE - Directory Tree

### Python Module Structure
```
packages/zuspec-fe-pss/
├── python/zuspec/fe/pss/                    # Main Python module
│   ├── __init__.py                          # Public API entry point
│   ├── parser.py                            # Parser class - main entry point
│   ├── ast_to_ir.py                         # AST to IR translation (44KB, 1164 lines)
│   ├── ast_ext.py                           # Cython AST extension setup
│   ├── ast.pyx                              # Cython AST bindings (generated)
│   ├── core.pyx                             # Cython core parser bindings (generated)
│   ├── ast.pxd                              # Cython AST declarations
│   ├── core.pxd                             # Cython core declarations
│   ├── ast_decl.pxd                         # Cython AST declarations
│   ├── decl.pxd                             # Cython declarations
│   ├── pkginfo.py                           # Package info
│   ├── __version__.py                       # Version info
│   ├── __build_num__.py                     # Build number
│   └── utils/                               # Utility modules
│       ├── __init__.py
│       ├── symbol_scope_util.py             # Symbol scope navigation
│       ├── symbol_type_scope_util.py        # Type scope utilities
│       ├── symbol_children_scope_util.py    # Child scope utilities
│       └── list_iterator.py                 # Iterator utilities

├── src/                                      # C++ source code
│   ├── PSSParser.g4                         # ANTLR PSS grammar
│   ├── PSSLexer.g4                          # ANTLR lexer
│   ├── PSSExprParser.g4                     # Expression parser grammar
│   ├── PSSExprLexer.g4                      # Expression lexer
│   ├── AstBuilder.h/cpp                     # AST construction
│   ├── AstLinker.h/cpp                      # Symbol linking phase
│   ├── AstMerger.h/cpp                      # File merging
│   ├── Factory.h/cpp                        # AST factory
│   ├── AstSymbol.h/cpp                      # Symbol definitions
│   ├── AstSymbolTable.h/cpp                 # Symbol table implementation
│   ├── NameResolver.h/cpp                   # Name resolution
│   ├── RefExprUtil.h/cpp                    # Reference expression utilities
│   ├── TaskResolveRef.cpp                   # Resolve references task
│   ├── TaskResolveImports.h                 # Import resolution task
│   ├── TaskApplyTypeExtensions.h            # Type extension application
│   ├── TaskApplyOverlay.h                   # Overlay application
│   ├── ResolveContext.h                     # Resolution context
│   └── stdlib/
│       ├── mk_pssstdlib.py                  # Standard library generator
│       └── executor_pkg.pss                 # Built-in executor package

├── tests/python/
│   ├── conftest.py                          # pytest configuration
│   ├── test_helpers.py                      # Shared test utilities
│   ├── test_parser.py                       # Parser tests
│   ├── test_ast_to_ir.py                    # AST-to-IR translation tests
│   ├── test_register_*.py                   # Registration phase tests
│   ├── execution/
│   │   └── test_action.py                   # Action execution tests
│   ├── parsing/                             # Parsing feature tests
│   ├── source_references/                   # Location tracking tests
│   └── performance/                         # Performance tests

├── examples/
│   └── ast_to_ir_demo.py                    # AST-to-IR demonstration

└── build/                                    # Build artifacts
    └── zsp_ast/ext/                         # Generated extension files
```

---

## 2. PSS PARSER API - Entry Points and Usage

### Main Entry Point: Parser Class

**File**: `/home/mballance/projects/zuspec/zuspec-pss/packages/zuspec-fe-pss/python/zuspec/fe/pss/parser.py`

#### Class: `Parser`

```python
class Parser(object):
    """Main PSS parser class for parsing and linking PSS files"""
    
    def __init__(self):
        """Initialize parser with factory instances"""
        # Initializes AST factory and parser factory
        # Loads standard library automatically on first parse
        
    def parse(self, files: List[str]) -> bool:
        """Parse PSS files from disk
        
        Args:
            files: List of file paths to parse
            
        Returns:
            bool: True on success
            
        Raises:
            ParseException: If parsing fails with error list and markers
            
        Example:
            parser = Parser()
            parser.parse(["design.pss", "testbench.pss"])
            root = parser.link()
        """
        
    def parses(self, files: List[Tuple[str, str]]) -> bool:
        """Parse PSS from in-memory strings
        
        Args:
            files: List of (filename, code) tuples
            
        Returns:
            bool: True on success
            
        Raises:
            ParseException: If parsing fails
            
        Example:
            parser.parses([
                ("types.pss", "struct Point { int x; int y; }"),
                ("actions.pss", "component Top { action Move { Point p; } }")
            ])
            root = parser.link()
        """
        
    def link(self) -> 'zsp_ast.RootSymbolScope':
        """Link parsed files and resolve symbols
        
        Returns:
            RootSymbolScope: Root of the linked symbol tree
            
        Raises:
            ParseException: If linking fails with error list and markers
            
        This is the key step that:
        - Resolves symbol references across files
        - Validates type consistency
        - Establishes the symbol hierarchy
        
        Example:
            root = parser.link()
            util = SymbolScopeUtil(root)
            component_a = util.getQname("module1::ComponentA")
        """
        
    def enable_profiling(self, enable: bool = True):
        """Enable ANTLR parsing profiling
        
        Args:
            enable: True to enable, False to disable
            
        Note: Must be called before parse() to take effect
        """
        
    def get_profile_info(self):
        """Get profiling information from last parse operation
        
        Returns:
            ParseProfileInfo object or None
            
        Contains:
            - Decision-level metrics
            - Aggregate metrics
            - Performance statistics
        """
        
    @property
    def markers(self) -> list:
        """Get structured list of markers from parse/link operations
        
        Returns:
            List of dict with keys:
                - severity: "error", "warning", "info", "hint"
                - message: Human-readable error message
                - file: Source filename
                - line: Line number (1-based)
                - col: Column number (1-based)
        """
        
    @property
    def root(self) -> 'zsp_ast.RootSymbolScope':
        """Get linked root symbol scope (after link() called)"""
```

#### Class: `ParseException`

```python
class ParseException(Exception):
    """Exception raised when parsing or linking fails
    
    Attributes:
        message: Error description
        markers: List of structured error markers with location info
    """
    def __init__(self, message, markers=None):
        super().__init__(message)
        self.markers = markers or []
```

### Public API in __init__.py

**File**: `/home/mballance/projects/zuspec/zuspec-pss/packages/zuspec-fe-pss/python/zuspec/fe/pss/__init__.py`

```python
from .parser import Parser, ParseException
from .ast_to_ir import AstToIrTranslator, AstToIrContext

def get_deps():
    """Get module dependencies"""
    return []

def get_libs():
    """Get linked C++ libraries"""
    return ["zsp-parser"]

def get_libdirs():
    """Get library directory paths"""
    # Returns directory containing compiled extensions

def get_incdirs():
    """Get include directory paths"""
    # Returns src/include or build/include paths
```

### Usage Examples

```python
# Example 1: Parse from files
from zuspec.fe.pss import Parser

parser = Parser()
parser.parse(["design.pss"])
root = parser.link()

# Example 2: Parse from strings
parser = Parser()
parser.parses([
    ("test.pss", """
        component pss_top {
            action A {
                bit[32] x;
            }
        }
    """)
])
root = parser.link()

# Example 3: Handle errors
try:
    parser.parse(["invalid.pss"])
    root = parser.link()
except ParseException as e:
    print(f"Parse error: {e}")
    for marker in e.markers:
        print(f"  {marker['severity']}: {marker['file']}:{marker['line']}")

# Example 4: Check markers
root = parser.link()
for marker in parser.markers:
    if marker['severity'] == 'error':
        print(f"Error at {marker['file']}:{marker['line']}: {marker['message']}")

# Example 5: Enable profiling
parser = Parser()
parser.enable_profiling(True)
parser.parse(["design.pss"])
root = parser.link()
profile_info = parser.get_profile_info()
```

---

## 3. AST/IR STRUCTURE - Data Models

### Core AST Classes (Cython/C++ Interface)

The AST is defined in C++ and exposed via Cython. Key classes accessed from Python:

#### Root/Global Scopes
```
RootSymbolScope
  ├── RootSymbolScope.numUnits() -> int
  ├── RootSymbolScope.getUnit(i) -> GlobalScope
  └── RootSymbolScope (SymbolChildrenScope)
      ├── symtabHas(name: str) -> bool
      ├── symtabAt(name: str) -> int
      ├── getChild(idx: int) -> Symbol
      ├── numChildren() -> int
      └── children() -> Iterable[Symbol]

GlobalScope (SymbolChildrenScope)
  ├── children() -> Iterable[Symbol]
  ├── symtabHas(name: str) -> bool
  ├── getChild(idx: int) -> Symbol
  └── numChildren() -> int
```

#### Component Definition
```python
class Component (Symbol):
    """PSS component declaration"""
    ├── getName() -> ExprId | str          # Component name
    ├── getSuper_t() -> TypeRef            # Parent component (if any)
    ├── children() -> Iterable[Symbol]     # Fields, actions, nested types
    └── Methods:
        ├── numChildren() -> int
        ├── getChild(idx: int)
        └── symtabHas(name) -> bool
```

#### Action Definition
```python
class Action (Symbol):
    """PSS action declaration"""
    ├── getName() -> ExprId | str          # Action name
    ├── getSuper_t() -> TypeRef            # Parent action (if any)
    ├── children() -> Iterable[Symbol]     # Fields, exec blocks
    └── Methods:
        ├── numChildren() -> int
        └── getChild(idx: int)
```

#### Field Definition
```python
class Field (Symbol):
    """Field/property in component/action/struct"""
    ├── getName() -> ExprId | str          # Field name
    ├── getType() -> DataType              # Field data type
    ├── getInit() -> Expr | None           # Initialization expression
    └── getAccessModifier() -> AccessMod
```

#### Struct Definition
```python
class Struct (Symbol):
    """User-defined struct type"""
    ├── getName() -> ExprId | str          # Struct name
    ├── getSuper_t() -> TypeRef            # Parent struct
    ├── children() -> Iterable[Field]      # Fields
    └── numChildren() -> int
```

#### Function Definition
```python
class FunctionDefinition (Symbol):
    """Function definition in component/struct"""
    ├── getProto() -> FunctionPrototype    # Function signature
    ├── getBody() -> ExecScope             # Function body
    └── Methods:
        ├── FunctionPrototype.getName() -> ExprId
        ├── FunctionPrototype.getRtype() -> DataType | None
        ├── FunctionPrototype.numParameters() -> int
        └── FunctionPrototype.getParameter(i) -> Parameter
```

#### Execution Blocks (exec)
```python
class ExecScope (Symbol):
    """exec body { ... } block"""
    ├── children() -> Iterable[Stmt]      # Statements in body
    └── numChildren() -> int

class ExecTarget (Symbol):
    """Specific exec variant (init, init_down, body, etc.)"""
    ├── getLabel() -> str                  # "body", "init_down", etc.
    └── getScope() -> ExecScope
```

#### Expressions
```python
class Expr:
    """Base expression class"""

class ExprId (Expr):
    ├── getId() -> str                    # Identifier name
    └── getValue() -> str

class ExprNumber (Expr):
    ├── getValue() -> int                 # Numeric value

class ExprString (Expr):
    ├── getValue() -> str                 # String value

class ExprBool (Expr):
    ├── getVal() -> bool                  # Boolean value

class ExprBin (Expr):
    ├── getLhs() -> Expr                  # Left operand
    ├── getRhs() -> Expr                  # Right operand
    └── getOp() -> int                    # Operator code (0-18)

class ExprUnary (Expr):
    ├── getExpr() -> Expr                 # Operand
    └── getOp() -> int                    # Operator code (0-3)

class ExprCond (Expr):
    ├── getCond_e() -> Expr               # Condition
    ├── getTrue_e() -> Expr               # True branch
    └── getFalse_e() -> Expr              # False branch

class ExprRefPathContext (Expr):
    ├── getHier_id() -> TypeIdentifier    # Hierarchical identifier
    └── Methods for path resolution

class ExprCast (Expr):
    ├── getTarget_t() -> DataType
    └── getExpr() -> Expr

class ExprSubscript (Expr):
    ├── getLhs() -> Expr                  # Array
    └── getRhs() -> Expr                  # Index

class ExprBitSlice (Expr):
    ├── getLhs() -> Expr                  # Value
    ├── getLower() -> Expr                # Lower bound
    └── getUpper() -> Expr                # Upper bound
```

#### Data Types
```python
class DataType:
    """Base type class"""

class DataTypeInt (DataType):
    ├── getWidth() -> Expr | int          # Bit width
    └── getIs_signed() -> bool            # Signedness

class DataTypeBool (DataType):
    """Boolean type"""

class DataTypeString (DataType):
    """String type"""

class DataTypeUserDefined (DataType):
    ├── getType_id() -> ExprId | TypeIdentifier
    └── getParams() -> TemplateParams

class TypeIdentifier:
    """Template specialization"""
    ├── numElems() -> int
    └── getElem(i) -> TypeIdentifierElem

class TypeIdentifierElem:
    ├── getId() -> ExprId
    ├── getParams() -> TemplateParamValueList
    └── Methods for parameter access

class TemplateParamValueList:
    ├── numValues() -> int
    └── getValue(i) -> TemplateParamValue

class TemplateParamValue:
    """Base template parameter"""

class TemplateParamTypeValue (TemplateParamValue):
    └── getValue() -> DataType

class TemplateParamExprValue (TemplateParamValue):
    └── getValue() -> Expr
```

#### Statements
```python
class Stmt:
    """Base statement class"""

class ProceduralStmtReturn (Stmt):
    └── getExpr() -> Expr | None

class ProceduralStmtDataDeclaration (Stmt):
    ├── getName() -> ExprId
    ├── getDatatype() -> DataType
    └── getInit() -> Expr | None

class ProceduralStmtAssignment (Stmt):
    ├── getLhs() -> Expr
    └── getRhs() -> Expr

class ProceduralStmtIfElse (Stmt):
    ├── getIf_then(i) -> IfClause
    ├── getElse_then() -> ExecScope
    └── IfClause:
        ├── getCond() -> Expr
        └── getBody() -> ExecScope

class ProceduralStmtWhile (Stmt):
    ├── getExpr() -> Expr              # Condition
    └── getBody() -> ExecScope

class ProceduralStmtRepeat (Stmt):
    ├── getCount() -> Expr
    └── getBody() -> ExecScope

class ProceduralStmtRepeatWhile (Stmt):
    ├── getExpr() -> Expr
    └── getBody() -> ExecScope

class ProceduralStmtBreak (Stmt):
    """break; statement"""

class ProceduralStmtContinue (Stmt):
    """continue; statement"""
```

---

## 4. EXISTING TESTS - tests/python/execution/

### Test File: test_action.py

**Location**: `/home/mballance/projects/zuspec/zuspec-pss/packages/zuspec-fe-pss/tests/python/execution/test_action.py`

```python
def test_action():
    """Test action execution with body exec block"""
    content = """
import std::*;

component MyC {
  action MyA {
    bit[32] val;

    exec body {
      print("Hello World");
      val = 15;
    }
  }
}

component Top {
  MyC c1;
  MyC c2;

  exec init_down {
    c1.val = 21;
    c2.val = 22;
  }
}
"""
    # Test verifies:
    # 1. Action field declarations
    # 2. exec body blocks with statements
    # 3. Component instantiation
    # 4. exec init_down phase access to fields
```

### Test Categories

- **execution/test_action.py**: Action execution and field access
- **parsing/test_actions.py**: Action parsing features
- **parsing/test_components.py**: Component parsing
- **parsing/test_activities.py**: Activity/behavior parsing
- **parsing/test_exec_variants.py**: Different exec block types
- **parsing/test_constraints.py**: Constraint parsing
- **parsing/test_templates.py**: Template specialization
- **parsing/test_dataflow.py**: Dataflow constructs
- **parsing/test_atomic_blocks.py**: Atomic execution blocks
- **parsing/test_resources.py**: Resource definitions
- **parsing/test_coverage.py**: Coverage collection
- **source_references/test_location_tracking.py**: Source location preservation
- **performance/**: Performance benchmarks

---

## 5. test_helpers.py - Full Content

**Location**: `/home/mballance/projects/zuspec/zuspec-pss/packages/zuspec-fe-pss/tests/python/test_helpers.py`

[Content shown in detail above - 439 lines]

### Key Helper Functions:

**Parsing Helpers:**
- `parse_pss(code, filename, parser)` - Parse PSS code string
- `parse_multi_file(files, parser)` - Parse multiple PSS files
- `assert_parse_ok(code, parser_or_filename)` - Assert parsing succeeds
- `assert_parse_error(code, expected_error)` - Assert parsing fails with error

**Symbol Access Helpers:**
- `get_symbol(scope, name)` - Get symbol by name (supports qualified names with ::)
- `has_symbol(scope, name)` - Check if symbol exists
- `get_type_scope_util(scope)` - Get SymbolTypeScopeUtil
- `assert_linked(scope, name)` - Assert symbol exists and is linked

**Location Helpers:**
- `get_location(node)` - Get (line, col) from AST node
- `assert_location(node, line, col)` - Assert node location

**Code Generators (for testing):**
- `generate_actions(num_actions, with_fields, with_constraints)`
- `generate_components(num_components, nested)`
- `generate_constraints(num_constraints, field_prefix)`
- `generate_register_model(num_registers, with_fields)`
- `generate_struct_hierarchy(depth)`
- `generate_activity_parallel(num_actions)`

**Debug Helpers:**
- `print_symbol_tree(scope, indent)` - Recursively print symbol tree
- `dump_scope_symbols(scope)` - Dump all symbols in scope

---

## 6. LINKER/SYMBOL RESOLUTION

### Symbol Resolution Architecture

The linker and symbol resolution is implemented in C++ with Python interfaces:

#### Key Components in src/:

1. **AstLinker** (`AstLinker.h/cpp`)
   - Links parsed files
   - Resolves symbol references across files
   - Validates type consistency
   
   C++ Interface:
   ```cpp
   class AstLinker {
       RootSymbolScope* link(
           IMarkerCollector* markers,
           const std::vector<IGlobalScope*>& files
       );
   };
   ```

2. **NameResolver** (`NameResolver.h/cpp`)
   - Resolves hierarchical names
   - Handles symbol table lookups
   - Manages scope hierarchies

3. **AstSymbolTable** (`AstSymbolTable.h/cpp`)
   - Symbol table implementation per scope
   - Symbol lookups by name
   - Symbol iteration

4. **TaskResolveRef** (`TaskResolveRef.cpp`)
   - Resolves reference expressions
   - Validates references point to valid symbols
   - Handles import resolution

5. **TaskResolveImports** (`TaskResolveImports.h`)
   - Handles import statements
   - Manages namespace imports with wildcards

#### Python API for Symbol Resolution

```python
from zuspec.fe.pss.utils import SymbolScopeUtil, SymbolTypeScopeUtil

# Get root scope
root = parser.link()

# Create utility for scope navigation
util = SymbolScopeUtil(root)

# Get symbol by qualified name
component_a = util.getQname("module1::ComponentA")

# Get root of hierarchy
root_scope = util.getRoot()

# Get symbol extensions (for extended types)
extensions = util.getExtensions()

# For type scopes, also resolve superclass
type_util = SymbolTypeScopeUtil(component_a)
super_type = type_util.getSuper()
```

#### Symbol Table Interface

```python
class SymbolChildrenScope:
    """Scope with child symbols"""
    
    def symtabHas(name: str) -> bool:
        """Check if symbol with name exists in scope"""
        
    def symtabAt(name: str) -> int:
        """Get index of symbol in child list"""
        # Then use getChild(idx) to get the symbol
        
    def getChild(idx: int) -> Symbol:
        """Get child at index"""
        
    def numChildren() -> int:
        """Get number of children"""
        
    def children() -> Iterable[Symbol]:
        """Get all children as iterable"""
        
    def getUpper() -> SymbolChildrenScope | None:
        """Get parent scope"""
```

#### Usage Example

```python
# Parse and link
parser = Parser()
parser.parses([
    ("types.pss", """
        struct Point {
            int x;
            int y;
        }
    """),
    ("comp.pss", """
        component Top {
            Point origin;
        }
    """)
])
root = parser.link()

# Navigate symbol tree
util = SymbolScopeUtil(root)

# Get Point struct
point_type = util.getQname("Point")
print(f"Found type: {point_type.getName()}")

# Iterate fields in Point
for child in point_type.children():
    if hasattr(child, 'getType'):
        print(f"Field: {child.getName()}")

# Get Top component
top = util.getQname("Top")

# Get origin field in Top
if top.symtabHas("origin"):
    origin_idx = top.symtabAt("origin")
    origin = top.getChild(origin_idx)
    print(f"Origin type: {origin.getType()}")
```

---

## 7. CODE GENERATION - AST to IR Translation

### AST to IR Translator

**File**: `/home/mballance/projects/zuspec/zuspec-pss/packages/zuspec-fe-pss/python/zuspec/fe/pss/ast_to_ir.py` (1164 lines)

This module translates PSS AST nodes to Zuspec IR (Intermediate Representation) using zuspec.dataclasses.ir.

#### Main Classes

##### AstToIrContext
```python
class AstToIrContext:
    """Context for AST to IR translation"""
    
    def __init__(self):
        self.type_map: Dict[str, ir.DataType]        # name -> IR DataType
        self.symbol_table: Dict[str, Any]            # Symbol lookup table
        self.errors: List[str]                        # Translation errors
        self.scope_stack: List[ir.DataType]          # Scope hierarchy
        self.ir_context: Optional[ir.Context]        # IR context
        
    def push_scope(self, scope: ir.DataType):
        """Push new scope (component, struct, etc.)"""
        
    def pop_scope(self) -> Optional[ir.DataType]:
        """Pop current scope"""
        
    def current_scope(self) -> Optional[ir.DataType]:
        """Get current scope"""
        
    def add_type(self, name: str, dtype: ir.DataType):
        """Register type in type map"""
        
    def get_type(self, name: str) -> Optional[ir.DataType]:
        """Look up type by name"""
        
    def add_error(self, message: str):
        """Record translation error"""
```

##### AstToIrTranslator
```python
class AstToIrTranslator:
    """Main AST to IR translator"""
    
    def __init__(self, debug: bool = False):
        """Initialize with optional debug logging"""
        
    def translate(self, ast_root: pss_ast.GlobalScope) -> AstToIrContext:
        """Translate entire AST to IR
        
        Returns AstToIrContext with populated type_map and errors
        """
```

#### Translation Methods (Private)

**Type Translation:**
```python
def _translate_global_scope(ctx, global_scope)
def _translate_unit(ctx, unit)
def _translate_component(ctx, component) -> ir.DataTypeComponent
def _translate_action(ctx, action) -> ir.DataTypeClass
def _translate_struct(ctx, struct) -> ir.DataTypeStruct
def _translate_field(ctx, field) -> ir.Field
def _translate_function(ctx, function) -> ir.Function
def _translate_data_type(ctx, dtype_node) -> ir.DataType
def _translate_type_identifier(ctx, type_id) -> ir.DataType
def _translate_reg_c(ctx, elem) -> ir.DataTypeRegister
```

**Statement Translation:**
```python
def _translate_exec_scope(ctx, exec_scope) -> List[ir.Stmt]
def _translate_statement(ctx, stmt_node) -> ir.Stmt
def _translate_stmt_return(ctx, stmt) -> ir.StmtReturn
def _translate_stmt_declaration(ctx, stmt) -> ir.StmtAnnAssign
def _translate_stmt_assignment(ctx, stmt) -> ir.StmtAssign
def _translate_stmt_if(ctx, stmt) -> ir.StmtIf
def _translate_stmt_while(ctx, stmt) -> ir.StmtWhile
def _translate_stmt_repeat(ctx, stmt) -> ir.StmtFor
def _translate_stmt_repeat_while(ctx, stmt) -> ir.StmtWhile
```

**Expression Translation:**
```python
def _translate_expression(ctx, expr_node) -> ir.Expr
def _translate_expr_number(ctx, expr) -> ir.ExprConstant
def _translate_expr_string(ctx, expr) -> ir.ExprConstant
def _translate_expr_bool(ctx, expr) -> ir.ExprConstant
def _translate_expr_bin(ctx, expr) -> ir.ExprBin
def _translate_expr_unary(ctx, expr) -> ir.ExprUnary
def _translate_expr_cond(ctx, expr) -> ir.ExprIfExp
def _translate_expr_ref(ctx, expr) -> ir.ExprRefUnresolved
def _translate_expr_cast(ctx, expr) -> ir.ExprCast
def _translate_expr_subscript(ctx, expr) -> ir.ExprSubscript
def _translate_expr_bitslice(ctx, expr) -> ir.ExprSlice

def _map_binop(op: int) -> ir.BinOp          # Map PSS op codes to IR
def _map_unaryop(op: int) -> ir.UnaryOp
```

**Register/Register Group Generation:**
```python
def _add_register_functions(ctx, reg)
    # Generates: read(), write(val), read_val(), write_val(val)
    
def _extract_register_fields(ctx, reg)
    # Copies fields from register value type struct
    
def _add_register_group_functions(ctx, reg_group)
    # Generates: get_offset_of_instance(), get_offset_of_instance_array()
    
def _compute_register_offsets(ctx, reg_group)
    # Computes sequential register offsets with 4-byte alignment
```

#### Generated IR Types

The translator generates IR types from zuspec.dataclasses.ir:

**Component/Struct IR Types:**
- `ir.DataTypeComponent` - Component definition
- `ir.DataTypeClass` - Action definition
- `ir.DataTypeStruct` - Struct definition
- `ir.DataTypeRegister` - Register (from reg_c<> template)
- `ir.DataTypeRegisterGroup` - Register group container

**Data Type IR:**
- `ir.DataTypeInt` - Integer type (bits, signed)
- `ir.DataTypeString` - String type
- `ir.DataTypeRef` - Type reference (forward declaration)
- `ir.DataTypeArray` - Array type

**Field IR:**
- `ir.Field` - Field definition (name, type, kind)

**Function IR:**
- `ir.Function` - Function (name, args, body, returns)
- `ir.Arg` - Function argument
- `ir.Arguments` - Arguments list

**Statement IR:**
- `ir.StmtReturn` - Return statement
- `ir.StmtAssign` - Assignment
- `ir.StmtAnnAssign` - Annotated assignment (with type)
- `ir.StmtIf` - If/else statement
- `ir.StmtWhile` - While loop
- `ir.StmtFor` - For loop
- `ir.StmtBreak` - Break statement
- `ir.StmtContinue` - Continue statement

**Expression IR:**
- `ir.ExprConstant` - Literal value
- `ir.ExprBin` - Binary operation
- `ir.ExprUnary` - Unary operation
- `ir.ExprIfExp` - Ternary/conditional expression
- `ir.ExprCast` - Type cast
- `ir.ExprSubscript` - Array subscript
- `ir.ExprSlice` - Bit slice
- `ir.ExprRefUnresolved` - Unresolved reference
- `ir.ExprRefLocal` - Local reference

#### Usage Example

```python
from zuspec.fe.pss import Parser
from zuspec.fe.pss.ast_to_ir import AstToIrTranslator, AstToIrContext
from zuspec.dataclasses import ir

# Parse PSS
parser = Parser()
parser.parses([("design.pss", """
    component pss_top {
        action Setup {
            bit[32] addr;
            bit[32] data;
        }
    }
""".strip())])
ast_root = parser.link()

# Translate to IR
translator = AstToIrTranslator(debug=True)
ctx = translator.translate(ast_root)

# Access IR
for name, dtype in ctx.type_map.items():
    print(f"Type: {name}")
    if isinstance(dtype, ir.DataTypeComponent):
        print(f"  Fields: {len(dtype.fields)}")
        for field in dtype.fields:
            print(f"    - {field.name}: {field.datatype.name if hasattr(field.datatype, 'name') else field.datatype}")

# Check for errors
if ctx.errors:
    for error in ctx.errors:
        print(f"ERROR: {error}")
```

---

## 8. conftest.py - Pytest Configuration

**Location**: `/home/mballance/projects/zuspec/zuspec-pss/packages/zuspec-fe-pss/tests/python/conftest.py`

[Full content shown above - 112 lines]

### Key Fixtures

```python
@pytest.fixture(scope="session")
def factory():
    """Global factory instance (session scope)"""
    return Factory.inst()

@pytest.fixture
def parser():
    """Fresh parser for each test"""
    return Parser()

@pytest.fixture
def profiling_parser():
    """Parser with profiling enabled"""
    parser = Parser()
    parser.enable_profiling(True)
    return parser

@pytest.fixture
def debug_parser(factory):
    """Parser with debug output enabled"""
    factory.getDebugMgr().enable(True)
    parser = Parser()
    yield parser
    factory.getDebugMgr().enable(False)  # Cleanup

@pytest.fixture
def sample_component():
    """Sample component for testing"""
    return """
        component pss_top {
            action A {
                rand int x;
                constraint x > 0;
            }
        }
    """

@pytest.fixture
def multi_file_project():
    """Multi-file PSS project for import testing"""
    return [
        ("types.pss", "struct Point { int x; int y; }"),
        ("actions.pss", """
            import types::*;
            component pss_top {
                action Move { Point dest; }
            }
        """)
    ]
```

### Pytest Configuration

```python
def pytest_configure(config):
    """Configure custom pytest markers"""
    # Markers:
    # - slow: Slow tests (deselect with '-m "not slow"')
    # - profiling: Performance/profiling tests
    # - integration: Integration tests
    # - performance: Benchmarking tests
    # - source_ref: Source location preservation tests

def pytest_collection_modifyitems(config, items):
    """Automatically mark tests by location"""
    # Tests in performance/ -> marked as slow, performance
    # Tests in integration/ -> marked as integration
    # Tests in source_references/ -> marked as source_ref
```

### Running Tests

```bash
# All tests
pytest tests/python/

# Run only fast tests
pytest tests/python/ -m "not slow"

# Run profiling tests
pytest tests/python/ -m profiling

# Run specific test
pytest tests/python/test_parser.py::TestParser::test_smoke

# With verbose output
pytest tests/python/ -vv

# With debug manager enabled
# (Use debug_parser fixture in test)
```

---

## SUMMARY

### Key Takeaways

1. **Parser API**: Simple two-step process:
   - `parser.parse()` or `parser.parses()` - Parse files/strings
   - `parser.link()` - Link symbols and get symbol tree root

2. **AST Structure**: Cython-wrapped C++ AST with these key nodes:
   - Component, Action, Struct (containers)
   - Field (properties)
   - Function/FunctionDefinition (methods)
   - ExecScope (exec body { ... })
   - Various Expr and Stmt subclasses

3. **Symbol Resolution**: 
   - SymbolScopeUtil for hierarchical navigation
   - Support for qualified names (::)
   - Extension handling for extended types
   - Symbol tables per scope

4. **Code Generation**:
   - AstToIrTranslator converts PSS AST to Zuspec IR
   - Supports components, actions, structs, functions
   - Special handling for registers (reg_c<> template)
   - Full expression/statement translation

5. **Test Infrastructure**:
   - Comprehensive test helpers in test_helpers.py
   - pytest fixtures for common scenarios
   - Support for both file and string parsing
   - Marker-based test organization

6. **C++ Backend**:
   - Source in packages/zuspec-fe-pss/src/
   - ANTLR-based grammar parsing
   - Multi-phase processing (parse, link, various tasks)
   - Linker resolves cross-file references
