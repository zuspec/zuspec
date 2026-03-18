# Zuspec Actions, Activities, and Activity Statements -- Design

## Overview

This document describes the design for representing PSS Actions, Activities,
and Activity Statements in the Zuspec Python-based frontend
(`zuspec-dataclasses`). The goal is a Pythonic surface syntax that can be
parsed from the Python AST and lowered to a PSS-compatible IR suitable for
solving, code generation (Python and C), and round-tripping to/from the
PSS DSL.

The design follows the established zuspec-dataclasses conventions:

- `@zdc.dataclass` decorator on classes
- Field helpers (`zdc.rand()`, `zdc.field()`, etc.) for metadata
- Decorated methods whose bodies are parsed from AST, not executed
  (same pattern as `@zdc.constraint`)
- IR node classes in `zuspec.dataclasses.ir`

References: PSS LRM 3.0 Sections 10 (Actions), 12 (Activities), 13 (Flow
Objects), 14 (Resources), 15 (Pools), 22.1 (Exec Blocks).

---

## 1. Action Declaration

### 1.1 Current State

The existing `Action[T]` base class is a generic dataclass parameterized by
the component type it runs in:

```python
@zdc.dataclass
class MyAction(zdc.Action[MyComponent]):
    val: zdc.u32 = zdc.field()

    async def body(self):
        ...
```

This already captures the component-binding idea from PSS (every non-abstract
action lives inside a component scope). However it lacks:

- Distinction between atomic and compound actions
- Flow-object and resource-object field declarations
- Activity declarations
- Abstract action support
- Full exec-block lifecycle (pre_solve, post_solve, pre_body)

### 1.2 Proposed Design

Actions remain dataclasses inheriting from `zdc.Action[T]`. The atomic vs
compound distinction is inferred from the class definition:

- **Compound**: The class defines `async def activity(self)`.
- **Atomic**: The class defines `async def body(self)` (no activity).

No special decorator is needed to mark activities. The `@zdc.dataclass`
decorator detects the presence of an `activity` method and records it
for AST parsing. Making `activity` async is required so it can be
`await`-ed by the runtime executor and composed with `asyncio` tasks.

```python
@zdc.dataclass
class AtomicAction(zdc.Action[MyComponent]):
    """Atomic -- has body(), no activity()."""
    size: zdc.u32 = zdc.rand(domain=(1, 256))

    async def body(self):
        print(f"write {self.size} bytes")


@zdc.dataclass
class CompoundAction(zdc.Action[MyComponent]):
    """Compound -- has activity(), no body()."""
    a1: AtomicAction
    a2: AtomicAction

    async def activity(self):
        self.a1()
        self.a2()
```

Sub-action fields (like `a1` and `a2` above) are inferred from the type
annotation. Any field whose annotated type is a subclass of `Action` is
automatically treated as an action handle by the parser. No explicit
`zdc.action_handle()` helper is needed. For fixed-size arrays of action
handles, use `List[ActionType]` with a `zdc.field(size=N)`:

```python
a_arr: List[WriteAction] = zdc.field(size=4)
```

#### Abstract Actions

Abstract actions use the `abstract=True` parameter and may be declared
outside a component scope (without the `[T]` type parameter):

```python
@zdc.dataclass(abstract=True)
class BaseAction(zdc.Action):
    i: zdc.i32 = zdc.rand()

    @zdc.constraint
    def c(self):
        self.i > 5
        self.i < 10


@zdc.dataclass
class DerivedAction(BaseAction, zdc.Action[MyComponent]):
    @zdc.constraint
    def c2(self):
        self.i > 6
```

The `@zdc.dataclass` decorator with `abstract=True` sets
`cls.__abstract_action__ = True` and blocks direct instantiation.

---

## 2. Action Field Declarations

PSS actions contain several kinds of fields. Each uses the appropriate
existing or new field helper. All field helpers return
`dataclasses.field(...)` with appropriate metadata.

### 2.1 Random Fields (existing)

```python
size: zdc.u32 = zdc.rand(domain=(1, 256))
mode: MyEnum = zdc.randc()
```

No changes needed.

### 2.2 Action Handle Fields (inferred)

Action handles are inferred from the type annotation. Any field annotated
with a type that is a subclass of `Action` is treated as an action handle.
No dedicated field helper is required:

```python
a1: WriteAction                                    # single handle
a_arr: List[WriteAction] = zdc.field(size=4)       # fixed-size array
```

Handles default to `None` (uninitialized until traversal). The parser
inspects base classes of the annotated type to detect action handles.

### 2.3 Flow-Object Reference Fields

Flow objects (buffer, stream, state) are referenced by actions via the
existing `zdc.input()` and `zdc.output()` helpers. The distinction between
a hardware signal port and a flow-object reference is determined by the
annotated type: if the type inherits from `Buffer`, `Stream`, or `State`,
it is a flow-object reference. No new `zdc.flow_input()` /
`zdc.flow_output()` helpers are needed.

```python
@zdc.dataclass
class DataBuffer(zdc.Buffer):
    """PSS buffer type."""
    seg: MemSegment = zdc.rand()

@zdc.dataclass
class WriteAction(zdc.Action[DmaComponent]):
    data: DataBuffer = zdc.output()             # produces a buffer
    cfg: ConfigState = zdc.input()              # consumes a state
    stream_out: DataStream = zdc.output()       # produces a stream
    multi_buf: List[DataBuffer] = zdc.output(size=2)  # array of refs
```

The parser checks the annotated type's base classes:
- Inherits `Buffer`, `Stream`, or `State` -> flow-object reference
- Otherwise -> hardware signal port (existing behavior)

Metadata remains `{"kind": "flow_ref", "direction": "input"|"output"}`
for flow-object references, set automatically by the parser/decorator.

Corresponding base types for flow objects:

```python
class Buffer(Struct):
    """PSS buffer flow-object base type."""
    pass

class Stream(Struct):
    """PSS stream flow-object base type."""
    pass

class State(Struct):
    """PSS state flow-object base type.

    Has built-in 'initial' bool attribute and 'prev' reference.
    """
    initial: bool = False
    prev: Optional[Self] = None
```

### 2.4 Resource Reference Fields

Resource claims use `zdc.lock()` and `zdc.share()`:

```python
@zdc.dataclass
class DmaChannel(zdc.Resource):
    """PSS resource type."""
    priority: zdc.u4 = zdc.rand()

@zdc.dataclass
class TwoChannelTransfer(zdc.Action[DmaComponent]):
    chan_a: DmaChannel = zdc.lock()
    chan_b: DmaChannel = zdc.lock()
    ctrl:   CpuCore    = zdc.share()
    multi:  List[DmaChannel] = zdc.lock(size=4)  # array of locks
```

Metadata: `{"kind": "resource_ref", "claim": "lock"|"share"}`.

Base type:

```python
class Resource(Struct):
    """PSS resource base type.

    Has built-in 'instance_id' attribute.
    """
    instance_id: int = 0
```

### 2.5 Activity-Scoped Data Fields

PSS allows `action`-qualified data fields inside activities (traversed to
randomize values without execution). These have no special semantics in the
Zuspec Python representation -- use the standard `zdc.field()`:

```python
max_val: zdc.u4 = zdc.field()
```

The parser treats these as ordinary data fields. Their role in the activity
(randomized but not executed) is determined by how they are referenced in
the activity body.

---

## 3. Exec Block Methods

PSS defines several exec-block kinds. In Zuspec, these are plain methods
on the Action class.

### 3.1 Method Mapping

| PSS exec kind | Zuspec method         | Notes                        |
|----------------|-----------------------|------------------------------|
| pre_solve      | `def pre_solve(self)` | Already exists on Struct     |
| post_solve     | `def post_solve(self)`| Already exists on Struct     |
| pre_body       | `def pre_body(self)`  | New. Runs after post_solve   |
| body           | `async def body(self)`| Existing. Atomic action impl |

`run_start` and `run_end` are deferred -- they add complexity without
immediate payoff and can be added later without breaking changes.

Example:

```python
@zdc.dataclass
class WriteAction(zdc.Action[MyComponent]):
    addr: zdc.u32 = zdc.rand(domain=(0, 0xFFFF))

    def pre_solve(self):
        # non-random setup before solving
        pass

    def post_solve(self):
        # compute derived values after solving
        self.aligned_addr = self.addr & ~0x3

    async def body(self):
        await self.comp.write(self.aligned_addr, self.data)
```

### 3.2 Mutual Exclusion

An action with `activity()` shall not define `body()` and vice-versa.
The `@zdc.dataclass` decorator validates this at class-creation time.

---

## 4. Activity Declaration and Statements

This is the core of the design. An `async def activity(self)` method
is detected by the `@zdc.dataclass` decorator. Its body is parsed from
AST (never executed) and lowered to activity IR nodes, following the same
pattern as `@zdc.constraint`.

### 4.1 Detection

```python
async def activity(self):
    ...
```

The `@zdc.dataclass` decorator:
1. Detects `activity` in the class dict
2. Captures `inspect.getsource()` of the method
3. Parses it to `ast.AsyncFunctionDef`
4. Walks the body, producing `ActivityStmt` IR nodes
5. Stores the IR on the class as `cls.__activity__`

No separate `@zdc.activity` decorator is needed.

### 4.2 Action Traversal

#### Handle traversal

Calling an action-handle field traverses that action:

```python
async def activity(self):
    self.a1()                              # traverse handle a1
    self.a_arr[0]()                        # traverse array element
    self.a_arr()                           # traverse entire array
```

In the AST, `self.a1()` is an `ast.Call` on `ast.Attribute(value=Name('self'),
attr='a1')`. The activity parser recognizes this pattern and emits an
`ActivityTraversal` IR node.

#### Inline constraints via context manager

Inline constraints on a traversal use the `with` statement. The handle
is the context expression, and the body contains constraint expressions:

```python
async def activity(self):
    self.a1()                              # traverse, no constraints
    with self.a2():                        # traverse with inline constraints
        self.a2.f1 < 10
        self.a2.f2 > 0
```

In the AST, `with self.a2():` is an `ast.With` whose context expression is
a call on `self.a2`. The body statements are constraint expressions, parsed
using the existing `ConstraintParser.parse_expr()`. This maps to PSS
`a2 with { f1 < 10; f2 > 0; };`.

This approach keeps constraint syntax identical to `@constraint` methods
and avoids overloading function call arguments.

#### Anonymous traversal

The `do()` function traverses an action by type without a pre-declared handle:

```python
async def activity(self):
    do(WriteAction)                        # anonymous
    with do(WriteAction) as wr:            # anonymous with constraints
        wr.f1 < 10
```

In the AST, `do(WriteAction)` is an `ast.Call` with `func=ast.Name('do')` and
a class-reference arg. This maps to PSS `do WriteAction;`.

The `with do(Type) as name:` form provides both a label and inline
constraint scope:

```python
with do(WriteAction) as xfer:
    xfer.size > 10
```

This is equivalent to PSS `xfer: do WriteAction with { size > 10; };`.

#### Labeled anonymous traversal (no constraints)

Assignment captures the label when no constraints are needed:

```python
xfer = do(WriteAction)
```

In the AST this is `ast.Assign(targets=[Name('xfer')], value=Call(...))`.
The variable name `xfer` becomes the label identifier.

### 4.3 Sequential Blocks

By default, statements in an `activity` method execute sequentially,
matching PSS semantics. An explicit sequential block uses the `sequence()`
context manager:

```python
async def activity(self):
    self.a1()                  # sequential by default
    self.a2()
    with sequence():           # explicit sequential block
        self.a3()
        self.a4()
```

### 4.4 Parallel Blocks

```python
with parallel():
    self.a1()
    self.a2()

# With fine-grained join specification
with parallel(join_branch='L2'):
    L2 = do(ActionA)
    L3 = do(ActionB)
do(ActionC)                    # waits only for L2

with parallel(join_none=True):
    self.a1()
    self.a2()
do(ActionC)                    # no dependency on parallel branches

with parallel(join_select=1):
    self.a1()
    self.a2()
do(ActionC)                    # waits for 1 random branch

with parallel(join_first=1):
    self.a1()
    self.a2()
do(ActionC)                    # runtime: waits for first to finish
```

### 4.5 Schedule Blocks

```python
with schedule():
    self.a1()
    self.a2()
    self.a3()

# With join specs (same as parallel)
with schedule(join_branch='L1'):
    L1 = do(ActionA)
    L2 = do(ActionB)
do(ActionC)
```

### 4.6 Atomic Blocks

```python
with atomic():
    self.a1()
    self.a2()
```

Maps directly to PSS `atomic { a1; a2; }`.

### 4.7 Repeat / Loops

#### Count-based repeat (PSS `repeat(N)`)

Python `for ... in range(...)` maps to PSS repeat:

```python
for i in range(3):
    self.a1()
    self.a2()

# Dynamic count from a rand field
for i in range(self.count):
    self.a1()
```

The activity parser detects `for target in Call(Name('range'), ...)` and
emits `ActivityRepeat(count=expr, index=target)`.

#### do_while / while_do (PSS `repeat { } while (cond)`)

PSS has `repeat { body } while (cond)` (do-while semantics: body executes
at least once, then condition is checked). Python has no native do-while.

We provide two constructs:

**`do_while(cond)`** -- Body executes first, then condition is checked
(PSS `repeat-while` semantics):

```python
with do_while(self.s1.last_one != 0):
    self.s1()
```

**`while_do(cond)`** -- Condition is checked first, then body executes
(standard while-loop semantics, not in PSS but useful):

```python
with while_do(self.remaining > 0):
    do(ProcessAction)
```

Both accept a bare expression (no lambda). Since the activity body is
parsed from AST, the expression is extracted as an AST node, never
evaluated.

#### Foreach (PSS `foreach`)

Iteration over a collection:

```python
for item in self.data_array:
    do(ProcessAction)

# With index
for i, item in enumerate(self.data_array):
    with self.action1():
        self.action1.val <= item
```

The parser detects `for target in Attribute(Name('self'), ...)` and emits
`ActivityForeach`. When `enumerate()` wraps the iterable, an index variable
is also captured.

### 4.8 Select

PSS `select` chooses one branch to execute. Since Python has no direct
analog, we use a context manager with nested `with branch()` blocks:

```python
with select():
    with branch():
        self.action1()
    with branch():
        self.action2()
```

#### Guards and weights

```python
with select():
    with branch(guard=self.a == 0, weight=20):
        self.action1()
    with branch(guard=self.a.in_(range(0, 4)), weight=30):
        self.action2()
    with branch(weight=50):
        self.action3()
```

`guard=` is a boolean expression parsed from AST. `weight=` is an integer
expression. When no guard/weight is specified, the branch is unconditional
with weight 1.

### 4.9 If-Else

Standard Python `if/elif/else`:

```python
if self.x > 5:
    self.a1()
else:
    self.a2()
```

Maps directly to PSS `if (x > 5) a1; else a2;`.

### 4.10 Match

Python structural pattern matching (3.10+):

```python
match self.security_level:
    case SecurityLevel.LOW:
        self.action1()
    case SecurityLevel.MEDIUM:
        self.action2()
    case _:
        self.action3()
```

Maps to PSS `match (security_level) { ... }`.

### 4.11 Replicate

Replicate is a generative construct that expands in-place. It differs from
`repeat` because it does not introduce a sequential loop -- the expansion
takes the scheduling semantics of its enclosing scope.

```python
with parallel():
    for i in replicate(self.count):
        do(ActionA)
        do(ActionB)
```

The parser distinguishes `replicate()` from `range()` in the `for` iterator.
`replicate()` produces `ActivityReplicate`, which expands N copies into the
enclosing scope.

#### Labeled replicate (for hierarchical references)

```python
with parallel():
    for i in replicate(self.count, label='RL'):
        a = do(ActionA)
        b = do(ActionB)

# Reference: RL[0].a, RL[count-1].b
```

### 4.12 Flow-Object Binding in Activities

Explicit binding of flow objects between sub-actions:

```python
async def activity(self):
    self.producer()
    self.consumer()
    bind(self.producer.data_out, self.consumer.data_in)
```

`bind()` in an activity context emits an `ActivityBind` IR node.

### 4.13 Scheduling Constraints in Activities

Scheduling constraints within an activity use a `with constraint():`
context manager. This keeps the constraint syntax consistent with
`@constraint` methods while scoping them to the activity:

```python
async def activity(self):
    self.a1()
    self.a2()
    with constraint():
        self.a1.size + self.a2.size < 100
        self.a1.addr != self.a2.addr
```

The parser recognizes `with constraint():` and collects the body expressions
as scheduling constraints on the enclosing activity. These constrain
relationships between sub-action fields.

### 4.14 Activity with Inheritance

When a compound action inherits from another compound action, the
sub-class activity shadows the base. The `super().activity()` call
traverses the base activity:

```python
@zdc.dataclass
class ExtAction(BaseAction, zdc.Action[MyComponent]):
    async def activity(self):
        super().activity()         # traverse base activity
        do(ActionC)
```

In the AST, `super().activity()` is an `ast.Call` on
`ast.Attribute(value=ast.Call(func=ast.Name('super')), attr='activity')`.
The parser recognizes this pattern and emits an `ActivitySuper` IR node.
This maps to PSS `super;` in an activity block.

### 4.15 Activity Extension

When type extension contributes activities, they are combined in an implied
`schedule` block (per PSS semantics). Extensions are defined as subclasses
with the `@zdc.extend` decorator:

```python
# Original
@zdc.dataclass
class EntryAction(zdc.Action[TopComponent]):
    async def activity(self):
        do(ActionA)

# Extension (separate module)
@zdc.extend
class EntryActionExt(EntryAction):
    async def activity(self):
        do(ActionB)
```

The `@zdc.extend` decorator examines the base classes to determine the
type being extended. No explicit type argument is needed. The extended type
is resolved from the inheritance chain.

Multiple extensions of the same type produce an implied schedule block,
equivalent to PSS extension semantics (Section 12.6).

---

## 5. Pool Declarations

Pools hold flow and resource objects. In PSS, pools are declared in
component scope with bind directives.

```python
@zdc.dataclass
class TopComponent(zdc.Component):
    dma_channels: zdc.Pool[DmaChannel] = zdc.pool(size=4)
    config_pool: zdc.Pool[ConfigState] = zdc.pool(size=1)

    @zdc.bind
    def bindings(self, s: Self):
        return {
            s.dma_channels: '*',           # bind to all actions needing DmaChannel
            s.config_pool: s.sub.action1,  # bind to specific action
        }
```

`zdc.Pool[T]` is a generic type. `zdc.pool(size=N)` sets the pool size.
Bind directives use the existing `@zdc.bind` mechanism.

---

## 6. Complete Example

Translating PSS LRM Example 45 (compound action) and related patterns:

### PSS DSL

```
buffer data_buff {
    rand mem_segment_s seg;
};

resource DMA_channel_s {
    rand bit[3:0] priority;
};

component dma_c {
    pool[4] DMA_channel_s chan_pool;
    bind chan_pool *;

    action write_data {
        output data_buff data;
        lock DMA_channel_s chan;
        rand bit[7:0] size;

        exec body C = """...""";
    };

    action read_data {
        input data_buff data;
        lock DMA_channel_s chan;
    };

    action dma_xfer {
        write_data wr;
        read_data rd;

        activity {
            wr;
            rd with { chan.priority > 5; };
        }
    };
};
```

### Zuspec Python

```python
import zuspec.dataclasses as zdc
from typing import List


@zdc.dataclass
class MemSegment(zdc.Struct):
    base: zdc.u32 = zdc.rand()
    size: zdc.u32 = zdc.rand()


@zdc.dataclass
class DataBuff(zdc.Buffer):
    seg: MemSegment = zdc.rand()


@zdc.dataclass
class DmaChannel(zdc.Resource):
    priority: zdc.u4 = zdc.rand()


@zdc.dataclass
class DmaComponent(zdc.Component):
    chan_pool: zdc.Pool[DmaChannel] = zdc.pool(size=4)

    @zdc.bind
    def bindings(self, s):
        return {s.chan_pool: '*'}


@zdc.dataclass
class WriteData(zdc.Action[DmaComponent]):
    data: DataBuff = zdc.output()
    chan: DmaChannel = zdc.lock()
    size: zdc.u8 = zdc.rand()

    async def body(self):
        # target implementation
        ...


@zdc.dataclass
class ReadData(zdc.Action[DmaComponent]):
    data: DataBuff = zdc.input()
    chan: DmaChannel = zdc.lock()

    async def body(self):
        ...


@zdc.dataclass
class DmaXfer(zdc.Action[DmaComponent]):
    wr: WriteData
    rd: ReadData

    async def activity(self):
        self.wr()
        with self.rd():
            self.rd.chan.priority > 5
```

### Advanced Scenario

```python
@zdc.dataclass
class StressTest(zdc.Action[TopComponent]):
    count: zdc.u8 = zdc.rand(domain=(2, 8))

    async def activity(self):
        for i in range(self.count):
            with parallel():
                with do(WriteData) as wr:
                    wr.size > 16
                do(ReadData)
            with select():
                with branch(weight=70):
                    do(DmaXfer)
                with branch(weight=30):
                    do(ReadData)


@zdc.dataclass
class ForkJoinTest(zdc.Action[TopComponent]):
    async def activity(self):
        with parallel(join_first=1):
            do(WriteData)
            do(WriteData)
        do(ReadData)               # starts after first write completes
```

---

## 7. Activity Parser Design

### 7.1 Parser Structure

`ActivityParser` (new class, sibling to `ConstraintParser`) walks the AST of
an `async def activity(self)` method and produces activity IR nodes.

```
activity method source
    --> ast.parse()
    --> ast.AsyncFunctionDef
    --> ActivityParser.parse_body(func_def.body)
    --> List[ActivityStmt]   (IR nodes)
```

### 7.2 AST Pattern Recognition

| Python AST pattern                          | Activity IR node         |
|---------------------------------------------|--------------------------|
| `ast.Call(func=Attr(self, name))`           | `ActivityTraversal`      |
| `ast.With(ctx=Call(Attr(self, name)))`      | `ActivityTraversal` + constraints |
| `ast.Call(func=Name('do'), args=[type])`    | `ActivityAnonTraversal`  |
| `ast.With(ctx=Call(Name('do')))`            | `ActivityAnonTraversal` + constraints |
| `ast.Assign(value=Call(do(...)))`           | `ActivityAnonTraversal` (labeled) |
| `ast.With(Name('parallel'))`               | `ActivityParallel`       |
| `ast.With(Name('schedule'))`               | `ActivitySchedule`       |
| `ast.With(Name('sequence'))`               | `ActivitySequence`       |
| `ast.With(Name('atomic'))`                 | `ActivityAtomic`         |
| `ast.With(Name('select'))`                 | `ActivitySelect`         |
| `ast.With(Name('branch'))`                 | `SelectBranch`           |
| `ast.With(Name('do_while'))`               | `ActivityDoWhile`        |
| `ast.With(Name('while_do'))`               | `ActivityWhileDo`        |
| `ast.With(Name('constraint'))`             | `ActivityConstraint`     |
| `ast.For(iter=Call(Name('range')))`         | `ActivityRepeat`         |
| `ast.For(iter=Call(Name('replicate')))`     | `ActivityReplicate`      |
| `ast.For(iter=Attr(self, collection))`      | `ActivityForeach`        |
| `ast.If`                                   | `ActivityIfElse`         |
| `ast.Match`                                | `ActivityMatch`          |
| `ast.Call(func=Name('bind'))`              | `ActivityBind`           |
| `Call(Attr(Call(Name('super')),'activity'))`| `ActivitySuper`          |

### 7.3 Constraint Sub-Parsing

Inline constraints (body of `with self.handle():` or `with do(T) as x:`)
reuse the existing `ConstraintParser.parse_expr()` to produce constraint
IR nodes. This avoids duplicating expression parsing logic.

---

## 8. Activity IR Nodes

New IR node classes in `zuspec.dataclasses.ir.activity`:

```python
@dc.dataclass(kw_only=True)
class ActivityStmt(Base):
    """Base class for all activity IR nodes."""
    pass

@dc.dataclass(kw_only=True)
class ActivityTraversal(ActivityStmt):
    """Traversal of a declared action handle."""
    handle: str                                 # field name on self
    index: Optional[Expr] = None                # array subscript
    inline_constraints: List[Expr] = field(default_factory=list)

@dc.dataclass(kw_only=True)
class ActivityAnonTraversal(ActivityStmt):
    """Anonymous traversal by action type."""
    action_type: str                            # qualified type name
    label: Optional[str] = None                 # label if assigned
    inline_constraints: List[Expr] = field(default_factory=list)

@dc.dataclass(kw_only=True)
class ActivitySequenceBlock(ActivityStmt):
    """Sequential block (default or explicit)."""
    stmts: List[ActivityStmt] = field(default_factory=list)

@dc.dataclass(kw_only=True)
class ActivityParallel(ActivityStmt):
    """Parallel block with optional join spec."""
    stmts: List[ActivityStmt] = field(default_factory=list)
    join_spec: Optional[JoinSpec] = None

@dc.dataclass(kw_only=True)
class ActivitySchedule(ActivityStmt):
    """Schedule block with optional join spec."""
    stmts: List[ActivityStmt] = field(default_factory=list)
    join_spec: Optional[JoinSpec] = None

@dc.dataclass(kw_only=True)
class ActivityAtomic(ActivityStmt):
    """Atomic block."""
    stmts: List[ActivityStmt] = field(default_factory=list)

@dc.dataclass(kw_only=True)
class ActivityRepeat(ActivityStmt):
    """Count-based repeat."""
    count: Expr
    index_var: Optional[str] = None
    body: List[ActivityStmt] = field(default_factory=list)

@dc.dataclass(kw_only=True)
class ActivityDoWhile(ActivityStmt):
    """Do-while loop (body executes first, then condition checked).
    Maps to PSS repeat-while."""
    condition: Expr
    body: List[ActivityStmt] = field(default_factory=list)

@dc.dataclass(kw_only=True)
class ActivityWhileDo(ActivityStmt):
    """While-do loop (condition checked first, then body executes)."""
    condition: Expr
    body: List[ActivityStmt] = field(default_factory=list)

@dc.dataclass(kw_only=True)
class ActivityForeach(ActivityStmt):
    """Foreach over a collection."""
    iterator: str
    collection: Expr
    index_var: Optional[str] = None
    body: List[ActivityStmt] = field(default_factory=list)

@dc.dataclass(kw_only=True)
class ActivitySelect(ActivityStmt):
    """Select statement (choose one branch)."""
    branches: List[SelectBranch] = field(default_factory=list)

@dc.dataclass(kw_only=True)
class SelectBranch(Base):
    """One branch of a select statement."""
    guard: Optional[Expr] = None
    weight: Optional[Expr] = None
    body: List[ActivityStmt] = field(default_factory=list)

@dc.dataclass(kw_only=True)
class ActivityIfElse(ActivityStmt):
    """If-else branch."""
    condition: Expr
    if_body: List[ActivityStmt] = field(default_factory=list)
    else_body: List[ActivityStmt] = field(default_factory=list)

@dc.dataclass(kw_only=True)
class ActivityMatch(ActivityStmt):
    """Match statement."""
    subject: Expr
    cases: List[MatchCase] = field(default_factory=list)

@dc.dataclass(kw_only=True)
class MatchCase(Base):
    """One case of a match statement."""
    pattern: Expr                              # range or value
    body: List[ActivityStmt] = field(default_factory=list)
    is_default: bool = False

@dc.dataclass(kw_only=True)
class ActivityReplicate(ActivityStmt):
    """Replicate statement (generative in-place expansion)."""
    count: Expr
    index_var: Optional[str] = None
    label: Optional[str] = None
    body: List[ActivityStmt] = field(default_factory=list)

@dc.dataclass(kw_only=True)
class ActivityConstraint(ActivityStmt):
    """Scheduling constraint block within an activity."""
    exprs: List[Expr] = field(default_factory=list)

@dc.dataclass(kw_only=True)
class ActivityBind(ActivityStmt):
    """Explicit flow-object binding."""
    src: Expr
    dst: Expr

@dc.dataclass(kw_only=True)
class ActivitySuper(ActivityStmt):
    """Invoke base-class activity via super().activity()."""
    pass

# Join specifications
@dc.dataclass(kw_only=True)
class JoinSpec(Base):
    pass

@dc.dataclass(kw_only=True)
class JoinBranch(JoinSpec):
    labels: List[str] = field(default_factory=list)

@dc.dataclass(kw_only=True)
class JoinSelect(JoinSpec):
    count: Expr

@dc.dataclass(kw_only=True)
class JoinNone(JoinSpec):
    pass

@dc.dataclass(kw_only=True)
class JoinFirst(JoinSpec):
    count: Expr
```

---

## 9. Runtime Execution Model

### 9.1 Python Execution

For direct Python execution (not pre-generated), the activity IR is
interpreted by an `ActivityExecutor`:

1. `ActivityTraversal` / `ActivityAnonTraversal`:
   - Instantiate the action type
   - Bind to a component instance (random selection from matching instances)
   - Run `pre_solve()` -> solve rand fields -> `post_solve()` -> `pre_body()`
     -> `body()` (atomic) or recurse into sub-activity (compound)

2. `ActivitySequenceBlock`: Execute stmts in order.

3. `ActivityParallel`: Launch stmts as concurrent `asyncio.Task`s, await
   per the join spec.

4. `ActivitySchedule`: Build a dependency graph from flow/resource
   constraints, topologically sort, execute.

5. `ActivitySelect`: Evaluate guards, compute weights, randomly pick one
   enabled branch, execute it.

6. Control flow (repeat, foreach, if-else, match): Standard interpretation.

### 9.2 C Code Generation

The activity IR maps to a scheduling graph that a C code generator can
emit as:
- Sequential function calls
- `pthread` or task-based parallelism for parallel/schedule blocks
- Static loop unrolling for replicate
- Standard C control flow for repeat/if/match

---

## 10. API Surface Summary

### New Base Types

| Type            | Purpose                           |
|-----------------|-----------------------------------|
| `zdc.Buffer`    | Base for PSS buffer flow objects   |
| `zdc.Stream`    | Base for PSS stream flow objects   |
| `zdc.State`     | Base for PSS state flow objects    |
| `zdc.Resource`  | Base for PSS resource objects      |

### New Field Helpers

| Helper              | Metadata                                        |
|----------------------|-------------------------------------------------|
| `zdc.lock()`        | `{"kind": "resource_ref", "claim": "lock"}`     |
| `zdc.share()`       | `{"kind": "resource_ref", "claim": "share"}`    |
| `zdc.pool(size=N)`  | `{"kind": "pool", "size": N}`                   |

### Existing Helpers (reused, context-sensitive)

| Helper              | In Action scope                                  |
|----------------------|--------------------------------------------------|
| `zdc.input()`       | Flow-object ref if type is Buffer/Stream/State   |
| `zdc.output()`      | Flow-object ref if type is Buffer/Stream/State   |
| `zdc.field()`       | Activity-scoped data field (no special semantics) |

### Inferred Fields (no helper needed)

| Pattern               | Meaning                                     |
|-----------------------|---------------------------------------------|
| `f: SomeAction`       | Action handle (type inherits from `Action`)  |
| `f: List[SomeAction]` | Action handle array                         |

### New Decorator

| Decorator        | Purpose                                    |
|------------------|--------------------------------------------|
| `@zdc.extend`    | Marks class as a type extension (base type inferred from inheritance) |

### Activity DSL Functions (AST-only, never executed)

| Function              | PSS Equivalent                          |
|-----------------------|-----------------------------------------|
| `do(Type)`            | `do Type;`                              |
| `with do(Type) as x:` | `x: do Type with {...};`               |
| `with self.h():`      | `h with {...};`                         |
| `parallel(...)`       | `parallel [join_spec] { ... }`          |
| `schedule(...)`       | `schedule [join_spec] { ... }`          |
| `sequence()`          | `sequence { ... }`                      |
| `atomic()`            | `atomic { ... }`                        |
| `select()`            | `select { ... }`                        |
| `branch(...)`         | Select branch with guard/weight         |
| `do_while(cond)`      | `repeat { ... } while (cond);`          |
| `while_do(cond)`      | While-do loop (condition first)         |
| `replicate(N, ...)`   | `replicate (N) [label[]:] { ... }`      |
| `constraint()`        | Scheduling constraint block             |
| `bind(src, dst)`      | `bind src dst;`                         |
| `super().activity()`  | `super;`                                |

---

## 11. Open Issues

### 11.1 Type Extension Mechanism

`@zdc.extend` for contributing activity blocks to existing actions
interacts with module loading order and the IR merge step. Needs
investigation pending review of existing notes on:
- How extensions discover the base type (resolved: from inheritance)
- How multiple extensions across packages are ordered
- How the implied schedule block is constructed

### 11.2 Flow Object Binding Defaults

PSS uses a combination of type-based default binding and explicit `bind`
directives. The current `@zdc.bind` decorator handles component-level
bindings. Activity-level `bind()` calls for explicit flow-object binding
need integration with pool resolution.

### 11.3 Component Scope for Action Declarations

PSS requires non-abstract actions to be declared within a component scope.
In Zuspec, `Action[T]` captures this via the type parameter. However,
Python module-level class declarations don't enforce "inside a component"
at the syntactic level. This is validated at IR construction time rather
than at class definition time.

### 11.4 Hierarchical Activity References

PSS allows constraining sub-actions from outer scopes via hierarchical
references (e.g., `do mem2mem_chain with { xfer.size > 10; }`). In the
proposed design, this works when traversing via `with do(T) as x:` with
inline constraints, but the scoping and name resolution rules for
hierarchical references through labeled traversals need further
specification.

### 11.5 `do_while` vs `while_do` Naming

Both constructs are provided. `do_while` maps directly to PSS
`repeat-while`. `while_do` is a standard pre-condition loop not present
in PSS but useful for Python-native patterns. Need to confirm whether
both should be in the initial implementation or if `while_do` should be
deferred.

---

## 12. Overlooked Opportunities

### 12.1 Constraint and Activity Co-Parsing

The `ConstraintParser` and `ActivityParser` share significant AST-walking
infrastructure. A unified `ZuspecASTParser` base class could handle common
patterns (attribute access, comparisons, constants) with specialized
subclasses for constraint vs activity semantics. This reduces code
duplication and ensures consistent expression handling.

### 12.2 Static Validation via MyPy Plugin

The existing MyPy plugin (`flake8_zdc_struct.py`) validates struct profiles.
This can be extended to validate:
- Atomic/compound mutual exclusion (body vs activity)
- Flow object direction rules (buffer: one output, N inputs)
- Resource claim validity
- Action handle traversal-once rules in sequential/parallel scopes

Static checking catches PSS semantic errors at edit-time rather than at
solve-time.

### 12.3 Activity Visualization

The activity IR is a structured tree that maps naturally to scheduling
graphs (DAGs). A `to_dot()` method on activity IR nodes could generate
Graphviz output for visual debugging of scenario structure. The existing
`regfile.dot` / `regfile.png` pattern in the repo suggests this
infrastructure already exists in embryonic form.

### 12.4 Incremental Parsing

Activities and constraints are parsed from source via `inspect.getsource()`.
For large models, caching parsed IR keyed by source hash avoids redundant
parsing. This is straightforward to add in the decorator.

### 12.5 Python `async for` / `async with` for Runtime

While the AST-parsed activity is never executed directly, the runtime
executor could expose the same API surface as `async` Python:

```python
# Runtime execution (not user-written, but the executor's internal API)
async def _execute_parallel(self, stmts):
    tasks = [asyncio.create_task(self._execute(s)) for s in stmts]
    await asyncio.gather(*tasks)
```

This means the Python runtime can directly leverage `asyncio` for
parallel/schedule block execution without a custom scheduler.

### 12.6 Coverage Integration

PSS 3.0 adds behavioral coverage (monitors, Section 19). Activities
and monitor activities share significant syntax. The activity IR could
be reused for monitor scenario specification, with monitor-specific
nodes (concat, eventually, overlap) added as extensions.

### 12.7 Template / Generic Actions

PSS supports template actions. Python generics (`class MyAction[T, N]:`)
could map to PSS template parameters. This is not designed here but the
`Action[ComponentType]` pattern already uses one type parameter; extending
to additional template value and type parameters is a natural evolution.

### 12.8 Resource-Aware `asyncio` Scheduling

For Python runtime execution, resource lock/share semantics map naturally
to `asyncio.Semaphore` (share) and `asyncio.Lock` (lock). The runtime
executor should integrate these with the existing `ClaimPool` / `Lock`
infrastructure already present in `zuspec.dataclasses.rt`.

---

## 13. Implementation Priorities

Suggested phased implementation:

**Phase 1 -- Core**
- Activity detection in `@zdc.dataclass` and `ActivityParser` (sequential, traversal)
- Action handle inference from type annotations
- `ActivityTraversal` and `ActivityAnonTraversal` IR nodes
- Inline constraints via `with self.handle():` / `with do(T) as x:`
- Basic sequential executor in Python

**Phase 2 -- Scheduling**
- `parallel()`, `schedule()`, `atomic()` context managers and IR
- Join specifications
- `asyncio`-based parallel executor

**Phase 3 -- Control Flow**
- `for/range` -> repeat, `for/collection` -> foreach
- `if/else`, `match/case`
- `select()` / `branch()`
- `replicate()`
- `do_while()` / `while_do()`
- `with constraint():` for scheduling constraints

**Phase 4 -- Flow and Resource Objects**
- `Buffer`, `Stream`, `State`, `Resource` base types
- `lock()`, `share()` field helpers
- Pool declarations and bind integration

**Phase 5 -- Extensions and Codegen**
- `@zdc.extend` for type extensions
- C code generation from activity IR
- MyPy plugin extensions
- Activity visualization
