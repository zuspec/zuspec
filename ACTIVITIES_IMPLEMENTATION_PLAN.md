# Activities Implementation Plan — zuspec-dataclasses

## Overview

This document is the implementation plan for PSS Activities support in
`packages/zuspec-dataclasses`. It covers the five implementation phases
described in `ACTIVITY_DESIGN.md`, plus testing and documentation tasks for
each phase.

Reference documents:
- `ACTIVITY_DESIGN.md` — full design specification (authoritative)
- `PSS_LRM.md` — PSS 3.0 LRM (Sections 10, 12, 13, 14, 15, 22.1)

---

## Current State

### What Exists

| Area | Status |
|---|---|
| `Action[T]` base class | Exists in `types.py`; has `body()`, `pre_solve()`, `post_solve()`, `activity()` stubs |
| `Component`, `Struct`, `TypeBase` | Exist in `types.py` |
| `Pool[T]`, `BufferPool[T]`, `ClaimPool[T]` | Exist in `types.py` (runtime-level; not PSS IR) |
| `@zdc.dataclass` decorator | Exists; processes fields, constraints, profiles |
| `ConstraintParser` | Exists; parses `@constraint` methods from AST |
| IR node hierarchy | `ir/base.py`, `ir/expr.py`, `ir/stmt.py`, `ir/fields.py`, etc. |
| IR visitor pattern | `ir/visitor.py` — `Base.accept()` / `v.visitXxx()` pattern |

### What Is Missing

- `Buffer`, `Stream`, `State`, `Resource` PSS base types in `types.py`
- `lock()`, `share()` field helpers in `decorators.py`
- `@zdc.extend` decorator for type extensions
- Activity IR nodes (`ir/activity.py`)
- `ActivityParser` class (sibling to `ConstraintParser`)
- Activity detection in `@zdc.dataclass` decorator
- DSL context-manager stubs (`parallel`, `schedule`, `sequence`, `atomic`,
  `select`, `branch`, `do_while`, `while_do`, `replicate`, `constraint`, `bind`, `do`)
- Visitor methods for activity IR nodes
- Tests for all of the above
- Documentation updates

---

## Phase 1 — Core: Sequential Traversal

**Goal:** Parse a basic `async def activity(self)` that traverses declared
action handles sequentially. Store the IR on the class. Write tests.

### Tasks

#### 1.1 PSS Flow-Object and Resource Base Types

**File:** `src/zuspec/dataclasses/types.py`

Add the following classes after `Struct`:

```python
class Buffer(Struct):
    """PSS buffer flow-object base type."""
    pass

class Stream(Struct):
    """PSS stream flow-object base type."""
    pass

class State(Struct):
    """PSS state flow-object base type.
    Has built-in `initial` bool and `prev` reference.
    """
    initial: bool = False

class Resource(Struct):
    """PSS resource base type. Has built-in `instance_id`."""
    instance_id: int = 0
```

Export from `__init__.py`.

#### 1.2 `lock()` and `share()` Helpers

**File:** `src/zuspec/dataclasses/decorators.py`

```python
def lock(size: Optional[int] = None) -> Any:
    """Mark a Resource field as an exclusive lock claim."""
    meta = {"kind": "resource_ref", "claim": "lock"}
    if size is not None:
        meta["size"] = size
    return dc.field(default=None, metadata=meta)

def share(size: Optional[int] = None) -> Any:
    """Mark a Resource field as a shared claim."""
    meta = {"kind": "resource_ref", "claim": "share"}
    if size is not None:
        meta["size"] = size
    return dc.field(default=None, metadata=meta)
```

Export from `__init__.py`.

#### 1.3 Activity IR Nodes — Phase 1 Subset

**New file:** `src/zuspec/dataclasses/ir/activity.py`

Define the base and Phase 1 IR nodes per the design spec (Section 8):

```
ActivityStmt          — base
ActivitySequenceBlock — list of stmts (implicit or explicit sequence)
ActivityTraversal     — self.handle() [with optional inline constraints]
ActivityAnonTraversal — do(Type) [with optional label and inline constraints]
ActivitySuper         — super().activity()
JoinSpec              — (deferred to Phase 2, stub only)
```

Follow the existing `@dc.dataclass(kw_only=True)` + `Base` convention.
Add `accept()` / `visitXxx()` per the visitor pattern in `ir/base.py`.

Export new nodes from `ir/__init__.py`.

#### 1.4 `ActivityParser` — Phase 1

**New file:** `src/zuspec/dataclasses/activity_parser.py`

Modeled after `constraint_parser.py`. Public API:

```python
class ActivityParser:
    def parse(self, method: Callable) -> ActivitySequenceBlock:
        """Parse an async activity method, return IR."""
        ...
```

Phase 1 AST patterns to handle (from design Section 7.2):

| AST Pattern | IR Node |
|---|---|
| `Call(Attr(self, name))` | `ActivityTraversal` |
| `With(ctx=Call(Attr(self, name)))` | `ActivityTraversal` + inline constraints |
| `Call(Name('do'), args=[type])` | `ActivityAnonTraversal` |
| `With(ctx=Call(Name('do')))` | `ActivityAnonTraversal` + inline constraints |
| `Assign(value=Call(do(...)))` | `ActivityAnonTraversal` (labeled) |
| `Call(Attr(Call(Name('super')),'activity'))` | `ActivitySuper` |

Inline constraints in `with` bodies are parsed by delegating to
`ConstraintParser.parse_expr()`.

#### 1.5 Activity Detection in `@zdc.dataclass`

**File:** `src/zuspec/dataclasses/decorators.py` — `dataclass()` function

After building the dataclass, detect `activity` in `cls.__dict__`:

```python
if 'activity' in cls.__dict__ and 'body' in cls.__dict__:
    raise TypeError(f"{cls.__name__}: action cannot define both activity() and body()")
if 'activity' in cls.__dict__:
    from .activity_parser import ActivityParser
    cls.__activity__ = ActivityParser().parse(cls.__dict__['activity'])
```

#### 1.6 DSL Stub Functions (Phase 1)

**New file:** `src/zuspec/dataclasses/activity_dsl.py`

Provide callable stubs that are legal Python (for import without error) but
are never actually executed (AST-only). The stubs raise `RuntimeError` if
called at runtime to catch accidental non-AST use:

```python
def do(action_type):
    raise RuntimeError("do() is an activity DSL function; use inside async def activity(self)")

class _CtxMgr:
    def __enter__(self): return self
    def __exit__(self, *a): pass

def parallel(*args, **kwargs): return _CtxMgr()
def schedule(*args, **kwargs): return _CtxMgr()
def sequence(*args, **kwargs): return _CtxMgr()
def atomic(*args, **kwargs): return _CtxMgr()
def select(*args, **kwargs): return _CtxMgr()
def branch(*args, **kwargs): return _CtxMgr()
def do_while(cond): return _CtxMgr()
def while_do(cond): return _CtxMgr()
def replicate(n, label=None): return iter([])
def constraint(): return _CtxMgr()
def bind(src, dst): pass
```

Export all from `__init__.py`.

#### 1.7 Visitor Updates

**File:** `src/zuspec/dataclasses/ir/visitor.py`

Add `visitActivityStmt`, `visitActivitySequenceBlock`, `visitActivityTraversal`,
`visitActivityAnonTraversal`, `visitActivitySuper` with default pass-through
implementations.

#### 1.8 Phase 1 Tests

**New file:** `tests/unit/test_activity_parser.py`

Test cases:
1. `activity` with a single handle traversal (`self.a1()`) → `ActivityTraversal`
2. `activity` with multiple sequential traversals → `ActivitySequenceBlock` with 2+ nodes
3. `activity` with `with self.h():` → `ActivityTraversal` with inline constraints
4. `activity` with `do(WriteAction)` → `ActivityAnonTraversal`
5. `activity` with `with do(WriteAction) as wr:` → `ActivityAnonTraversal` labeled, with inline constraints
6. `activity` with `xfer = do(WriteAction)` → labeled `ActivityAnonTraversal`
7. `activity` with `super().activity()` → `ActivitySuper`
8. Error: defining both `activity` and `body` raises `TypeError`

**New file:** `tests/unit/test_flow_resource_types.py`

Test cases:
1. `Buffer` subclass can be decorated with `@zdc.dataclass`
2. `Stream` subclass can be decorated
3. `State` subclass can be decorated
4. `Resource` subclass can be decorated
5. `lock()` creates field with `{"kind": "resource_ref", "claim": "lock"}` metadata
6. `share()` creates field with `{"kind": "resource_ref", "claim": "share"}` metadata

---

## Phase 2 — Scheduling Blocks

**Goal:** Parse `parallel()`, `schedule()`, `atomic()` context managers and their
`join_spec` arguments. Add async executor support.

### Tasks

#### 2.1 `JoinSpec` IR Node

**File:** `src/zuspec/dataclasses/ir/activity.py`

```python
@dc.dataclass(kw_only=True)
class JoinSpec(Base):
    kind: str  # "all" | "branch" | "none" | "select" | "first"
    branch_label: Optional[str] = None
    count: Optional[Expr] = None
```

#### 2.2 Activity IR Nodes — Phase 2 Subset

Add to `ir/activity.py`:

```
ActivityParallel   — stmts + optional JoinSpec
ActivitySchedule   — stmts + optional JoinSpec
ActivityAtomic     — stmts
```

#### 2.3 `ActivityParser` — Phase 2 Patterns

Extend `ActivityParser` to handle:

| AST Pattern | IR Node |
|---|---|
| `With(Name('parallel'))` | `ActivityParallel` |
| `With(Name('schedule'))` | `ActivitySchedule` |
| `With(Name('sequence'))` | `ActivitySequenceBlock` (explicit) |
| `With(Name('atomic'))` | `ActivityAtomic` |

Parse `join_branch`, `join_none`, `join_select`, `join_first` keyword args
from the context manager call to populate `JoinSpec`.

#### 2.4 Visitor Updates

Add `visitActivityParallel`, `visitActivitySchedule`, `visitActivityAtomic`.

#### 2.5 Phase 2 Tests

**New file:** `tests/unit/test_activity_parallel.py`

Test cases:
1. `with parallel():` → `ActivityParallel` with stmts
2. `with schedule():` → `ActivitySchedule` with stmts
3. `with sequence():` → `ActivitySequenceBlock` (explicit)
4. `with atomic():` → `ActivityAtomic` with stmts
5. `with parallel(join_branch='L2'):` → `ActivityParallel` with `JoinSpec(kind='branch', branch_label='L2')`
6. `with parallel(join_none=True):` → `ActivityParallel` with `JoinSpec(kind='none')`
7. `with parallel(join_first=1):` → `ActivityParallel` with `JoinSpec(kind='first', count=Expr(1))`
8. Nested `parallel` inside `sequence` → correct nesting in IR

---

## Phase 3 — Control Flow

**Goal:** Parse `for/range` repeat, `for/collection` foreach, `if/else`,
`match/case`, `select/branch`, `do_while`, `while_do`, `replicate`.

### Tasks

#### 3.1 Activity IR Nodes — Phase 3 Subset

Add to `ir/activity.py`:

```
ActivityRepeat    — count repeat (for i in range(...))
ActivityDoWhile   — do-while loop
ActivityWhileDo   — while-do loop
ActivityForeach   — foreach over collection
ActivitySelect    — select statement
SelectBranch      — one branch of select
ActivityIfElse    — if/else
ActivityMatch     — match/case
MatchCase         — one match case
ActivityReplicate — replicate (generative, not sequential loop)
ActivityConstraint — scheduling constraint block
```

#### 3.2 `ActivityParser` — Phase 3 Patterns

Extend parser per design Section 7.2 table.

Key patterns:
- `for i in range(N)` or `for i in range(self.count)` → `ActivityRepeat`
- `for item in self.collection` → `ActivityForeach`
- `for i, item in enumerate(self.collection)` → `ActivityForeach` with index
- `for i in replicate(N)` → `ActivityReplicate`
- `with do_while(cond):` → `ActivityDoWhile`
- `with while_do(cond):` → `ActivityWhileDo`
- `with select():` + inner `with branch():` → `ActivitySelect` / `SelectBranch`
- `if cond:` / `else:` → `ActivityIfElse`
- `match subject: case X:` → `ActivityMatch` / `MatchCase`
- `with constraint():` → `ActivityConstraint` (collect body as constraint exprs)

#### 3.3 Visitor Updates

Add visit methods for all Phase 3 nodes.

#### 3.4 Phase 3 Tests

**New file:** `tests/unit/test_activity_control_flow.py`

Test cases for each new construct:
1. `for i in range(3):` → `ActivityRepeat(count=Const(3))`
2. `for i in range(self.count):` → `ActivityRepeat(count=AttrExpr('count'))`
3. `with do_while(self.s1.last_one != 0):` → `ActivityDoWhile` with condition
4. `with while_do(self.remaining > 0):` → `ActivityWhileDo` with condition
5. `for item in self.data_array:` → `ActivityForeach`
6. `for i, item in enumerate(self.data_array):` → `ActivityForeach` with index
7. `with select(): with branch(): ...` → `ActivitySelect` with `SelectBranch`
8. `with branch(guard=self.a == 0, weight=20):` → `SelectBranch` with guard + weight
9. `if self.x > 5: ... else: ...` → `ActivityIfElse`
10. `match self.level: case Low: ...` → `ActivityMatch` / `MatchCase`
11. `with replicate(self.count):` → `ActivityReplicate`
12. `with constraint(): self.a1.size < 10` → `ActivityConstraint` with expr

---

## Phase 4 — Flow and Resource Objects

**Goal:** Integrate `Buffer`, `Stream`, `State`, `Resource` with field
helpers `input()` / `output()` (flow-object context-sensitivity) and
`lock()` / `share()`. Add pool declarations with `@zdc.bind`.

### Tasks

#### 4.1 Context-Sensitive `input()` / `output()` in Action Scope

**File:** `src/zuspec/dataclasses/decorators.py`

In the `@zdc.dataclass` decorator, when processing an `Action` subclass:
- Inspect each field's annotated type.
- If the type is a subclass of `Buffer`, `Stream`, or `State`, set
  `metadata["kind"] = "flow_ref"` and `metadata["direction"] = "input"|"output"`.
- Existing signal port behavior is unchanged for non-flow-object types.

This means `input()` and `output()` become context-sensitive at IR construction
time, not at decoration time.

#### 4.2 Pool Declaration IR

**File:** `src/zuspec/dataclasses/ir/activity.py` or `ir/fields.py`

Add:
```python
@dc.dataclass(kw_only=True)
class PoolDecl(Base):
    name: str
    element_type: str       # qualified type name
    size: int
```

#### 4.3 `ActivityBind` IR Node

Add to `ir/activity.py`:
```python
@dc.dataclass(kw_only=True)
class ActivityBind(ActivityStmt):
    src: Expr
    dst: Expr
```

#### 4.4 `ActivityParser` — `bind()` Support

Recognize `Call(Name('bind'), args=[src, dst])` → `ActivityBind`.

#### 4.5 Phase 4 Tests

**New file:** `tests/unit/test_activity_flow_resource.py`

Test cases:
1. `Buffer` subclass field with `output()` → `flow_ref` / `output` metadata
2. `Buffer` subclass field with `input()` → `flow_ref` / `input` metadata
3. `Resource` subclass field with `lock()` → `resource_ref` / `lock` metadata
4. `Resource` subclass field with `share()` → `resource_ref` / `share` metadata
5. `bind(self.producer.data_out, self.consumer.data_in)` → `ActivityBind` IR node
6. Action with both flow-object and regular fields parsed correctly

---

## Phase 5 — Extensions and Codegen

**Goal:** `@zdc.extend` decorator for type extensions; activity visualization;
incremental parser caching; MyPy plugin extensions.

### Tasks

#### 5.1 `@zdc.extend` Decorator

**File:** `src/zuspec/dataclasses/decorators.py`

```python
def extend(cls):
    """Mark a class as a type extension of its base class."""
    # Infer extended type from base class inheritance
    bases = [b for b in cls.__bases__ if hasattr(b, '__activity__') or hasattr(b, '__dataclass_fields__')]
    if not bases:
        raise TypeError(f"@extend: {cls.__name__} must inherit from a zuspec dataclass")
    cls.__extends__ = bases[0]
    cls.__is_extension__ = True
    return cls
```

Multiple extensions of the same type produce an implied `schedule` block
per PSS semantics (Section 12.6).

#### 5.2 Activity Visualization (`to_dot()`)

Add `to_dot()` method to `ActivitySequenceBlock` and sibling IR nodes,
generating Graphviz DOT output for visual debugging. Follow the pattern
of `regfile.dot` in the project root.

#### 5.3 MyPy Plugin Extensions

**File:** `src/zuspec/dataclasses/flake8_zdc_struct.py`

Extend the existing MyPy / flake8 plugin to validate:
- Mutual exclusion: action cannot define both `activity()` and `body()`
- Flow object direction: `Buffer` allows one `output()`, N `input()`
- Abstract action (`abstract=True`) cannot be instantiated

#### 5.4 Incremental Parsing Cache

In `ActivityParser.parse()`, cache the parsed IR keyed by
`hash(inspect.getsource(method))` to avoid repeated AST parsing for
the same source text.

#### 5.5 Phase 5 Tests

**New file:** `tests/unit/test_activity_extend.py`

Test cases:
1. `@zdc.extend` on a class extending an action → `__is_extension__` set
2. Multiple extensions of the same action → combined as implied `schedule`
3. Extension without valid base → `TypeError`

---

## Phase 6 — End-to-End Example Tests

**Goal:** Run the full PSS LRM Example 45 (DMA transfer) as a Python test,
verify activity IR structure, and execute via the existing async runtime.

### Tasks

#### 6.1 DMA Transfer Example Test

**New file:** `tests/unit/test_activity_e2e_dma.py`

Translate PSS LRM Example 45:
- `MemSegment`, `DataBuff`, `DmaChannel`, `DmaComponent`
- `WriteData`, `ReadData`, `DmaXfer`
- `DmaXfer.activity()` with `self.wr()` and `with self.rd():` inline constraint
- Assert IR structure: `ActivitySequenceBlock` with `ActivityTraversal` nodes
- Assert `WriteData` has `flow_ref` output field and `resource_ref` lock field

#### 6.2 Stress Test / Advanced Example

**New file:** `tests/unit/test_activity_e2e_stress.py`

Translate the StressTest / ForkJoinTest examples from Section 6 of
`ACTIVITY_DESIGN.md`:
- `for i in range(self.count): with parallel(): ...`
- `with select(): with branch(weight=70): ...`
- `with parallel(join_first=1): ...`

Assert correct IR nesting at each level.

---

## Documentation Tasks

### D1 — Update `README.md`

Add a "PSS Activities" section after the existing Constraints section.
Cover:
- How to declare a compound action with `async def activity(self)`
- Handle traversal syntax (`self.h()`, `do(Type)`)
- Scheduling blocks (`parallel`, `schedule`, `sequence`, `atomic`)
- Control flow (`for/range`, `if/else`, `select/branch`)
- Inline constraints in activity

### D2 — Update `API_REFERENCE.md`

Add entries for:
- `Buffer`, `Stream`, `State`, `Resource` base types
- `lock()`, `share()` helpers
- `do()`, `parallel()`, `schedule()`, `sequence()`, `atomic()`, `select()`, `branch()`
- `do_while()`, `while_do()`, `replicate()`, `constraint()`, `bind()`
- `@zdc.extend` decorator
- Activity IR nodes (`ir/activity.py`)

### D3 — Add Examples

**New file:** `examples/activity_dma.py`

Full working example translated from PSS LRM Example 45, runnable as a
Python script.

---

## File Change Summary

| File | Change |
|---|---|
| `src/zuspec/dataclasses/types.py` | Add `Buffer`, `Stream`, `State`, `Resource` |
| `src/zuspec/dataclasses/decorators.py` | Add `lock()`, `share()`, `extend()`; activity detection in `dataclass()` |
| `src/zuspec/dataclasses/__init__.py` | Export new types and helpers |
| `src/zuspec/dataclasses/ir/activity.py` | **New** — all activity IR nodes |
| `src/zuspec/dataclasses/ir/__init__.py` | Export activity IR nodes |
| `src/zuspec/dataclasses/ir/visitor.py` | Add visit methods for activity nodes |
| `src/zuspec/dataclasses/activity_parser.py` | **New** — `ActivityParser` |
| `src/zuspec/dataclasses/activity_dsl.py` | **New** — DSL stub functions |
| `tests/unit/test_flow_resource_types.py` | **New** — Phase 1 type tests |
| `tests/unit/test_activity_parser.py` | **New** — Phase 1 parser tests |
| `tests/unit/test_activity_parallel.py` | **New** — Phase 2 tests |
| `tests/unit/test_activity_control_flow.py` | **New** — Phase 3 tests |
| `tests/unit/test_activity_flow_resource.py` | **New** — Phase 4 tests |
| `tests/unit/test_activity_extend.py` | **New** — Phase 5 tests |
| `tests/unit/test_activity_e2e_dma.py` | **New** — End-to-end DMA example |
| `tests/unit/test_activity_e2e_stress.py` | **New** — End-to-end stress example |
| `README.md` | Activity section |
| `API_REFERENCE.md` | New API entries |
| `examples/activity_dma.py` | **New** — runnable example |

---

## Open Issues to Resolve During Implementation

From `ACTIVITY_DESIGN.md` Section 11:

1. **`@zdc.extend` module-ordering** — how extensions across packages are merged
   (implied schedule block construction). Defer to Phase 5; mark as open.

2. **Flow-object default binding** — activity-level `bind()` vs component-level
   pool resolution. Needs integration with existing `@zdc.bind`. Phase 4 adds
   `ActivityBind` IR; resolver is deferred.

3. **`while_do` inclusion** — not in PSS LRM but useful for Python-native
   patterns. Include in Phase 3 with a clear docstring noting the deviation.

4. **Hierarchical activity references** — `do T with { nested.field > 0; }`.
   Full name resolution in constraint sub-parser is deferred; Phase 1
   supports single-level references only.

---

## Implementation Order

```
Phase 1  →  Phase 2  →  Phase 3  →  Phase 4  →  Phase 5  →  Phase 6
(Core)     (Sched)     (Control)    (Flow/Res)   (Ext/CG)    (E2E)
```

Each phase is independently testable. The existing test suite must remain
green at the end of each phase before proceeding to the next.
