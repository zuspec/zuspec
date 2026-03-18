# PSS to Runtime Objects: Design Document

## Goal

Transform a PSS string (as in `zuspec-fe-pss/tests/python/execution/test_action.py`) into
live Python runtime objects that use the `zuspec-dataclasses` runtime — then construct and
execute them exactly as lines 35-40 of `zuspec-dataclasses/tests/unit/test_action.py` do.

The equivalent hand-written Python for the PSS below:

```pss
component MyC {
  bit[32] val;
  action MyA {
    bit[32] val;
    exec body { val = 15; }
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
```

…is:

```python
@zdc.dataclass
class MyC(zdc.Component):
    val: zdc.u32 = zdc.field()

@zdc.dataclass
class Top(zdc.Component):
    c1: MyC = zdc.inst()
    c2: MyC = zdc.inst()
    def __post_init__(self):
        self.c1.val = 21
        self.c2.val = 22

@zdc.dataclass
class MyA(zdc.Action[MyC]):
    val: zdc.u32 = zdc.field()
    async def body(self):
        self.val = 15

top = Top()
a = await MyA()(top)        # lines 35-40 of test_action.py
assert a.comp.val in [21, 22]
assert a.val == 15
```

No source-code generation is needed — we create Python class and callable objects **directly
in memory**.

---

## Pipeline

```
PSS string
    │
    ▼  zuspec.fe.pss.Parser.parses() + .link()
PSS AST (linked SymbolTypeScope tree)
    │
    ▼  zuspec.fe.pss.AstToIrTranslator.translate()   [NEEDS EXTENSION]
IR context  (AstToIrContext.type_map: name → ir.DataType)
    │
    ▼  NEW: IrToRuntimeBuilder.build()
Python class dict  { 'MyC': <class>, 'Top': <class>, 'MyA': <class>, ... }
    │
    ▼  caller instantiates Top(), runs await MyA()(top)
```

### Step 1 — Parse (works today)

```python
from zuspec.fe.pss import Parser
parser = Parser()
parser.parses([('test.pss', pss_code)])
ast_root = parser.link()
```

### Step 2 — AST → IR (partially works; needs extension)

```python
from zuspec.fe.pss import AstToIrTranslator
translator = AstToIrTranslator()
ir_ctx = translator.translate(ast_root)
# ir_ctx.type_map → { 'MyC': DataTypeComponent, 'MyA': DataTypeClass, 'Top': DataTypeComponent }
```

**What works today:** Component and action *fields* are translated.

**What is missing (see § Gaps below):** exec blocks and action-parent tracking.

### Step 3 — IR → Runtime classes (new code)

```python
from zuspec.fe.pss.ir_to_runtime import IrToRuntimeBuilder
builder = IrToRuntimeBuilder(ir_ctx)
classes = builder.build()   # { 'MyC': cls, 'Top': cls, 'MyA': cls }
```

Core of `IrToRuntimeBuilder.build()`:

1. **Topological sort** `type_map` so that `DataTypeRef` dependencies are resolved before
   the type that references them.
2. For each `DataTypeComponent` → call `_build_component(dt)`.
3. For each `DataTypeClass` (action) → call `_build_action(dt)`.

#### `_build_component`

```python
def _build_component(self, dt: ir.DataTypeComponent) -> type:
    annotations = {}
    defaults    = {}

    for f in dt.fields:
        py_type, default = self._field_to_zdc(f)
        annotations[f.name] = py_type
        defaults[f.name]    = default

    ns = {'__annotations__': annotations, **defaults}

    # exec init_down → __post_init__
    init_down = dt.get_function('init_down')   # see gap note
    if init_down:
        ns['__post_init__'] = self._build_post_init(init_down)

    cls = type(dt.name, (zdc.Component,), ns)
    return zdc.dataclass(cls)
```

#### `_build_action`

The action's *type parameter* T comes from its `parent_comp_name` attribute (see Gap 1).

```python
def _build_action(self, dt: ir.DataTypeClass) -> type:
    parent_name = self._action_parent[dt.name]     # e.g. 'MyC'
    comp_type   = self.python_classes[parent_name]
    ActionBase  = zdc.Action[comp_type]

    annotations = {}
    defaults    = {}
    for f in dt.fields:
        py_type, default = self._field_to_zdc(f)
        annotations[f.name] = py_type
        defaults[f.name]    = default

    ns = {'__annotations__': annotations, **defaults}

    body_fn = dt.get_function('body')   # see gap note
    if body_fn:
        ns['body'] = self._build_body_fn(body_fn)

    import types as pytypes
    cls = pytypes.new_class(dt.name, (ActionBase,), {}, lambda d: d.update(ns))
    return cls
```

(`types.new_class` is required because `type()` cannot resolve generic `Action[T]` MRO
entries — verified experimentally.)

#### `_field_to_zdc`

```python
INT_TYPE_MAP = {
    # (bits, signed) → zdc type
    (1,  False): zdc.u1,
    (8,  False): zdc.u8,
    (16, False): zdc.u16,
    (32, False): zdc.u32,
    (64, False): zdc.u64,
    (8,  True):  zdc.i8,
    (16, True):  zdc.i16,
    (32, True):  zdc.i32,
    (64, True):  zdc.i64,
}

def _field_to_zdc(self, f: ir.Field):
    dt = f.datatype
    if isinstance(dt, ir.DataTypeInt):
        py_type = INT_TYPE_MAP.get((dt.bits, dt.signed), int)
        return py_type, zdc.field()
    elif isinstance(dt, ir.DataTypeRef):
        ref_cls = self.python_classes[dt.ref_name]   # resolved earlier
        return ref_cls, zdc.inst()
    else:
        # fallback
        return int, zdc.field()
```

#### `_build_body_fn` / `_build_post_init`

The IR `Function.body` is a list of `ir.Stmt` nodes. For the initial scope (simple
assignments), we generate Python closures directly from the IR without going through the
full `rt/executor.py` machinery:

```python
def _build_body_fn(self, func: ir.Function):
    stmts = func.body   # list[ir.Stmt]

    async def body(self):
        for stmt in stmts:
            _exec_stmt(self, stmt)
    return body

def _build_post_init(self, func: ir.Function):
    stmts = func.body

    def __post_init__(self):
        for stmt in stmts:
            _exec_stmt(self, stmt)
    return __post_init__
```

`_exec_stmt` is a small helper that handles `StmtAssign` over simple 1- and 2-segment
`ExprRef` paths (sufficient for the target test cases). The existing `rt/executor.py`
`Executor` class can be used or adapted for more complex statement types later.

---

## Gaps That Must Be Closed

### Gap 1 — Action-parent association not tracked in IR

**Problem:** `_translate_action` creates `DataTypeClass(name='MyA', ...)` but records no
information about the enclosing component (`MyC`). Yet `IrToRuntimeBuilder` needs this to
select the type parameter `T` for `Action[T]`.

**Where in code:** `ast_to_ir.py:_translate_action` (line 250).

**Fix options:**

- **(A — preferred)** Add `parent_comp_names: Dict[str, str]` to `AstToIrContext` and
  populate it in `_translate_component` when it calls `_translate_action`:

  ```python
  # in _translate_component, after translating nested action:
  ctx.parent_comp_names[action_ir.name] = comp_name
  ```

- **(B)** Add a `parent_comp: Optional[str]` field to `ir.DataTypeClass`.

Option A is non-invasive and keeps the IR model unchanged.

### Gap 2 — exec body blocks not translated

**Problem:** `_translate_action` iterates `action.children()` but only handles
`pss_ast.Field`. `ExecBlock` children (which carry the `exec body { ... }` statements)
are silently skipped.

**Where in code:** `ast_to_ir.py:_translate_action` lines 289-296.

**Fix:** Add an `ExecBlock` branch:

```python
elif isinstance(child, pss_ast.ExecBlock):
    kind = child.getKind()
    if kind == pss_ast.ExecKind.ExecKind_Body:
        stmts = self._translate_exec_block(ctx, child)
        func = ir.Function(name='body', is_async=True, body=stmts)
        action_ir.functions.append(func)
    # (pre_solve / post_solve can be handled here too)
```

The key AST navigation inside an `ExecBlock`:

```
ExecBlock
  ProceduralStmtAssignment
    lhs: ExprRefPathContext
      .getHier_id() → ExprHierarchicalId
        .getElem(i) → ExprMemberPathElem
          .getId() → ExprId → .getId() → "val"
    rhs: ExprUnsignedNumber → .getValue() → 15
```

### Gap 3 — exec init_down blocks not translated

**Problem:** `_translate_component` only handles `Field`, `FunctionDefinition`, `Action`,
and `Struct` children. `ExecBlock(kind=InitDown)` is skipped.

**Where in code:** `ast_to_ir.py:_translate_component` lines 220-237.

**Fix:** Add an `ExecBlock` branch analogous to Gap 2 but producing a non-async function
named `'init_down'` that becomes `__post_init__` in the runtime class.

For `init_down`, assignment paths are 2-segment (`c1.val = 21`):

```
ExprHierarchicalId
  getElem(0) → ExprMemberPathElem → getId() → ExprId → "c1"
  getElem(1) → ExprMemberPathElem → getId() → ExprId → "val"
```

The generated statement closure sets `getattr(getattr(self, 'c1'), 'val') = 21`.

### Gap 4 — `DataTypeClass` has no `get_function` helper

`ir.DataTypeStruct` has a `functions: List[Function]` field but no lookup method.

**Fix:** Add a trivial helper (either to the IR class or to `IrToRuntimeBuilder`):

```python
def _get_function(self, dt, name):
    return next((f for f in dt.functions if f.name == name), None)
```

### Gap 5 — Topological ordering for type resolution

Components that are fields of other components (`DataTypeRef`) must be built before the
types that reference them.

**Fix:** Simple DFS topological sort over `type_map` using `DataTypeRef.ref_name` edges.
This is straightforward and only needs to handle the DAG case (PSS does not allow cycles
in component field types).

---

## Open Issues / Questions

### OI-1: Statement IR representation vs. direct AST traversal

The current `_translate_exec_scope` in `ast_to_ir.py` produces `ir.Stmt` nodes
(`StmtAssign`, etc.) with `ir.Expr` nodes (`ExprRefUnresolved`, etc.). The `rt/executor.py`
`Executor` class was designed for the *signal/process* model (reading/writing named signal
paths on a component), not the action-body model.

**Decision:** Use and extend `rt/executor.py` from the start. The `Executor` class already
handles `StmtAssign`, `StmtIf`, `StmtWhile`, `ExprConstant`, `ExprBin`, etc. It needs
to be extended to resolve field references in the action-body context (self.field), but
building on it now avoids throwing away work later. `IrToRuntimeBuilder._build_body_fn`
will instantiate an action-aware `ActionBodyExecutor(Executor)` subclass that overrides
field-path resolution.

### OI-2: How to handle `ExprRefUnresolved` in action body context

In the IR, `val = 15` becomes `StmtAssign(target=ExprRefUnresolved(name='val'), value=ExprConstant(15))`.
`ExprRefUnresolved` is designed for the process/signal executor where the name is looked up
as a signal path. In an action body, `val` always means `self.val`.

**Decision:** Resolve at translation time. When `_translate_exec_scope` is called inside an
action scope (i.e., `ctx.current_scope()` is a `DataTypeClass`), single-name references
must be resolved against the action's own field names. If the name matches a field of the
current action, emit `ExprAttribute(base=ExprSelf(), attr=name)` rather than
`ExprRefUnresolved`. This keeps the IR clean and makes all downstream consumers
(executor, future backends) see fully-resolved expressions.

### OI-3: Nested action namespace

In PSS, `MyA` is textually nested inside `MyC`. After linking, the symbol tree has
`root → MyC (SymbolTypeScope) → MyA (SymbolTypeScope)`. The current translator flattens
both into the top-level `ctx.type_map` under the simple names `'MyC'` and `'MyA'`.

This is fine as long as action names are unique across all components. If not (two
components each with an action named `Run`), the second overwrites the first in `type_map`.

**Decision:** Use a qualified namespace from the start. Concretely:

- `IrToRuntimeBuilder.build()` returns a dict keyed by **simple name** for top-level types
  (components) and **qualified name** (`'MyC::MyA'`) for nested actions.
- Additionally, each action class is **set as a class attribute** on its parent component
  class, so callers can write `classes['MyC'].MyA` — matching PSS dot-notation naturally.

```python
# Both access paths work:
MyA = classes['MyC::MyA']
MyA = classes['MyC'].MyA     # attribute on the component class
```

`AstToIrContext` will use `'MyC::MyA'` as the `type_map` key for the action (rather than
flattening to `'MyA'`), and `parent_comp_names` maps `'MyC::MyA'` → `'MyC'`.

### OI-4: `pss_top` vs. user-chosen top

PSS convention is that the root component is named `pss_top`. The execution test uses
`Top`. `IrToRuntimeBuilder.build()` returns a flat dict of all classes; the caller chooses
which is the top. No special handling needed — document this.

### OI-5: Exec block translation gated on PSS action kind

The PSS spec has many `exec` kinds (`body`, `pre_solve`, `post_solve`, `init_down`,
`init_up`, `run_start`, `run_end`, …). Only `body` and `init_down` are needed for the
first milestone. The others map naturally to `zdc.Action` methods (`pre_solve`,
`post_solve`) or component lifecycle hooks. This is future work.

---

## Implementation Plan

| Step | What | Where |
|------|------|-------|
| 1 | Add `parent_comp_names` dict to `AstToIrContext`; use `'MyC::MyA'` qualified keys in `type_map` for actions | `ast_to_ir.py` |
| 2 | Populate `parent_comp_names` in `_translate_component`; set action key as `'CompName::ActionName'` | `ast_to_ir.py` |
| 3 | In `_translate_exec_scope`, resolve single-name refs against current scope's fields → emit `ExprAttribute(ExprSelf(), name)` when inside an action (OI-2) | `ast_to_ir.py` |
| 4 | Add `ExecBlock(kind=Body)` handling in `_translate_action` (Gap 2) | `ast_to_ir.py` |
| 5 | Add `ExecBlock(kind=InitDown)` handling in `_translate_component` (Gap 3) | `ast_to_ir.py` |
| 6 | Create `IrToRuntimeBuilder` with `_build_component`, `_build_action`, `_field_to_zdc`; set action class as attribute on parent component class (OI-3) | new `ir_to_runtime.py` in `zuspec-fe-pss/python/zuspec/fe/pss/` |
| 7 | Create `ActionBodyExecutor(Executor)` subclass that resolves `ExprAttribute(ExprSelf(), …)` against the action instance (OI-1) | `ir_to_runtime.py` or extend `rt/executor.py` |
| 8 | Wire it all up in `test_action.py` (execution test) | `tests/python/execution/test_action.py` |

**Estimated scope:** Steps 1-5 are surgical additions to `ast_to_ir.py` (~80-100 lines
total). Steps 6-7 form a new ~200-250 line module. Step 8 completes the test.

---

## Verification Target

After all steps, the following test must pass end-to-end:

```python
# packages/zuspec-fe-pss/tests/python/execution/test_action.py
import asyncio
from zuspec.fe.pss import Parser, AstToIrTranslator
from zuspec.fe.pss.ir_to_runtime import IrToRuntimeBuilder

def test_action():
    pss_code = """
    component MyC {
      bit[32] val;
      action MyA {
        bit[32] val;
        exec body { val = 15; }
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

    parser = Parser()
    parser.parses([('test.pss', pss_code)])
    ast_root = parser.link()

    ir_ctx = AstToIrTranslator().translate(ast_root)

    classes = IrToRuntimeBuilder(ir_ctx).build()

    Top = classes['Top']
    MyA = classes['MyC'].MyA     # qualified via parent component class attribute
    # also accessible as: classes['MyC::MyA']
    top = Top()

    async def run():
        a = await MyA()(top)
        assert a.comp.val in [21, 22]
        assert a.val == 15

    asyncio.run(run())
```

This mirrors lines 35-40 of `packages/zuspec-dataclasses/tests/unit/test_action.py`
exactly, with PSS source as the input instead of hand-written Python decorators.
