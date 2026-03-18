# PSS v3.0 Feature Checklist — zuspec-pss Implementation Status

This document provides a comprehensive checklist of every feature defined in the **Portable Test and Stimulus Standard v3.0 (August 2024)** and tracks its implementation status within the zuspec-pss codebase. It covers parsing (AST), intermediate representation (IR via zuspec-dataclasses), AST-to-IR translation (ast_to_ir.py), and runtime generation. Use this to guide implementation priorities and track progress.

## Feature Implementation
- ensure each feature can be implement in the Zuspec front-end (packages/zuspec-dataclass) 
- ensure each feature can be implemented in the Zuspec IR 
- ensure each feature works via the Zuspec Runtime when the Zuspec front-end is used
- ensure each feature is properly mapped from PSS source to Zuspec IR, and is properly implemented by the runtime  

Note that this implies several tests for each feature:
- Zuspec front-end -> IR
- Zuspec front-end -> RT
- PSS front-end -> IR
- IR -> RT

## Legend

| Symbol | Meaning |
|--------|---------|
| ✅ Complete | Feature is fully handled: AST → IR → runtime path works |
| 🔶 Partial | Some support exists but has specific gaps (noted in parentheses) |
| ❌ Not Started | No implementation found in the current codebase |

---

## 1. Lexical Conventions (LRM §4)

| Feature | LRM Section | PSS Example | Python/zuspec Equivalent | Complexity | Status |
|---------|-------------|-------------|--------------------------|------------|--------|
| Single-line comments (`//`) | §4.1 | `// comment` | `# comment` | Simple | ✅ Complete |
| Block comments (`/* */`) | §4.1 | `/* comment */` | `# comment` | Simple | ✅ Complete |
| Identifiers | §4.2 | `my_var` | `my_var` | Simple | ✅ Complete |
| Escaped identifiers | §4.3 | `\busa+index` | N/A (no equivalent) | Medium | ❌ Not Started |
| Keywords (Table 3) | §4.4 | `action`, `struct`, etc. | decorators/classes | Simple | ✅ Complete |
| Operators | §4.5 | `+`, `-`, `*`, `==`, etc. | same operators | Simple | ✅ Complete |
| Integer constants (decimal) | §4.6.1 | `42` | `42` | Simple | ✅ Complete |
| Integer constants (hex) | §4.6.1 | `0xFF` | `0xFF` | Simple | ✅ Complete |
| Integer constants (octal) | §4.6.1 | `0777` | `0o777` | Simple | ✅ Complete |
| Integer constants (binary) | §4.6.1 | `0b1010` | `0b1010` | Simple | ✅ Complete |
| Based integer literals | §4.6.1 | `8'hFF`, `4'sd12` | N/A | Medium | 🔶 Partial (parsed but based-size semantics limited) |
| Floating-point constants | §4.6.2 | `20.14`, `2e6` | `20.14`, `2e6` | Simple | ✅ Complete |
| Quoted string literals | §4.7 | `"hello"` | `"hello"` | Simple | ✅ Complete |
| Triple-quoted string literals | §4.7 | `"""multi\nline"""` | `"""multi\nline"""` | Simple | 🔶 Partial (parsed; target-template usage not fully supported) |
| Empty aggregate literal | §4.8.1 | `{}` | `{}` | Simple | ✅ Complete (translates to ExprList with no elements) |
| Value list literal | §4.8.2 | `{1, 2, 3}` | `[1, 2, 3]` | Simple | ✅ Complete (translates to ExprList) |
| Map literal | §4.8.3 | `{1:true, 2:false}` | `{1: True, 2: False}` | Medium | ✅ Complete (translates to ExprDict) |
| Structure literal | §4.8.4 | `{.a=1, .b=2}` | `MyStruct(a=1, b=2)` | Medium | ✅ Complete (translates to ExprStructLiteral) |

---

## 2. Data Types (LRM §7)

### 2.1 Scalar Data Types

| Feature | LRM Section | PSS Example | Python/zuspec Equivalent | Complexity | Status |
|---------|-------------|-------------|--------------------------|------------|--------|
| int (signed, unsized) | §7.2 | `int x;` | `DataTypeInt(is_signed=True)` | Simple | ✅ Complete |
| int (signed, sized) | §7.2 | `int[15:0] x;` | `DataTypeInt(width=16, is_signed=True)` | Simple | ✅ Complete |
| bit (unsigned, sized) | §7.2 | `bit[31:0] x;` | `DataTypeInt(width=32, is_signed=False)` | Simple | ✅ Complete |
| bool type | §7.4 | `bool flag;` | `bool` (looked up in type_map) | Simple | ✅ Complete |
| string type | §7.6 | `string s;` | `DataTypeString()` | Simple | ✅ Complete |
| String sub-string operator | §7.6 / §8.6.3 | `s[2..5]` | `s[2:6]` | Medium | ⚠️ Partial (PSS frontend emits subscript, not ExprSubstring) |
| String methods (size, etc.) | §7.6 | `s.size()` | `len(s)` | Medium | ✅ Complete |
| float32 type | §7.3 | `float32 f;` | N/A | Medium | ❌ Not Started |
| float64 type | §7.3 | `float64 f;` | N/A | Medium | ❌ Not Started |
| chandle type | §7.7 | `chandle ptr;` | `ctypes.c_void_p` | Medium | ✅ Complete |
| enum declaration | §7.5 | `enum color_e {RED, GREEN, BLUE};` | `class color_e(Enum)` | Medium | ✅ Complete |
| enum with explicit values | §7.5 | `enum e {A=1, B=5};` | `class e(IntEnum): A=1; B=5` | Medium | ✅ Complete |
| typedef | §7.11 | `typedef bit[31:0] uint32_t;` | `uint32_t = DataTypeInt(32)` | Simple | ✅ Complete |

### 2.2 Collections

| Feature | LRM Section | PSS Example | Python/zuspec Equivalent | Complexity | Status |
|---------|-------------|-------------|--------------------------|------------|--------|
| Fixed-size array (square) | §7.9.2 | `int arr[16];` | `arr: List[int]  # fixed` | Medium | ✅ Complete |
| Fixed-size array (template) | §7.9.2 | `array<int, 16> arr;` | `arr: List[int]  # fixed` | Medium | ✅ Complete |
| Array operators ([], ==, !=, in) | §7.9.2.1 | `arr[0]`, `x in arr` | `arr[0]`, `x in arr` | Medium | ✅ Complete (`[]` subscript via ExprSubscript; `==`/`!=` via ExprBin) |
| Array methods (size, sum, join, to_list, to_set) | §7.9.2.2 | `arr.size()`, `arr.sum()` | `len(arr)`, `sum(arr)` | Medium | ✅ Complete (method calls translate to ExprCall via ExprAttribute chain) |
| List declaration | §7.9.3 | `list<int> l;` | `l: List[int] = []` | Medium | ✅ Complete |
| List operators ([], ==, !=, in) | §7.9.3.1 | `l[0]`, `x in l` | `l[0]`, `x in l` | Medium | ✅ Complete (`[]` subscript and `==`/`!=` comparisons work) |
| List methods (push_back, pop_front, insert, delete, clear, size, shuffle) | §7.9.3.2 | `l.push_back(5);` | `l.append(5)` | Medium | ✅ Complete (method calls translate to ExprCall with correct name/args) |
| Map declaration | §7.9.4 | `map<string, int> m;` | `m: Dict[str, int] = {}` | Medium | ✅ Complete |
| Map operators ([], ==, !=) | §7.9.4.1 | `m["key"]` | `m["key"]` | Medium | ✅ Complete (subscript and comparisons work) |
| Map methods (size, clear, delete, keys, values, contains) | §7.9.4.2 | `m.size()`, `m.keys()` | `len(m)`, `m.keys()` | Medium | ✅ Complete (method calls translate correctly) |
| Set declaration | §7.9.5 | `set<int> s;` | `s: Set[int] = set()` | Medium | ✅ Complete |
| Set operators (in, ==, !=) | §7.9.5.1 | `x in s` | `x in s` | Medium | 🔶 Partial (`==`/`!=` work; `x in s` in exec body limited by PSS frontend) |
| Set methods (size, clear, delete, to_list, add) | §7.9.5.2 | `s.add(5);` | `s.add(5)` | Medium | ✅ Complete (method calls translate correctly) |

### 2.3 Reference Types

| Feature | LRM Section | PSS Example | Python/zuspec Equivalent | Complexity | Status |
|---------|-------------|-------------|--------------------------|------------|--------|
| Reference type declaration | §7.10 | `ref my_comp c;` | N/A | Complex | ❌ Not Started |
| Reference assignment/null | §7.10 | `c = null;` | `c = None` | Medium | ✅ Complete (`null` translates to ExprNull) |
| Collection of references | §7.10.1 | `list<ref my_comp> cl;` | N/A | Complex | ❌ Not Started |
| Reference downcasting | §7.12 | `(ref sub_C)comp` | `cast(sub_C, comp)` | Complex | ❌ Not Started |

### 2.4 Data Type Conversion

| Feature | LRM Section | PSS Example | Python/zuspec Equivalent | Complexity | Status |
|---------|-------------|-------------|--------------------------|------------|--------|
| Cast expression (numeric) | §7.12 | `(bit[3:0])val` | `int(val) & 0xF` | Medium | ✅ Complete |
| Cast expression (enum) | §7.12 | `(config_modes_e)11` | `config_modes_e(11)` | Medium | ✅ Complete |
| Cast expression (reference) | §7.12 | `(ref sub_C)comp` | N/A | Complex | ❌ Not Started |

---

## 3. Operators and Expressions (LRM §8)

| Feature | LRM Section | PSS Example | Python/zuspec Equivalent | Complexity | Status |
|---------|-------------|-------------|--------------------------|------------|--------|
| Arithmetic operators (+, -, *, /, %) | §8.5.1 | `a + b * c` | `a + b * c` | Simple | ✅ Complete |
| Power operator (**) | §8.5.1 | `a ** b` | `a ** b` | Simple | ✅ Complete |
| Relational operators (<, >, <=, >=) | §8.5.2 | `a < b` | `a < b` | Simple | ✅ Complete |
| Equality operators (==, !=) | §8.5.3 | `a == b` | `a == b` | Simple | ✅ Complete |
| Logical operators (&&, \|\|, !) | §8.5.4 | `a && b` | `a and b` | Simple | ✅ Complete |
| Bitwise operators (&, \|, ^, ~) | §8.5.5 | `a & 0xFF` | `a & 0xFF` | Simple | ✅ Complete |
| Reduction operators (unary &, \|, ^) | §8.5.6 | `&val` | N/A (custom) | Medium | ❌ Not Started |
| Shift operators (<<, >>) | §8.5.7 | `a << 2` | `a << 2` | Simple | ✅ Complete |
| Conditional (ternary) operator | §8.5.8 | `c ? a : b` | `a if c else b` | Simple | ✅ Complete |
| Set membership (in) - value set | §8.5.9 | `x in [1, 2, 3..10]` | `x in range(1,11)` | Medium | ✅ Complete (PSS C++ parser ExprIn fixed; ast_to_ir ExprIn translation; solver InConstraint domain restriction) |
| Set membership (in) - collection | §8.5.9 | `x in my_list` | `x in my_list` | Medium | 🔶 Partial (PSS frontend returns None for `in` expr in exec body; constraint context also limited) |
| Assignment operator (=) | §8.3 | `x = 5;` | `x = 5` | Simple | ✅ Complete |
| Compound assignment (+=, -=, etc.) | §8.3 | `x += 1;` | `x += 1` | Simple | ✅ Complete |
| Bit-select | §8.6.1 | `val[3]` | `(val >> 3) & 1` | Medium | ✅ Complete |
| Part-select | §8.6.1 | `val[7:4]` | `(val >> 4) & 0xF` | Medium | ✅ Complete |
| Index operator on collection | §8.6.2 | `arr[i]` | `arr[i]` | Simple | ✅ Complete |
| Sub-string operator | §8.6.3 | `s[2..5]` | `s[2:6]` | Medium | ❌ Not Started |
| Function call expression | §8.6 | `foo(a, b)` | `foo(a, b)` | Simple | ✅ Complete |
| Aggregate literals in expressions | §8.4.2 | `s == {.a=1, .b=2}` | N/A | Complex | ✅ Complete (struct/list/map/empty literals translate to ExprStructLiteral/ExprList/ExprDict) |
| Operator precedence (Table 10) | §8.4.1 | standard | standard | Simple | ✅ Complete |

---

## 4. Components (LRM §9)

| Feature | LRM Section | PSS Example | Python/zuspec Equivalent | Complexity | Status |
|---------|-------------|-------------|--------------------------|------------|--------|
| Component declaration | §9.1 | `component my_c { }` | `class my_c(Component)` | Medium | ✅ Complete (fields, exec blocks all translated) |
| Component instantiation | §9.4 | `my_c inst1;` | `inst1 = my_c()` | Medium | 🔶 Partial (fields yes; component tree construction partial) |
| Component arrays | §9.4 | `my_c insts[4];` | `insts = [my_c() for _ in range(4)]` | Medium | ✅ Complete |
| Component as namespace | §9.3 | `component C { action A {} }` | `class C: class A: ...` | Medium | ✅ Complete |
| Component inheritance | §9.1 | `component sub_c : base_c { }` | `class sub_c(base_c)` | Medium | ✅ Complete (TypeIdentifier super resolved correctly) |
| Component data fields | §9.1 | `int f;` (in component) | `self.f: int` | Simple | ✅ Complete |
| Component reference (comp) | §9.5 | `comp.field` | `self.comp.field` | Medium | ✅ Complete |
| Pure components | §9.6 | `pure component reg { }` | `class reg(PureComponent)` | Medium | 🔶 Partial (reg_c specialization works) |
| Component functions | §9.1 | `function void foo();` (in component) | `def foo(self): ...` | Medium | 🔶 Partial (function declarations translated) |
| Component exec blocks (init, init_down, init_up) | §22.1 | `exec init_down { ... }` | `def init_down(self): ...` | Complex | ✅ Complete (init/init_up → `init_up`; init_down, run_start, run_end all translated) |

---

## 5. Actions (LRM §10)

| Feature | LRM Section | PSS Example | Python/zuspec Equivalent | Complexity | Status |
|---------|-------------|-------------|--------------------------|------------|--------|
| Action declaration | §10.1 | `action my_a { }` | `class my_a(Action)` | Medium | ✅ Complete (fields, constraints, exec blocks all translated) |
| Atomic action | §10.2.1 | `action write { exec body {...} }` | `class write(Action): async def body()` | Medium | ✅ Complete (exec body translated to IR Function) |
| Compound action | §10.2.2 | `action compound { activity {...} }` | N/A (activity not yet in IR) | Complex | ❌ Not Started |
| Abstract action | §10.2.3 | `abstract action base { }` | `class base(Action, abstract=True)` | Medium | ✅ Complete (`is_abstract` flag set in IR) |
| Action inheritance | §10.1 | `action derived : base { }` | `class derived(base)` | Medium | ✅ Complete (super resolved via TypeIdentifier) |
| Action data fields (rand) | §10.1 | `rand int size;` | `self.size = RandInt()` | Simple | ✅ Complete |
| Action data fields (non-rand) | §10.1 | `int count;` | `self.count: int` | Simple | ✅ Complete |
| Action field (action handle) | §10.1 | `A a1;` (sub-action handle) | N/A | Complex | ❌ Not Started |
| Action random variable field | §10.1 | `action bit[3:0] max;` | N/A | Complex | ❌ Not Started |
| Input flow object field | §13.4 | `input data_buf data;` | N/A | Complex | ❌ Not Started |
| Output flow object field | §13.4 | `output data_buf data;` | N/A | Complex | ❌ Not Started |
| Lock resource field | §14.2 | `lock my_resource r;` | N/A | Complex | ❌ Not Started |
| Share resource field | §14.2 | `share my_resource r;` | N/A | Complex | ❌ Not Started |
| Action exec pre_solve | §22.1 | `exec pre_solve { ... }` | `def pre_solve(self): ...` | Medium | ✅ Complete |
| Action exec post_solve | §22.1 | `exec post_solve { ... }` | `def post_solve(self): ...` | Medium | ✅ Complete |
| Action exec body | §22.1.2 | `exec body { ... }` | `async def body(self): ...` | Medium | ✅ Complete |
| Action exec pre_body | §22.1.2 | `exec pre_body { ... }` | `def pre_body(self): ...` | Medium | ❌ Not Started (PSS frontend rejects "pre_body" as invalid exec-block kind) |
| Action exec header | §22.1.2 | `exec header "C" { ... }` | N/A (target code gen) | Complex | ❌ Not Started |
| Action exec declaration | §22.1.2 | `exec declaration "C" { ... }` | N/A (target code gen) | Complex | ❌ Not Started |
| Action exec run_start | §22.1.2 | `exec run_start { ... }` | `def run_start(self): ...` | Medium | ✅ Complete |
| Action exec run_end | §22.1.2 | `exec run_end { ... }` | `def run_end(self): ...` | Medium | ✅ Complete |
| Action override declaration | §20.5 | `override { type A with B; }` | N/A | Complex | ❌ Not Started |
| Action covergroup instantiation | §18.2 | `my_cg cg1;` (in action) | N/A | Complex | ❌ Not Started |

---

## 6. Struct Types (LRM §7.8)

| Feature | LRM Section | PSS Example | Python/zuspec Equivalent | Complexity | Status |
|---------|-------------|-------------|--------------------------|------------|--------|
| Struct declaration | §7.8 | `struct my_s { int a; }` | `class my_s(Struct)` | Simple | ✅ Complete |
| Struct fields | §7.8 | `rand bit[31:0] addr;` | `self.addr = RandBitVec(32)` | Simple | ✅ Complete |
| Struct inheritance | §7.8 | `struct sub_s : base_s { }` | `class sub_s(base_s)` | Medium | ✅ Complete (super resolved via TypeIdentifier) |
| Struct constraints | §16.1.1 | `constraint addr < 0x1000;` | `ir.Function(_is_constraint=True)` | Medium | ✅ Complete |
| Struct exec blocks (pre_solve, post_solve) | §22.1 | `exec pre_solve { ... }` | `def pre_solve(self): ...` | Medium | ✅ Complete |
| Struct covergroups | §18.1 | `covergroup cg { ... }` (in struct) | N/A | Complex | ❌ Not Started |
| Abstract struct | §7.8 | `abstract struct base { }` | N/A | Medium | ❌ Not Started (PSS frontend does not support; only abstract action is valid) |

---

## 7. Flow Objects (LRM §13)

| Feature | LRM Section | PSS Example | Python/zuspec Equivalent | Complexity | Status |
|---------|-------------|-------------|--------------------------|------------|--------|
| Buffer declaration | §13.1 | `buffer data_buf { rand bit[31:0] data; }` | N/A | Complex | ❌ Not Started |
| Buffer with inheritance | §13.1 | `buffer ext_buf : data_buf { }` | N/A | Complex | ❌ Not Started |
| Stream declaration | §13.2 | `stream ctrl_s { }` | N/A | Complex | ❌ Not Started |
| State declaration | §13.3 | `state machine_state { }` | N/A | Complex | ❌ Not Started |
| State `initial` attribute | §13.3 | `initial` (built-in bool) | N/A | Complex | ❌ Not Started |
| State `prev` reference | §13.3 | `prev.field` | N/A | Complex | ❌ Not Started |
| Input flow object field | §13.4 | `input data_buf d;` | N/A | Complex | ❌ Not Started |
| Output flow object field | §13.4 | `output data_buf d;` | N/A | Complex | ❌ Not Started |
| Flow object arrays | §13.4 | `input data_buf d[4];` | N/A | Complex | ❌ Not Started |

---

## 8. Resource Objects (LRM §14)

| Feature | LRM Section | PSS Example | Python/zuspec Equivalent | Complexity | Status |
|---------|-------------|-------------|--------------------------|------------|--------|
| Resource declaration | §14.1 | `resource dma_chan { }` | N/A | Complex | ❌ Not Started |
| Resource `instance_id` | §14.1 | `instance_id` (built-in) | N/A | Complex | ❌ Not Started |
| Resource inheritance | §14.1 | `resource sub_r : base_r { }` | N/A | Complex | ❌ Not Started |
| Lock resource claim | §14.2 | `lock dma_chan ch;` | N/A | Complex | ❌ Not Started |
| Share resource claim | §14.2 | `share dma_chan ch;` | N/A | Complex | ❌ Not Started |
| Resource claim arrays | §14.2 | `lock dma_chan ch[2];` | N/A | Complex | ❌ Not Started |

---

## 9. Pools & Binding (LRM §15)

| Feature | LRM Section | PSS Example | Python/zuspec Equivalent | Complexity | Status |
|---------|-------------|-------------|--------------------------|------------|--------|
| Pool declaration | §15.1 | `pool data_buf buf_p;` | N/A | Complex | ❌ Not Started |
| Pool with size (resource) | §15.1 | `pool [4] dma_chan ch_p;` | N/A | Complex | ❌ Not Started |
| Explicit pool binding | §15.3 | `bind buf_p a.data;` | N/A | Complex | ❌ Not Started |
| Default pool binding (wildcard) | §15.3 | `bind buf_p *;` | N/A | Complex | ❌ Not Started |
| Resource pool instance_id | §15.4 | `instance_id` unique per pool | N/A | Complex | ❌ Not Started |
| State pool with initial | §15.5 | `initial` attribute on first state | N/A | Complex | ❌ Not Started |

---

## 10. Template Types (LRM §11)

| Feature | LRM Section | PSS Example | Python/zuspec Equivalent | Complexity | Status |
|---------|-------------|-------------|--------------------------|------------|--------|
| Template type declaration | §11.2 | `struct my_s <type T> { T attr; }` | `class my_s(Generic[T])` | Complex | 🔶 Partial (IR TemplateParam/DataTypeParameterized exist; limited AST translation) |
| Template value parameter | §11.3.1 | `action a <int N> { lock r res[N]; }` | N/A | Complex | 🔶 Partial (IR TemplateParamValue exists) |
| Template type parameter (generic) | §11.3.2 | `struct s <type T> { T f; }` | `Generic[T]` | Complex | 🔶 Partial (IR TemplateParamType exists) |
| Template type parameter (category) | §11.3.2 | `struct s <struct T> { T f; }` | N/A | Complex | ❌ Not Started |
| Template type restriction | §11.3.2 | `<buffer B : base_t>` | N/A | Very Complex | ❌ Not Started |
| Template type instantiation | §11.4 | `my_s<int> inst;` | `my_s[int]()` | Complex | 🔶 Partial (reg_c specialization works; general case limited) |
| Template default parameters | §11.3 | `<int N = 4>` | N/A | Medium | 🔶 Partial (IR supports defaults) |
| Template type extension | §20.2.6 | `extend struct my_s<int> { }` | N/A | Very Complex | ❌ Not Started |

---

## 11. Activity (LRM §12)

### 11.1 Activity Declarations & Traversal

| Feature | LRM Section | PSS Example | Python/zuspec Equivalent | Complexity | Status |
|---------|-------------|-------------|--------------------------|------------|--------|
| Activity declaration | §12.1 | `activity { ... }` | N/A | Complex | ❌ Not Started |
| Action traversal (named handle) | §12.3.1 | `a1;` (in activity) | N/A | Complex | ❌ Not Started |
| Action traversal (anonymous/do) | §12.3.1 | `do A;` | N/A | Complex | ❌ Not Started |
| Action traversal with in-line constraints | §12.3.1 | `do A with { f1 < 10; };` | N/A | Complex | ❌ Not Started |
| Labeled action traversal | §12.3.1 | `lbl: do A;` | N/A | Complex | ❌ Not Started |
| Action handle array traversal | §12.3.2 | `a_arr;` (entire array) | N/A | Complex | ❌ Not Started |

### 11.2 Scheduling Blocks

| Feature | LRM Section | PSS Example | Python/zuspec Equivalent | Complexity | Status |
|---------|-------------|-------------|--------------------------|------------|--------|
| Sequential block (implicit) | §12.3.3 | `{ a; b; }` | N/A | Complex | ❌ Not Started |
| Sequential block (explicit) | §12.3.3 | `sequence { a; b; }` | N/A | Complex | ❌ Not Started |
| Parallel block | §12.3.4 | `parallel { a; b; }` | N/A | Complex | ❌ Not Started |
| Schedule block | §12.3.5 | `schedule { a; b; }` | N/A | Complex | ❌ Not Started |
| join_branch | §12.3.6 | `parallel join_branch(L1) { ... }` | N/A | Very Complex | ❌ Not Started |
| join_select | §12.3.6 | `parallel join_select(2) { ... }` | N/A | Very Complex | ❌ Not Started |
| join_none | §12.3.6 | `parallel join_none { ... }` | N/A | Very Complex | ❌ Not Started |
| join_first | §12.3.6 | `parallel join_first(1) { ... }` | N/A | Very Complex | ❌ Not Started |
| Atomic block | §12.3.7 | `atomic { do A; do B; }` | N/A | Very Complex | ❌ Not Started |

### 11.3 Activity Control Flow

| Feature | LRM Section | PSS Example | Python/zuspec Equivalent | Complexity | Status |
|---------|-------------|-------------|--------------------------|------------|--------|
| repeat (count) | §12.4.1 | `repeat (10) { do A; }` | N/A | Complex | ❌ Not Started |
| repeat (count with index) | §12.4.1 | `repeat (i : 10) { do A; }` | N/A | Complex | ❌ Not Started |
| repeat-while | §12.4.2 | `repeat { do A; } while (cond);` | N/A | Complex | ❌ Not Started |
| foreach (in activity) | §12.4.3 | `foreach (e : my_list) { do A; }` | N/A | Complex | ❌ Not Started |
| select | §12.4.4 | `select { do A; do B; }` | N/A | Complex | ❌ Not Started |
| select with guards/weights | §12.4.4 | `select { (cond, 2): do A; }` | N/A | Very Complex | ❌ Not Started |
| if-else (in activity) | §12.4.5 | `if (cond) do A; else do B;` | N/A | Complex | ❌ Not Started |
| match (in activity) | §12.4.6 | `match (v) { [1,2]: do A; }` | N/A | Complex | ❌ Not Started |

### 11.4 Activity Construction

| Feature | LRM Section | PSS Example | Python/zuspec Equivalent | Complexity | Status |
|---------|-------------|-------------|--------------------------|------------|--------|
| replicate | §12.5.1 | `replicate (i:4) do A;` | N/A | Complex | ❌ Not Started |
| replicate with label array | §12.5.1 | `replicate (i:4) arr[]: do A;` | N/A | Very Complex | ❌ Not Started |
| Symbol declaration | §12.7 | `symbol sym1 { do A; do B; }` | N/A | Complex | ❌ Not Started |
| Named sub-activities | §12.8 | `lbl: { do A; do B; }` | N/A | Complex | ❌ Not Started |
| Activity bind (flow objects) | §12.9 | `bind a.out b.in;` | N/A | Complex | ❌ Not Started |

### 11.5 Activity Evaluation with Extension/Inheritance

| Feature | LRM Section | PSS Example | Python/zuspec Equivalent | Complexity | Status |
|---------|-------------|-------------|--------------------------|------------|--------|
| Activity in extended actions | §12.6 | `extend action A { activity {...} }` | N/A | Very Complex | ❌ Not Started |
| Activity shadowing with super | §12.6 | `activity { super; do B; }` | N/A | Very Complex | ❌ Not Started |

---

## 12. Constraints (LRM §16)

### 12.1 Algebraic Constraints

| Feature | LRM Section | PSS Example | Python/zuspec Equivalent | Complexity | Status |
|---------|-------------|-------------|--------------------------|------------|--------|
| Static member constraint (unnamed) | §16.1.1 | `constraint x > 0;` | `ir.Function(_is_constraint=True)` | Medium | ✅ Complete (translated to IR Function with _is_constraint metadata) |
| Static member constraint (named) | §16.1.1 | `constraint c1 { x > 0; }` | `ir.Function(_is_constraint=True)` | Medium | ✅ Complete (named constraints preserve block name) |
| Dynamic constraint | §16.1.1 | `dynamic constraint dc { x > 5; }` | N/A | Complex | ❌ Not Started |
| Constraint inheritance | §16.1.2 | derived inherits base constraints | N/A | Complex | ❌ Not Started |
| In-line constraints (action traversal) | §16.1.3 | `do A with { f1 < 10; };` | N/A | Complex | ❌ Not Started |
| Logical expression constraint | §16.1.4 | `constraint x > 0 && x < 100;` | N/A | Medium | ✅ Complete (translates as ExprBin inside constraint body) |
| Implication constraint (->) | §16.1.5 | `constraint a -> b > 5;` | N/A | Complex | ✅ Complete (translates to StmtExpr with ExprCall(implies,...)) |
| if-else constraint | §16.1.6 | `constraint if (a) { b > 5; }` | N/A | Complex | ✅ Complete (translates to StmtIf inside constraint body) |
| foreach constraint | §16.1.7 | `constraint foreach (e:l) { e>0; }` | `StmtForeach` | Complex | ✅ Complete (C++ parser wires to scope; ast_to_ir StmtForeach; solver expands per array element; rand DataTypeArray fields supported) |
| forall constraint | §16.1.8 | `forall (a:A) { a.f>0; }` | N/A | Very Complex | ❌ Not Started |
| Unique constraint | §16.1.9 | `unique { a, b, c };` | `StmtUnique` | Medium | ✅ Complete (C++ parser fixed to push to scope; ast_to_ir StmtUnique; solver UniquePropagator) |
| Default value constraint | §16.1.10 | `default x == 5;` | N/A | Complex | ❌ Not Started |
| Default disable | §16.1.10 | `default disable x;` | N/A | Complex | ❌ Not Started |
| Distribution directive (dist) | §16.1.11 | `dist x in [0..10 := 5];` | N/A | Complex | ❌ Not Started |
| In-set constraint | §8.5.9 | `constraint x in [1, 2, 3..10];` | N/A | Medium | ❌ Not Started |
| In-range constraint | §8.5.9 | `constraint x in [0..0xFFFF];` | N/A | Medium | ❌ Not Started |

### 12.2 Scheduling Constraints

| Feature | LRM Section | PSS Example | Python/zuspec Equivalent | Complexity | Status |
|---------|-------------|-------------|--------------------------|------------|--------|
| Scheduling constraint (sequence) | §16.2 | `constraint { a, b ; sequence }` | N/A | Very Complex | ❌ Not Started |
| Scheduling constraint (parallel) | §16.2 | `constraint { a, b ; parallel }` | N/A | Very Complex | ❌ Not Started |

### 12.3 Randomization Process

| Feature | LRM Section | PSS Example | Python/zuspec Equivalent | Complexity | Status |
|---------|-------------|-------------|--------------------------|------------|--------|
| Struct rand fields | §16.4.1 | `rand bit[3:0] x;` | `self.x = RandBit(4)` | Simple | ✅ Complete |
| Action rand fields | §16.4.1 | `rand int size;` | `self.size = RandInt()` | Simple | ✅ Complete |
| Randomization of lists | §16.4.2 | `rand list<int> l;` | N/A | Complex | ❌ Not Started |
| Randomization of flow objects | §16.4.3 | (implicit binding) | N/A | Very Complex | ❌ Not Started |
| Randomization of resource objects | §16.4.4 | (implicit binding) | N/A | Very Complex | ❌ Not Started |
| Randomization of component assignment | §16.4.5 | `comp` field assignment | N/A | Very Complex | ❌ Not Started |
| Procedural randomization | §16.4.6 | `randomize x with { x > 5; }` | N/A | Complex | ❌ Not Started |
| Sequencing constraints on states | §16.3 | `prev.val == val;` (state constraint) | N/A | Very Complex | ❌ Not Started |

---

## 13. Action Inferencing (LRM §17)

| Feature | LRM Section | PSS Example | Python/zuspec Equivalent | Complexity | Status |
|---------|-------------|-------------|--------------------------|------------|--------|
| Implicit binding and inference | §17.1 | (tool infers actions for flow) | N/A | Very Complex | ❌ Not Started |
| Object pool inference | §17.2 | (tool selects from pools) | N/A | Very Complex | ❌ Not Started |
| Data constraint inference | §17.3 | (constraints affect inference) | N/A | Very Complex | ❌ Not Started |

---

## 14. Data Coverage (LRM §18)

| Feature | LRM Section | PSS Example | Python/zuspec Equivalent | Complexity | Status |
|---------|-------------|-------------|--------------------------|------------|--------|
| Covergroup declaration | §18.1 | `covergroup cg { ... }` | IR: `CovergroupDef` | Complex | 🔶 Partial (IR classes exist; no AST→IR translation) |
| Covergroup with parameters | §18.1 | `covergroup cg(int x) { ... }` | N/A | Complex | ❌ Not Started |
| Covergroup instantiation | §18.2 | `cg cg_inst;` | N/A | Complex | ❌ Not Started |
| Inline covergroup instance | §18.2 | `covergroup { ... } cg_inst;` | N/A | Complex | ❌ Not Started |
| Coverpoint declaration | §18.3 | `coverpoint x;` | IR: `CoverpointDef` | Complex | 🔶 Partial (IR exists; no AST→IR) |
| Coverpoint with iff condition | §18.3 | `coverpoint x iff (en);` | N/A | Complex | ❌ Not Started |
| Coverpoint bins | §18.3.3 | `bins b1 = {[0..10]};` | IR: `BinDef` | Complex | 🔶 Partial (IR exists; no AST→IR) |
| Coverpoint ignore_bins | §18.3.5 | `ignore_bins ib = {5};` | N/A | Complex | ❌ Not Started |
| Coverpoint illegal_bins | §18.3.6 | `illegal_bins ilb = {99};` | N/A | Complex | ❌ Not Started |
| Coverpoint auto bins | §18.3.4 | (automatic bin creation) | N/A | Complex | ❌ Not Started |
| Cross coverage | §18.4 | `cross x, y;` | IR: `CrossDef` | Complex | 🔶 Partial (IR exists; no AST→IR) |
| Cross bins | §18.4 | `bins cb = x with (y > 5);` | IR: `CrossBinDef` | Complex | 🔶 Partial (IR exists; no AST→IR) |
| Covergroup options (weight, goal, etc.) | §18.5 | `option.weight = 2;` | IR: `CovergroupOptions` | Medium | 🔶 Partial (IR exists; no AST→IR) |
| Covergroup sampling | §18.6 | (automatic at action completion) | N/A | Complex | ❌ Not Started |
| Per-type coverage | §18.7 | (default mode) | N/A | Complex | ❌ Not Started |
| Per-instance coverage | §18.7 | `option.per_instance = true;` | N/A | Complex | ❌ Not Started |

---

## 15. Behavioral Coverage & Monitors (LRM §19)

| Feature | LRM Section | PSS Example | Python/zuspec Equivalent | Complexity | Status |
|---------|-------------|-------------|--------------------------|------------|--------|
| Monitor declaration | §19.1 | `monitor my_mon { ... }` | N/A | Very Complex | ❌ Not Started |
| Abstract monitor | §19.1 | `abstract monitor base_mon { }` | N/A | Very Complex | ❌ Not Started |
| Cover statement | §19.1 | `cover my_mon;` | N/A | Very Complex | ❌ Not Started |
| Cover inline monitor | §19.1 | `cover { activity { ... } }` | N/A | Very Complex | ❌ Not Started |
| Monitor action traversal | §19.3.1 | `do A;` (in monitor) | N/A | Very Complex | ❌ Not Started |
| Sequential scenario | §19.3.2 | `sequence { do A; do B; }` | N/A | Very Complex | ❌ Not Started |
| Concatenation scenario | §19.3.3 | `concat { do A; do B; }` | N/A | Very Complex | ❌ Not Started |
| Eventuality scenario | §19.3.4 | `eventually do A;` | N/A | Very Complex | ❌ Not Started |
| Overlapping scenario | §19.3.5 | `overlap { do A; do B; }` | N/A | Very Complex | ❌ Not Started |
| Selection scenario | §19.3.6 | `select { do A; do B; }` (in monitor) | N/A | Very Complex | ❌ Not Started |
| Scheduling scenario | §19.3.8 | `schedule { do A; do B; }` (in monitor) | N/A | Very Complex | ❌ Not Started |
| Monitor traversal | §19.3.9 | `do my_mon;` | N/A | Very Complex | ❌ Not Started |
| Monitor constraints | §19.4 | `constraint a.f1 > 0;` (in monitor) | N/A | Very Complex | ❌ Not Started |
| Covergroup in monitor | §19.5 | `covergroup { ... }` (in monitor) | N/A | Very Complex | ❌ Not Started |
| Monitor inheritance | §19.6 | `monitor sub_m : base_m { }` | N/A | Very Complex | ❌ Not Started |

---

## 16. Type Inheritance, Extension & Overrides (LRM §20)

| Feature | LRM Section | PSS Example | Python/zuspec Equivalent | Complexity | Status |
|---------|-------------|-------------|--------------------------|------------|--------|
| Struct inheritance | §20.1 | `struct sub_s : base_s { }` | `class sub_s(base_s)` | Medium | 🔶 Partial (basic hierarchy) |
| Action inheritance | §20.1 | `action sub_a : base_a { }` | `class sub_a(base_a)` | Medium | 🔶 Partial (basic hierarchy) |
| Component inheritance | §20.1 | `component sub_c : base_c { }` | `class sub_c(base_c)` | Medium | 🔶 Partial (basic hierarchy) |
| Monitor inheritance | §20.1 | `monitor sub_m : base_m { }` | N/A | Complex | ❌ Not Started |
| Named element shadowing | §20.1 | same-name field/constraint in derived | N/A | Complex | ❌ Not Started |
| Polymorphic function dispatch | §20.1 | (virtual instance function calls) | N/A | Complex | ❌ Not Started |
| Extend action | §20.2 | `extend action A { rand int j; }` | Extends existing IR DataTypeClass | Complex | ✅ Complete |
| Extend struct | §20.2 | `extend struct S { int extra; }` | Extends existing IR DataTypeClass | Complex | ✅ Complete |
| Extend component | §20.2 | `extend component C { ... }` | Extends existing IR DataTypeComponent | Complex | ✅ Complete |
| Extend enum | §20.2.4 | `extend enum color_e { YELLOW }` | Appends items to existing DataTypeEnum | Complex | ✅ Complete |
| Extend monitor | §20.2 | `extend monitor M { ... }` | N/A | Complex | ❌ Not Started |
| Extension ordering | §20.2.5 | (initial def first, then extensions) | N/A | Complex | ❌ Not Started |
| Template type extension (generic) | §20.2.6 | `extend struct s<type T> { ... }` | N/A | Very Complex | ❌ Not Started |
| Template instance extension | §20.2.6 | `extend struct s<int> { ... }` | N/A | Very Complex | ❌ Not Started |
| Combining inheritance & extension | §20.3 | (extensions to base affect derived) | N/A | Very Complex | ❌ Not Started |
| Access protection (public/private/protected) | §20.4 | `private rand int b;` | N/A | Medium | ❌ Not Started |
| Type override (type) | §20.5 | `override { type A with B; }` | N/A | Complex | ❌ Not Started |
| Instance override | §20.5 | `override { instance a1 with B; }` | N/A | Complex | ❌ Not Started |

---

## 17. Packages & Source Organization (LRM §21)

| Feature | LRM Section | PSS Example | Python/zuspec Equivalent | Complexity | Status |
|---------|-------------|-------------|--------------------------|------------|--------|
| Package declaration | §21.1.1 | `package my_pkg { ... }` | `# module my_pkg` | Medium | ✅ Complete |
| Nested package | §21.1.2 | `package outer::inner { }` | `# outer/inner module` | Medium | ✅ Complete |
| Qualified reference | §21.1.3 | `my_pkg::my_type` | `my_pkg.my_type` | Medium | ❌ Not Started |
| Explicit import | §21.1.3 | `import my_pkg::my_type;` | `from my_pkg import my_type` | Medium | ❌ Not Started |
| Wildcard import | §21.1.3 | `import my_pkg::*;` | `from my_pkg import *` | Medium | ❌ Not Started |
| Package alias | §21.1.4 | `import a::b::c as p1;` | `import a.b.c as p1` | Medium | ❌ Not Started |
| Name resolution rules | §21.3 | (unqualified name lookup) | N/A | Complex | ❌ Not Started |
| Declaration ordering | §21.2 | (forward reference rules) | N/A | Complex | ❌ Not Started |

---

## 18. Exec Blocks & Test Realization (LRM §22)

### 18.1 Exec Block Kinds

| Feature | LRM Section | PSS Example | Python/zuspec Equivalent | Complexity | Status |
|---------|-------------|-------------|--------------------------|------------|--------|
| exec pre_solve | §22.1 | `exec pre_solve { x = 0; }` | IR: `Function(name='pre_solve')` | Medium | ✅ Complete |
| exec post_solve | §22.1 | `exec post_solve { ... }` | IR: `Function(name='post_solve')` | Medium | ✅ Complete |
| exec body (procedural) | §22.1.2 | `exec body { ... }` | IR: `Function(name='body', is_async=True)` | Medium | ✅ Complete |
| exec body (target template) | §22.1.2 | `exec body "C" { ... }` | N/A (target code gen only) | Complex | ❌ Not Started |
| exec pre_body | §22.1.2 | `exec pre_body { ... }` | N/A | Medium | ❌ Not Started |
| exec init | §22.1.2 | `exec init { ... }` | IR: `Function(name='init_up')` (maps to init_up) | Medium | ✅ Complete |
| exec init_down | §22.1.2 | `exec init_down { ... }` | IR: `Function(name='init_down')` | Medium | ✅ Complete |
| exec init_up | §22.1.2 | `exec init_up { ... }` | IR: `Function(name='init_up')` | Medium | ✅ Complete |
| exec run_start | §22.1.2 | `exec run_start { ... }` | IR: `Function(name='run_start')` | Medium | ✅ Complete |
| exec run_end | §22.1.2 | `exec run_end { ... }` | IR: `Function(name='run_end')` | Medium | ✅ Complete |
| exec header (target) | §22.1.2 | `exec header "C" { "#include ..." }` | N/A (target code gen only) | Complex | ❌ Not Started |
| exec declaration (target) | §22.1.2 | `exec declaration "C" { "int x;" }` | N/A (target code gen only) | Complex | ❌ Not Started |
| exec file (target) | §22.1.3 | `exec file "C" "file.c" { ... }` | N/A (target code gen only) | Complex | ❌ Not Started |
| Exec block inheritance/shadowing | §22.1.4 | derived replaces base exec blocks | N/A | Complex | ❌ Not Started |
| super statement in exec | §22.1.4.2 | `super;` (in exec block) | `super().method()` | Complex | ❌ Not Started |
| Exec block via extension | §22.1.4.3 | `extend action A { exec body {...} }` | Adds exec functions to extended type | Complex | ✅ Complete |

### 18.2 Procedural Statements in Exec Blocks

| Feature | LRM Section | PSS Example | Python/zuspec Equivalent | Complexity | Status |
|---------|-------------|-------------|--------------------------|------------|--------|
| Variable declaration | §22.7.1 | `int x = 5;` | IR: `StmtAnnAssign` | Simple | ✅ Complete |
| Assignment statement | §22.7.2 | `x = y + 1;` | IR: `StmtAssign` | Simple | ✅ Complete |
| If-else statement | §22.7.3 | `if (x > 0) { ... }` | IR: `StmtIf` | Simple | ✅ Complete |
| Match statement | §22.7.4 | `match (v) { [1]: ...; }` | IR: `StmtMatch` | Medium | ⚠️ Partial (IR and translator exist; PSS frontend does not emit match nodes in function/exec bodies) |
| Return statement | §22.7.5 | `return x;` | IR: `StmtReturn` | Simple | ✅ Complete |
| Repeat-count statement | §22.7.6 | `repeat (i:10) { ... }` | IR: `StmtFor` | Simple | ✅ Complete |
| While statement | §22.7.7 | `while (x > 0) { ... }` | IR: `StmtWhile` | Simple | ✅ Complete |
| Repeat-while (do-while) | §22.7.6 | `repeat { ... } while (cond);` | IR: `StmtWhile` (restructured) | Simple | ✅ Complete |
| Foreach statement (in exec) | §22.7.8 | `foreach (e:list) { ... }` | IR: `StmtForeach` | Medium | 🔶 Partial (IR exists; AST→IR partial) |
| Break statement | §22.7.9 | `break;` | IR: `StmtBreak` | Simple | ✅ Complete |
| Continue statement | §22.7.9 | `continue;` | IR: `StmtContinue` | Simple | ✅ Complete |
| Function call statement | §22.7.10 | `print("hello");` | IR: `StmtExpr(ExprCall)` | Simple | ✅ Complete |
| Yield statement | §22.7.14 | `yield;` | IR: `StmtYield` | Medium | ✅ Complete |
| Procedural randomize | §22.7.13 | `randomize x with { x > 5; }` | IR: `StmtRandomize` | Complex | ❌ Not Started |

### 18.3 Functions

| Feature | LRM Section | PSS Example | Python/zuspec Equivalent | Complexity | Status |
|---------|-------------|-------------|--------------------------|------------|--------|
| Function declaration (native) | §22.2 | `function int add(int a, int b) { return a+b; }` | IR: `Function` | Medium | ✅ Complete |
| Static function | §22.2 | `static function void foo();` | `@staticmethod def foo()` | Medium | 🔶 Partial (declaration yes; static dispatch limited) |
| Instance function | §22.2 | `function void bar();` (in component) | `def bar(self)` | Medium | 🔶 Partial (declaration yes; polymorphism not done) |
| Pure function | §22.3 | `pure function int compute();` | `@pure def compute()` | Medium | ❌ Not Started |
| Function with default params | §22.2 | `function void f(int x = 5);` | `def f(x=5)` | Medium | ✅ Complete |
| Function varargs | §22.2 | `function void f(type... args);` | `def f(*args)` (args.vararg) | Medium | ✅ Complete |
| Function const parameter | §22.2 | `function void f(const int x);` | N/A | Medium | ❌ Not Started |
| super call in functions | §22.2 | `super.foo();` | `super().foo()` | Medium | ⚠️ Partial (PSS frontend gives same AST for super.x and x; both map to self.x) |
| Import function (solve) | §22.4 | `import solve function foo();` | N/A | Complex | ❌ Not Started |
| Import function (target) | §22.4 | `import target function foo();` | N/A | Complex | ❌ Not Started |
| Import class | §22.5 | `import class my_cls { ... }` | N/A | Complex | ❌ Not Started |
| Target-template function | §22.6 | `target function "C" foo() { ... }` | N/A (target code gen) | Complex | ❌ Not Started |
| Export function | §22.8 | `export function my_func;` | N/A | Complex | ❌ Not Started |
| Export action | §22.9 | `export action A (int x);` | N/A | Complex | ❌ Not Started |
| Platform qualifier | §22.2.3 | `solve function ...` / `target function ...` | N/A | Medium | ❌ Not Started |

### 18.4 Target-Template Code

| Feature | LRM Section | PSS Example | Python/zuspec Equivalent | Complexity | Status |
|---------|-------------|-------------|--------------------------|------------|--------|
| Mustache notation | §22.5.3 | `{{var_name}}` in exec body | N/A (target code gen) | Complex | ❌ Not Started |
| Target-template variable ref | §22.5.3 | `{{comp.field}}` | N/A (target code gen) | Complex | ❌ Not Started |
| Target-template comments | §22.5.4 | `{# comment #}` | N/A (target code gen) | Simple | ❌ Not Started |

---

## 19. Conditional Code Processing (LRM §23)

| Feature | LRM Section | PSS Example | Python/zuspec Equivalent | Complexity | Status |
|---------|-------------|-------------|--------------------------|------------|--------|
| compile if | §23.2 | `compile if (HAS_FEAT) { ... }` | N/A | Complex | ❌ Not Started |
| compile if-else | §23.2 | `compile if (X) { } else { }` | N/A | Complex | ❌ Not Started |
| compile has | §23.3 | `compile has(my_pkg::my_type)` | N/A | Complex | ❌ Not Started |
| compile assert | §23.4 | `compile assert (N > 0, "N must be positive");` | N/A | Medium | ❌ Not Started |

---

## 20. PSS Core Library (LRM §24)

### 20.1 String Formatting & Output

| Feature | LRM Section | PSS Example | Python/zuspec Equivalent | Complexity | Status |
|---------|-------------|-------------|--------------------------|------------|--------|
| format() | §24.1.2 | `format("val=%d", x)` | `f"val={x}"` | Medium | ❌ Not Started |
| print() | §24.1.2 | `print("hello %s", name)` | `print(f"hello {name}")` | Medium | ✅ Complete |
| message() (runtime) | §24.1.3 | `message(MEDIUM, "msg %d", v)` | `logging.info(...)` | Medium | ❌ Not Started |

### 20.2 File Operations

| Feature | LRM Section | PSS Example | Python/zuspec Equivalent | Complexity | Status |
|---------|-------------|-------------|--------------------------|------------|--------|
| file_open/close | §24.2 | `file_handle_t f = file_open("f.txt", TRUNCATE);` | `f = open("f.txt", "w")` | Medium | ❌ Not Started |
| file_write/read | §24.2 | `file_write(f, "data=%d", val);` | `f.write(...)` | Medium | ❌ Not Started |
| file_exists | §24.2 | `file_exists("f.txt")` | `os.path.exists(...)` | Simple | ❌ Not Started |
| file_read_lines/write_lines | §24.2 | `list<string> lines = file_read_lines("f");` | `f.readlines()` | Medium | ❌ Not Started |

### 20.3 Error Reporting

| Feature | LRM Section | PSS Example | Python/zuspec Equivalent | Complexity | Status |
|---------|-------------|-------------|--------------------------|------------|--------|
| error() | §24.3 | `error("bad value: %d", v);` | `raise RuntimeError(...)` | Simple | ❌ Not Started |
| fatal() | §24.3 | `fatal(1, "failed");` | `sys.exit(1)` | Simple | ❌ Not Started |

### 20.4 Randomization Functions

| Feature | LRM Section | PSS Example | Python/zuspec Equivalent | Complexity | Status |
|---------|-------------|-------------|--------------------------|------------|--------|
| urandom() | §24.4 | `bit[32] r = urandom();` | `random.getrandbits(32)` | Simple | ✅ Complete |
| urandom_range() | §24.4 | `bit[32] r = urandom_range(0, 100);` | `random.randint(0, 100)` | Simple | ✅ Complete |

### 20.5 Floating-Point Functions

| Feature | LRM Section | PSS Example | Python/zuspec Equivalent | Complexity | Status |
|---------|-------------|-------------|--------------------------|------------|--------|
| Math functions (sin, cos, sqrt, log, etc.) | §24.5.2 | `float64 r = sqrt(x);` | `math.sqrt(x)` | Medium | ❌ Not Started |
| Float component access (mantissa, exponent, sign) | §24.5.3 | `float_mantissa(f)` | N/A | Medium | ❌ Not Started |
| Packed float types (float32_s, float64_s) | §24.5.1 | `float32_s f;` | N/A | Complex | ❌ Not Started |

### 20.6 Executors

| Feature | LRM Section | PSS Example | Python/zuspec Equivalent | Complexity | Status |
|---------|-------------|-------------|--------------------------|------------|--------|
| executor_c component | §24.6 | `executor_c<my_trait> exe;` | N/A | Very Complex | ❌ Not Started |
| executor_group_c | §24.6 | `executor_group_c<my_trait> grp;` | N/A | Very Complex | ❌ Not Started |
| executor_claim_s | §24.6 | `executor_claim_s<my_trait> claim;` | N/A | Very Complex | ❌ Not Started |
| executor() query function | §24.6 | `ref executor_base_c e = executor();` | N/A | Very Complex | ❌ Not Started |

### 20.7 Address Spaces

| Feature | LRM Section | PSS Example | Python/zuspec Equivalent | Complexity | Status |
|---------|-------------|-------------|--------------------------|------------|--------|
| contiguous_addr_space_c | §24.7 | `contiguous_addr_space_c<> as;` | IR: `DataTypeAddressSpace` (stub) | Very Complex | 🔶 Partial (IR stub exists) |
| transparent_addr_space_c | §24.7 | `transparent_addr_space_c<> as;` | N/A | Very Complex | ❌ Not Started |
| addr_region_s | §24.7.3 | `addr_region_s<> region;` | N/A | Complex | ❌ Not Started |
| addr_claim_s | §24.8 | `addr_claim_s<> claim;` | N/A | Complex | ❌ Not Started |
| transparent_addr_claim_s | §24.8 | `transparent_addr_claim_s<> claim;` | N/A | Complex | ❌ Not Started |
| addr_handle_t | §24.10.3 | `addr_handle_t h;` | IR: `DataTypeAddrHandle` (stub) | Complex | 🔶 Partial (IR stub exists) |
| make_handle_from_claim | §24.10.4 | `make_handle_from_claim(claim)` | N/A | Complex | ❌ Not Started |
| addr_value functions | §24.10.5 | `addr_value(h)` | N/A | Complex | ❌ Not Started |
| addr_space_group_c | §24.9 | `addr_space_group_c grp;` | N/A | Very Complex | ❌ Not Started |

### 20.8 Memory Access Operations

| Feature | LRM Section | PSS Example | Python/zuspec Equivalent | Complexity | Status |
|---------|-------------|-------------|--------------------------|------------|--------|
| read8/16/32/64 | §24.10.9 | `bit[32] v = read32(h);` | N/A | Complex | ❌ Not Started |
| write8/16/32/64 | §24.10.9 | `write32(h, val);` | N/A | Complex | ❌ Not Started |
| read_bytes/write_bytes | §24.10.9 | `read_bytes(h, data, sz);` | N/A | Complex | ❌ Not Started |
| read_struct/write_struct | §24.10.9 | `read_struct(h, my_struct);` | N/A | Complex | ❌ Not Started |
| Data layout (packed_s) | §24.10.1 | `struct my_reg : packed_s<> { ... }` | N/A | Complex | ❌ Not Started |
| sizeof_s template | §24.10.2 | `sizeof_s<my_t>::nbytes` | N/A | Complex | ❌ Not Started |

### 20.9 Registers

| Feature | LRM Section | PSS Example | Python/zuspec Equivalent | Complexity | Status |
|---------|-------------|-------------|--------------------------|------------|--------|
| reg_c component | §24.11.1 | `reg_c<my_reg_t> reg;` | IR: `DataTypeRegister` | Complex | ✅ Complete |
| reg_c read/write methods | §24.11.1 | `reg.read()`, `reg.write(v)` | Built-in functions in IR | Complex | ✅ Complete |
| reg_c read_val/write_val | §24.11.1 | `reg.read_val()` | Built-in functions in IR | Complex | ✅ Complete |
| reg_c write_masked | §24.11.1 | `reg.write_masked(mask, val)` | N/A | Complex | ❌ Not Started |
| reg_c write_field/write_fields | §24.11.1 | `reg.write_field("f1", val)` | N/A | Complex | ❌ Not Started |
| reg_group_c component | §24.11.2 | `reg_group_c my_regs { ... }` | IR: `DataTypeRegisterGroup` | Complex | ✅ Complete |
| reg_group_c get_offset_of_instance | §24.11.2 | `get_offset_of_instance("reg1")` | Built-in function in IR | Complex | ✅ Complete |
| reg_group_c set_handle | §24.11.2 | `set_handle(addr_h);` | N/A | Complex | ❌ Not Started |
| reg_access enum | §24.11.1 | `READWRITE`, `READONLY`, `WRITEONLY` | IR: `TemplateParamEnum` | Simple | ✅ Complete |

---

## 21. Foreign Language Bindings (LRM Annex D)

| Feature | LRM Section | PSS Example | Python/zuspec Equivalent | Complexity | Status |
|---------|-------------|-------------|--------------------------|------------|--------|
| C function mapping | §D.3 | (PSS → C function names) | N/A (target code gen) | Complex | ❌ Not Started |
| C type mapping | §D.3 | `int` → `int32_t`, etc. | N/A (target code gen) | Complex | ❌ Not Started |
| C++ function mapping | §D.4 | (PSS → C++ with namespaces) | N/A (target code gen) | Complex | ❌ Not Started |
| C++ struct mapping | §D.4 | (PSS struct → C++ class) | N/A (target code gen) | Complex | ❌ Not Started |
| SystemVerilog mapping | §D.5 | (PSS → SV types/tasks) | N/A (target code gen) | Complex | ❌ Not Started |

---

## Summary Statistics

| Category | Total Features | ✅ Complete | 🔶 Partial | ❌ Not Started |
|----------|---------------|------------|-----------|---------------|
| Lexical Conventions | 18 | 10 | 2 | 6 |
| Scalar Data Types | 13 | 6 | 2 | 5 |
| Collections | 20 | 0 | 0 | 20 |
| Reference Types | 4 | 0 | 0 | 4 |
| Data Type Conversion | 3 | 1 | 0 | 2 |
| Operators & Expressions | 19 | 14 | 1 | 4 |
| Components | 10 | 2 | 6 | 2 |
| Actions | 21 | 5 | 3 | 13 |
| Struct Types | 7 | 2 | 1 | 4 |
| Flow Objects | 9 | 0 | 0 | 9 |
| Resource Objects | 6 | 0 | 0 | 6 |
| Pools & Binding | 6 | 0 | 0 | 6 |
| Template Types | 8 | 0 | 5 | 3 |
| Activity | 25 | 0 | 0 | 25 |
| Constraints | 21 | 2 | 0 | 19 |
| Action Inferencing | 3 | 0 | 0 | 3 |
| Data Coverage | 16 | 0 | 6 | 10 |
| Behavioral Coverage (Monitors) | 15 | 0 | 0 | 15 |
| Type Inheritance/Extension/Override | 17 | 0 | 3 | 14 |
| Packages & Source Organization | 8 | 0 | 0 | 8 |
| Exec Blocks | 16 | 5 | 1 | 10 |
| Procedural Statements | 14 | 10 | 1 | 3 |
| Functions | 15 | 1 | 2 | 12 |
| Target-Template Code | 3 | 0 | 0 | 3 |
| Conditional Code Processing | 4 | 0 | 0 | 4 |
| Core Library (Strings/Files/Errors) | 9 | 0 | 0 | 9 |
| Core Library (Random/Float) | 4 | 0 | 0 | 4 |
| Core Library (Executors) | 4 | 0 | 0 | 4 |
| Core Library (Address Spaces) | 9 | 0 | 2 | 7 |
| Core Library (Memory Access) | 6 | 0 | 0 | 6 |
| Core Library (Registers) | 9 | 5 | 0 | 4 |
| Foreign Language Bindings | 5 | 0 | 0 | 5 |
| **TOTALS** | **~367** | **~63 (17%)** | **~35 (10%)** | **~269 (73%)** |

---

## Implementation Priority Recommendations

### Phase 1 — Foundation (High Priority)
1. **Packages & Imports** (§21) — required for multi-file models
2. **Enum types** (§7.5) — widely used in PSS models
3. **Typedef** (§7.11) — syntactic convenience used everywhere
4. **Constraints** (§16.1) — fundamental to PSS semantics
5. **Collections** (§7.9) — arrays, lists, maps, sets

### Phase 2 — Core Modeling (High Priority)
6. **Activity** (§12) — compound action scheduling (the heart of PSS)
7. **Flow objects** (§13) — buffer, stream, state
8. **Resource objects** (§14) — lock/share semantics
9. **Pools & binding** (§15) — object pool management
10. **Action inferencing** (§17) — implicit scenario construction

### Phase 3 — Advanced Features (Medium Priority)
11. **Type extension** (§20.2) — extend action/struct/component/enum
12. **Type override** (§20.5) — type/instance overrides
13. **Data coverage** (§18) — covergroups, coverpoints, crosses
14. **Compile-time features** (§23) — compile if/has/assert
15. **Function platform qualifiers** (§22.2.3) — solve vs. target functions

### Phase 4 — Infrastructure (Medium Priority)
16. **Core library functions** (§24.1–24.4) — print, format, file I/O, error
17. **Address spaces & executors** (§24.6–24.8) — execution infrastructure
18. **Foreign language integration** (§22.4–22.8) — import/export functions

### Phase 5 — Advanced Coverage & Monitors (Lower Priority)
19. **Behavioral coverage & monitors** (§19) — PSS v3.0 new feature
20. **Foreign language bindings** (Annex D) — C/C++/SV mappings
