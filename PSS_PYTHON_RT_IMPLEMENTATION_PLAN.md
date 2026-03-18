# PSS Pure-Python Execution Runtime — Implementation Plan

Reference design: `pss-python-execution-design.md`

---

## Current State Summary

The following is already in place and does **not** need to be written from scratch:

| Item | Location | State |
|---|---|---|
| All activity IR nodes | `ir/activity.py` | Complete (21 node types) |
| `Loc(file, line, pos)` on `Base` | `ir/base.py` | Exists; `loc` always `None` currently |
| `ActivityParser.parse()` | `activity_parser.py` | Complete; does **not** populate `loc` |
| All visitor methods | `ir/visitor.py` | Complete |
| `randomize(obj)` / `randomize_with(obj)` | `solver/api.py` | Complete |
| `Action.__call__` (partial) | `types.py` | Comp-bind only; no solver; no IR walk |
| `ListClaimPool` (lock/share/drop) | `rt/list_claim_pool.py` | Complete |
| `ListBufferPool` | `rt/list_buffer_pool.py` | Complete |
| `_find_comp_instances(comp, type)` | `types.py` | Complete |
| `lock()` / `share()` decorators | `decorators.py` | Complete |
| `bind` class / `extend()` | `decorators.py` | Complete |
| `pool()` decorator | `decorators.py` | **Stub — returns `None`** |

---

## Conventions

- All new runtime modules go in `src/zuspec/dataclasses/rt/`.
- New test files go in `tests/unit/`.
- Use `asyncio` throughout; no custom scheduler.
- Type hints required on all public functions/methods.
- Dataclasses use `@dc.dataclass(kw_only=True)` (existing convention).

---

## Phase 1 — Source Locations, Sequential Traversal, Solver Integration

**Goal:** Run a sequentially structured compound action (with atomic sub-actions),
call the solver on each action's rand fields, and have debugger line events fire at
the correct user source location.

---

### T1.1 — Populate `loc` in `ActivityParser`

**File:** `src/zuspec/dataclasses/activity_parser.py`

**Problem:** `ActivityParser.parse(method)` calls `textwrap.dedent(inspect.getsource(method))`
and parses the dedented string with `ast.parse()`.  AST node `.lineno` values are
relative to the start of the dedented string (line 1 = `async def activity`).  The
actual file line number is `startlineno + node.lineno - 1` where `startlineno` comes
from `inspect.getsourcelines(method)[1]`.

**Changes:**

1. At the top of `parse()`, before the existing `inspect.getsource()` call, add:

```python
import inspect

src_file: str = inspect.getsourcefile(method) or ""
_, start_lineno = inspect.getsourcelines(method)
self._src_file = src_file
self._start_lineno = start_lineno   # 1-based line of "async def activity"
```

2. Add a helper `_loc(ast_node)` that converts an AST node's lineno to a `Loc`:

```python
from .ir.base import Loc

def _loc(self, ast_node) -> Loc:
    return Loc(
        file=self._src_file,
        line=self._start_lineno + getattr(ast_node, 'lineno', 1) - 1,
        pos=getattr(ast_node, 'col_offset', 0),
    )
```

3. Pass `loc=self._loc(ast_node)` to every IR node constructor call in the parser.
   There are approximately 25 construction sites; grep for `ActivityTraversal(`,
   `ActivityAnonTraversal(`, `ActivityParallel(`, etc. and add the `loc=` kwarg.

4. The parse cache key is `hash(source)` which is source-content-based.  After this
   change, two identical function bodies in different files will produce the same cache
   entry — wrong `loc.file` on second hit.  Fix: change the cache key to include
   the file and start line:

```python
key = (hash(source), src_file, start_lineno)
```

**Tests:** `tests/unit/test_activity_parser.py` — add assertions that
`parsed_block.stmts[0].loc.file` ends with the test file name and
`parsed_block.stmts[0].loc.line > 0`.

---

### T1.2 — Add `action_type_cls` to `ActivityAnonTraversal`

**File:** `src/zuspec/dataclasses/ir/activity.py`

`ActivityAnonTraversal.action_type` is a string (e.g. `"WriteAction"`).  At
execution time we need the actual `type` object.  Rather than changing the existing
`str` field (it is useful for serialisation), add an optional companion field:

```python
@dc.dataclass(kw_only=True)
class ActivityAnonTraversal(ActivityStmt):
    action_type: str = dc.field()
    label: Optional[str] = None
    inline_constraints: List['Expr'] = dc.field(default_factory=list)
    action_type_cls: Optional[type] = dc.field(default=None)   # ← NEW
    ...
```

**File:** `src/zuspec/dataclasses/activity_parser.py`

In `_parse_do_call()`, `_parse_labeled_do()`, and `_parse_with_do()` (the three
places that construct `ActivityAnonTraversal`), resolve the type string against
`method.__globals__` and store it:

```python
# After computing action_type string:
action_type_cls = method.__globals__.get(action_type_str)
# action_type_cls may be None for qualified names (e.g. "pkg.MyAction");
# resolver falls back to string search at runtime if None.
```

Pass `method` (or `method.__globals__`) into `_parse_body()` so the lookup
namespace is available throughout parsing.

---

### T1.3 — `rt/debug_rt.py`

**New file:** `src/zuspec/dataclasses/rt/debug_rt.py`

```python
"""Debugger integration for the PSS activity runner.

When a sys.settrace-based debugger (pdb, debugpy/VS Code, PyCharm) is active,
_fire_line_event() creates a real CPython frame at the user's source location
so the debugger fires a line event there.  No-op when no debugger is attached.
"""
from __future__ import annotations

import ast
import sys
from typing import Any


def _fire_line_event(filename: str, lineno: int, local_vars: dict[str, Any]) -> None:
    """
    Fire a ``line`` trace event at *filename*:*lineno*.

    Creates a real CPython frame at the specified location by compiling and
    executing a bare ``pass`` AST node.  Any active ``sys.settrace`` debugger
    sees this as a genuine line event and will stop if a breakpoint is set there.

    Zero overhead when no debugger is attached (guarded by ``sys.gettrace()``).
    """
    if sys.gettrace() is None:
        return

    if not filename or lineno <= 0:
        return

    stmt = ast.Pass()
    stmt.lineno = lineno
    stmt.col_offset = 0
    mod = ast.Module(body=[stmt], type_ignores=[])
    ast.fix_missing_locations(mod)
    code = compile(mod, filename, "exec")
    exec(code, local_vars)  # noqa: S102
```

---

### T1.4 — `rt/action_context.py`

**New file:** `src/zuspec/dataclasses/rt/action_context.py`

```python
from __future__ import annotations

import dataclasses as dc
from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    from ..types import Component
    from .pool_resolver import PoolResolver


@dc.dataclass(kw_only=True)
class ActionContext:
    """Carries all per-traversal state through the ActivityRunner call tree."""

    action: Any
    """The action instance currently being executed."""

    comp: "Component"
    """The component instance bound to this action."""

    pool_resolver: "PoolResolver"
    """Resolves resource/flow-object fields to pool instances."""

    parent: Optional["ActionContext"] = None
    """The enclosing traversal context (for super() support)."""

    seed: int = 0
    """RNG seed for this traversal (derived from parent seed XOR action id)."""

    inline_constraints: list = dc.field(default_factory=list)
    """Extra IR constraint expressions from a with-block, applied during solve."""

    flow_bindings: dict = dc.field(default_factory=dict)
    """field_name → FlowObjInstance; injected by schedule-block elaboration."""

    head_resource_hints: dict = dc.field(default_factory=dict)
    """field_name → instance_id pre-assigned by BindingSolver for parallel heads."""
```

---

### T1.5 — `rt/pool_resolver.py` (Phase 1 subset)

**New file:** `src/zuspec/dataclasses/rt/pool_resolver.py`

Phase 1 implements component-instance selection only.  Pool binding (for
resource acquisition) is added in T2.2.

```python
from __future__ import annotations

import dataclasses as dc
import random
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..types import Component


@dc.dataclass
class PoolResolver:
    """
    Built once per component-tree root.  Answers two runtime questions:

    1. Which component instances are candidates for a given action type?
    2. Which pool backs a given resource/flow-object field on an action?
       (Phase 2)
    """

    _comp_instances: dict[type, list["Component"]] = dc.field(
        default_factory=dict, init=False
    )

    @classmethod
    def build(cls, root: "Component") -> "PoolResolver":
        """Walk the component tree and index all component instances by type."""
        pr = cls()
        pr._walk(root)
        return pr

    # ------------------------------------------------------------------
    # Component instance selection
    # ------------------------------------------------------------------

    def select_comp(self, action_type: type, context_comp: "Component") -> "Component":
        """
        Randomly select a component instance of the type required by *action_type*.

        Looks up the ``Action[T]`` type parameter to find *T*, then returns a
        random instance of *T* found within *context_comp*'s subtree.
        """
        import typing
        from ..types import Action

        comp_type = _action_comp_type(action_type)
        if comp_type is None:
            raise RuntimeError(
                f"Cannot determine component type for {action_type.__name__}"
            )

        candidates = self._instances_in(context_comp, comp_type)
        if not candidates:
            raise RuntimeError(
                f"No instances of {comp_type.__name__} found within "
                f"{type(context_comp).__name__}"
            )
        return random.choice(candidates)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _walk(self, comp: "Component") -> None:
        import dataclasses
        t = type(comp)
        self._comp_instances.setdefault(t, []).append(comp)
        try:
            fields = dataclasses.fields(comp)
        except TypeError:
            return
        for f in fields:
            val = getattr(comp, f.name, None)
            if val is not None and _is_component(val):
                self._walk(val)

    def _instances_in(
        self, root: "Component", comp_type: type
    ) -> list["Component"]:
        """Return all instances of *comp_type* in *root*'s subtree (depth-first)."""
        import dataclasses
        result = []
        if isinstance(root, comp_type):
            result.append(root)
        try:
            for f in dataclasses.fields(root):
                val = getattr(root, f.name, None)
                if val is not None and _is_component(val):
                    result.extend(self._instances_in(val, comp_type))
        except TypeError:
            pass
        return result


def _action_comp_type(action_type: type) -> type | None:
    """Extract the ``T`` from ``Action[T]`` for a concrete action subclass."""
    import typing
    from ..types import Action
    for base in getattr(action_type, "__orig_bases__", ()):
        origin = typing.get_origin(base)
        if origin is not None and (origin is Action or issubclass(origin, Action)):
            args = typing.get_args(base)
            if args:
                return args[0]
    return None


def _is_component(obj: Any) -> bool:
    from ..types import Component
    return isinstance(obj, Component)
```

---

### T1.6 — `rt/activity_runner.py` (Phase 1 subset)

**New file:** `src/zuspec/dataclasses/rt/activity_runner.py`

Phase 1 implements: sequential block, handle traversal, anonymous traversal,
super traversal, and solver integration.  The parallel/control-flow cases raise
`NotImplementedError` as stubs for later phases.

```python
from __future__ import annotations

import asyncio
import dataclasses as dc
from typing import TYPE_CHECKING, Any, Optional

from ..ir.activity import (
    ActivityAnonTraversal,
    ActivitySequenceBlock,
    ActivityStmt,
    ActivitySuper,
    ActivityTraversal,
    # stubs — handled in later phases:
    ActivityParallel, ActivitySchedule, ActivityAtomic,
    ActivityRepeat, ActivityDoWhile, ActivityWhileDo,
    ActivityForeach, ActivityReplicate,
    ActivitySelect, ActivityIfElse, ActivityMatch,
    ActivityConstraint, ActivityBind,
)
from ..solver.api import randomize, randomize_with
from .action_context import ActionContext
from .debug_rt import _fire_line_event

if TYPE_CHECKING:
    from ..types import Component
    from .pool_resolver import PoolResolver


class ActivityRunner:
    """Interprets activity IR trees produced by ActivityParser."""

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    async def run(
        self,
        block: ActivitySequenceBlock,
        ctx: ActionContext,
    ) -> None:
        """Execute *block* in the given context."""
        await self._seq(block, ctx)

    # ------------------------------------------------------------------
    # Dispatcher
    # ------------------------------------------------------------------

    async def _exec(self, stmt: ActivityStmt, ctx: ActionContext) -> None:
        # Fire debugger line event at user source location
        if stmt.loc:
            _fire_line_event(
                stmt.loc.file or "",
                stmt.loc.line,
                vars(ctx.action),
            )

        match type(stmt):
            case t if t is ActivitySequenceBlock:
                await self._seq(stmt, ctx)
            case t if t is ActivityTraversal:
                await self._traverse_handle(stmt, ctx)
            case t if t is ActivityAnonTraversal:
                await self._traverse_anon(stmt, ctx)
            case t if t is ActivitySuper:
                await self._super(stmt, ctx)
            # Phase 2
            case t if t is ActivityParallel:
                await self._parallel(stmt, ctx)
            case t if t is ActivitySchedule:
                await self._schedule(stmt, ctx)
            case t if t is ActivityAtomic:
                await self._atomic(stmt, ctx)
            # Phase 3
            case t if t is ActivityRepeat:
                await self._repeat(stmt, ctx)
            case t if t is ActivityDoWhile:
                await self._do_while(stmt, ctx)
            case t if t is ActivityWhileDo:
                await self._while_do(stmt, ctx)
            case t if t is ActivityForeach:
                await self._foreach(stmt, ctx)
            case t if t is ActivityReplicate:
                await self._replicate(stmt, ctx)
            case t if t is ActivitySelect:
                await self._select(stmt, ctx)
            case t if t is ActivityIfElse:
                await self._if_else(stmt, ctx)
            case t if t is ActivityMatch:
                await self._match(stmt, ctx)
            # Phase 5
            case t if t is ActivityConstraint:
                pass   # scheduling constraint — no runtime action in Phase 1–4
            case t if t is ActivityBind:
                await self._bind(stmt, ctx)
            case _:
                raise RuntimeError(f"Unhandled activity node: {type(stmt).__name__}")

    # ------------------------------------------------------------------
    # Sequential block
    # ------------------------------------------------------------------

    async def _seq(self, node: ActivitySequenceBlock, ctx: ActionContext) -> None:
        for stmt in node.stmts:
            await self._exec(stmt, ctx)

    # ------------------------------------------------------------------
    # Action traversal — core lifecycle
    # ------------------------------------------------------------------

    async def _traverse(
        self,
        action_type: type,
        inline_constraints: list,
        ctx: ActionContext,
        label: Optional[str] = None,
        head_resource_hints: Optional[dict] = None,
    ) -> Any:
        """
        Full PSS action traversal lifecycle:
          1. Instantiate
          2. Assign comp
          3. pre_solve()
          4. randomize() — with any inline constraints
          5. post_solve()
          6. Acquire resources (Phase 2)
          7. body() or recurse into sub-activity
          8. Release resources (Phase 2)
        """
        # 1. Instantiate
        action = object.__new__(action_type)
        # Initialise dataclass fields to defaults
        for f in dc.fields(action_type):
            if f.default is not dc.MISSING:
                object.__setattr__(action, f.name, f.default)
            elif f.default_factory is not dc.MISSING:
                object.__setattr__(action, f.name, f.default_factory())
            else:
                object.__setattr__(action, f.name, None)

        # 2. Assign comp
        action.comp = ctx.pool_resolver.select_comp(action_type, ctx.comp)

        # 3. pre_solve
        action.pre_solve()

        # 4. Randomize
        child_seed = ctx.seed ^ id(action_type)
        if inline_constraints:
            # inline_constraints is a list of IR Expr nodes; pass via context
            # For Phase 1, fall back to plain randomize and apply constraints
            # via randomize_with in Phase 3 when ExprEval is available.
            randomize(action, seed=child_seed)
        else:
            randomize(action, seed=child_seed)

        # 5. post_solve
        action.post_solve()

        # Build child context
        child_ctx = ActionContext(
            action=action,
            comp=action.comp,
            pool_resolver=ctx.pool_resolver,
            parent=ctx,
            seed=child_seed,
            inline_constraints=[],
            flow_bindings={},
            head_resource_hints=head_resource_hints or {},
        )

        # 6/8. Resource acquire/release — implemented in Phase 2
        # For Phase 1 call body/activity directly
        await self._exec_action_body(action_type, action, child_ctx)
        return action

    async def _exec_action_body(
        self,
        action_type: type,
        action: Any,
        ctx: ActionContext,
    ) -> None:
        """Execute body() for atomic actions, or walk __activity__ for compound."""
        activity_ir = getattr(action_type, "__activity__", None)
        if activity_ir is not None:
            await ActivityRunner().run(activity_ir, ctx)
        else:
            await action.body()

    # ------------------------------------------------------------------
    # Handle traversal:  self.handle() / self.handle[i]()
    # ------------------------------------------------------------------

    async def _traverse_handle(
        self, node: ActivityTraversal, ctx: ActionContext
    ) -> None:
        handle = getattr(ctx.action, node.handle, None)
        if handle is None:
            raise RuntimeError(
                f"Action {type(ctx.action).__name__} has no handle '{node.handle}'"
            )
        action_type = type(handle)
        await self._traverse(
            action_type,
            node.inline_constraints,
            ctx,
        )

    # ------------------------------------------------------------------
    # Anonymous traversal:  do(Type) / with do(Type) as x:
    # ------------------------------------------------------------------

    async def _traverse_anon(
        self, node: ActivityAnonTraversal, ctx: ActionContext
    ) -> None:
        action_type = _resolve_action_type(node, ctx)
        action = await self._traverse(
            action_type,
            node.inline_constraints,
            ctx,
            label=node.label,
        )
        # Write back to label handle if present
        if node.label and hasattr(ctx.action, node.label):
            setattr(ctx.action, node.label, action)

    # ------------------------------------------------------------------
    # Super traversal:  super().activity()
    # ------------------------------------------------------------------

    async def _super(self, node: ActivitySuper, ctx: ActionContext) -> None:
        parent_activity = _find_super_activity(type(ctx.action))
        if parent_activity is None:
            return   # no parent activity — silently skip
        await ActivityRunner().run(parent_activity, ctx)

    # ------------------------------------------------------------------
    # Phase 2–5 stubs
    # ------------------------------------------------------------------

    async def _parallel(self, node, ctx): raise NotImplementedError("Phase 2")
    async def _schedule(self, node, ctx): raise NotImplementedError("Phase 2")
    async def _atomic(self, node, ctx):   raise NotImplementedError("Phase 2")
    async def _repeat(self, node, ctx):   raise NotImplementedError("Phase 3")
    async def _do_while(self, node, ctx): raise NotImplementedError("Phase 3")
    async def _while_do(self, node, ctx): raise NotImplementedError("Phase 3")
    async def _foreach(self, node, ctx):  raise NotImplementedError("Phase 3")
    async def _replicate(self, node, ctx):raise NotImplementedError("Phase 3")
    async def _select(self, node, ctx):   raise NotImplementedError("Phase 3")
    async def _if_else(self, node, ctx):  raise NotImplementedError("Phase 3")
    async def _match(self, node, ctx):    raise NotImplementedError("Phase 3")
    async def _bind(self, node, ctx):     pass   # Phase 5


# ------------------------------------------------------------------
# Module-level helpers
# ------------------------------------------------------------------

def _resolve_action_type(node: ActivityAnonTraversal, ctx: ActionContext) -> type:
    """Return the Python class for an ActivityAnonTraversal node."""
    # Prefer pre-resolved class reference from parser
    if node.action_type_cls is not None:
        return node.action_type_cls
    # Fall back: search by name in the action's module
    import sys
    module = sys.modules.get(type(ctx.action).__module__)
    if module:
        cls = getattr(module, node.action_type, None)
        if cls is not None:
            return cls
    raise RuntimeError(
        f"Cannot resolve action type '{node.action_type}' "
        f"in module '{type(ctx.action).__module__}'"
    )


def _find_super_activity(action_type: type):
    """Find the __activity__ IR from the first base class that defines it."""
    for base in action_type.__mro__[1:]:
        if "__activity__" in base.__dict__:
            return base.__dict__["__activity__"]
    return None
```

---

### T1.7 — `rt/scenario_runner.py`

**New file:** `src/zuspec/dataclasses/rt/scenario_runner.py`

```python
from __future__ import annotations

import asyncio
import random
from typing import TYPE_CHECKING, Optional, Type

from .action_context import ActionContext
from .activity_runner import ActivityRunner
from .pool_resolver import PoolResolver

if TYPE_CHECKING:
    from ..types import Component


class ScenarioRunner:
    """
    Stateful entry point for running PSS scenarios on a component tree.

    Usage::

        top = ObjFactory.inst().mkComponent(Top)
        runner = ScenarioRunner(top, seed=42)
        await runner.run(EntryAction)
    """

    def __init__(
        self,
        comp: "Component",
        seed: Optional[int] = None,
    ) -> None:
        self._comp = comp
        self._resolver = PoolResolver.build(comp)
        self._seed = seed if seed is not None else random.randrange(2**32)

    async def run(self, action_type: Type, **kwargs) -> None:
        """Traverse *action_type* once against the component tree."""
        ctx = ActionContext(
            action=None,        # root context has no owning action
            comp=self._comp,
            pool_resolver=self._resolver,
            seed=self._seed,
        )
        runner = ActivityRunner()
        action = await runner._traverse(action_type, [], ctx)
        # Advance seed for next call
        self._seed = (self._seed * 6364136223846793005 + 1442695040888963407) & 0xFFFFFFFF_FFFFFFFF
        return action

    async def run_n(self, action_type: Type, n: int) -> None:
        """Traverse *action_type* *n* times sequentially."""
        for _ in range(n):
            await self.run(action_type)


async def run_action(
    comp: "Component",
    action_type: Type,
    seed: Optional[int] = None,
) -> None:
    """
    Single-shot convenience function: traverse *action_type* on *comp*.

    Equivalent to ``await ScenarioRunner(comp, seed).run(action_type)``.
    """
    runner = ScenarioRunner(comp, seed=seed)
    await runner.run(action_type)


def run_action_sync(
    comp: "Component",
    action_type: Type,
    seed: Optional[int] = None,
) -> None:
    """Synchronous wrapper around :func:`run_action` for non-async callers."""
    asyncio.run(run_action(comp, action_type, seed=seed))
```

---

### T1.8 — Update `types.py` `Action.__call__`

**File:** `src/zuspec/dataclasses/types.py`

Replace the body of `Action.__call__` with a delegation to `ActivityRunner._traverse`:

```python
async def __call__(self, comp: 'Component') -> Self:
    from .rt.activity_runner import ActivityRunner
    from .rt.action_context import ActionContext
    from .rt.pool_resolver import PoolResolver
    import random

    resolver = PoolResolver.build(comp)
    ctx = ActionContext(
        action=None,
        comp=comp,
        pool_resolver=resolver,
        seed=random.randrange(2**32),
    )
    await ActivityRunner()._traverse(type(self), [], ctx)
    return self
```

> **Note:** `Action.__call__` is the legacy entry point used by existing tests.
> `ScenarioRunner` is the preferred new entry point.  Keeping `__call__` working
> ensures all existing tests continue to pass.

---

### T1.9 — Update `__init__.py`

**File:** `src/zuspec/dataclasses/__init__.py`

Add to `__all__` and add import lines:

```python
from .rt.scenario_runner import ScenarioRunner, run_action, run_action_sync

# In __all__:
'ScenarioRunner', 'run_action', 'run_action_sync',
```

---

### T1.10 — Phase 1 Tests

Phase 1 tests span eight files.  See **§ Testing Plan** for complete per-function
case lists.

| File | Cases |
|---|---|
| `test_rt_debug.py` | _fire_line_event — no-op, trace callbacks, loc population |
| `test_rt_action_context.py` | Construction, parent chain, defaults |
| `test_rt_pool_resolver.py` (Phase 1 section) | build(), select_comp(), error paths |
| `test_rt_runner_sequential.py` | Lifecycle, ordering, solver call |
| `test_rt_runner_traversal.py` | Handle/anon/super traversal variants |
| `test_rt_scenario_runner.py` | ScenarioRunner, run_action, run_action_sync, seed |
| `test_rt_regression_action_call.py` | Action.__call__ backwards compatibility |
| `test_activity_parser_loc.py` | loc.file and loc.line populated on IR nodes |

---

## Phase 2 — Parallel Blocks and Resource Management

**Goal:** Execute `parallel()` and `schedule()` blocks, acquire and release
resource claims via `ListClaimPool`, and guarantee distinct resource
assignments for head actions using `BindingSolver`.

---

### T2.1 — Implement `pool()` decorator

**File:** `src/zuspec/dataclasses/decorators.py`

The current `pool()` returns `None`.  It should produce a `dc.field` descriptor
that carries metadata marking the field as a pool declaration:

```python
def pool(size: Optional[int] = None, default_factory: Optional[Any] = None) -> Any:
    """Declare a resource/flow-object pool on a Component field.

    Example::

        channels: ClaimPool[DmaChannel] = zdc.pool(size=2)
    """
    meta: dict = {"kind": "pool"}
    if size is not None:
        meta["size"] = size
    if default_factory is not None:
        return dc.field(default_factory=default_factory, metadata=meta)
    return dc.field(default=None, metadata=meta)
```

Users create pool instances explicitly:

```python
channels: ClaimPool[DmaChannel] = zdc.pool(
    default_factory=lambda: ClaimPool.fromList([DmaChannel(), DmaChannel()])
)
```

---

### T2.2 — `rt/pool_resolver.py` — bind directive support

**File:** `src/zuspec/dataclasses/rt/pool_resolver.py`

Extend `PoolResolver.build()` to:

1. After `_walk()`, call `_index_pools(root)` to collect all `ClaimPool` and
   `BufferPool` instances in the component tree, indexed by `(comp_instance_id, field_name)`.

2. Call `_index_binds(root)` to walk components looking for `__bind__` methods
   (existing convention from `test_bind_map.py`).  A `__bind__` method returns
   a dict mapping pool instances to action field descriptions or `'*'` (wildcard).

3. Add `resolve_pool(action, field_name) -> ClaimPool | BufferPool | None`:
   - First try explicit bind: look up `(action.comp, action_type, field_name)`.
   - Fall back to wildcard bind: look up `(action.comp, field_type)`.
   - Fall back to type-based scan: find any pool of the matching element type
     in `action.comp`.

```python
def resolve_pool(self, action: Any, field_name: str):
    """Return the pool bound to action.<field_name> given action.comp."""
    ...

def _index_pools(self, comp: "Component") -> None:
    """Collect all ClaimPool/BufferPool instances in the tree."""
    ...

def _index_binds(self, comp: "Component") -> None:
    """Process __bind__ methods to build explicit and wildcard bind maps."""
    ...
```

---

### T2.3 — Resource field introspection helpers

**New file:** `src/zuspec/dataclasses/rt/resource_rt.py`

```python
"""Helpers for runtime resource field introspection and acquisition."""
from __future__ import annotations

import dataclasses as dc
from typing import Any, NamedTuple


class ResourceFieldInfo(NamedTuple):
    name: str          # field name on the action
    claim: str         # "lock" or "share"
    field_type: type   # the Resource subclass


def get_resource_fields(action_type: type) -> list[ResourceFieldInfo]:
    """Return all lock/share fields declared on *action_type*."""
    result = []
    for f in dc.fields(action_type):
        meta = f.metadata
        if meta.get("kind") == "resource_ref":
            claim = meta.get("claim", "lock")
            # Resolve type annotation
            import typing, sys
            hints = typing.get_type_hints(action_type)
            field_type = hints.get(f.name, type(None))
            result.append(ResourceFieldInfo(f.name, claim, field_type))
    return result


async def acquire_resources(
    action: Any,
    ctx: "ActionContext",        # forward ref
) -> list[tuple]:
    """
    Acquire all resource claims on *action* in canonical order.

    Canonical order: sort by (id(pool), assigned_instance_id) to prevent
    circular wait (deadlock-freedom by lock ordering).

    Returns a list of (pool, claim) pairs for later release.
    """
    from .pool_resolver import PoolResolver
    resource_fields = get_resource_fields(type(action))
    if not resource_fields:
        return []

    # Build (pool, field_info, instance_id_hint) triples
    entries = []
    for fi in resource_fields:
        pool = ctx.pool_resolver.resolve_pool(action, fi.name)
        if pool is None:
            continue
        resource_obj = getattr(action, fi.name, None)
        instance_id = getattr(resource_obj, "instance_id", None)
        entries.append((pool, fi, instance_id))

    # Sort by (pool identity, instance_id) for deadlock-free ordering
    entries.sort(key=lambda e: (id(e[0]), e[2] if e[2] is not None else -1))

    claims = []
    for pool, fi, instance_id in entries:
        filter_fn = (
            (lambda r, i, iid=instance_id: i == iid)
            if instance_id is not None
            else None
        )
        if fi.claim == "lock":
            claim = await pool.lock(filter=filter_fn)
        else:
            claim = await pool.share(filter=filter_fn)
        # Write solved resource object back onto action field
        setattr(action, fi.name, claim.t)
        claims.append((pool, claim))

    return claims


def release_resources(claims: list[tuple]) -> None:
    """Release all resource claims in reverse acquisition order."""
    for pool, claim in reversed(claims):
        pool.drop(claim)
```

---

### T2.4 — `rt/binding_solver.py`

**New file:** `src/zuspec/dataclasses/rt/binding_solver.py`

```python
"""Head-action AllDifferent solver for parallel blocks.

Before spawning parallel branches, assigns distinct resource instance_id
values to each branch's first action's lock fields, guaranteeing no two
branches start with the same resource held.
"""
from __future__ import annotations

import dataclasses as dc
import random
from typing import Any

from .resource_rt import get_resource_fields


@dc.dataclass
class HeadAssignment:
    """Per-branch result from BindingSolver."""
    branch_index: int
    resource_hints: dict[str, int]   # field_name → instance_id


class BindingSolver:
    """
    Solves resource assignments for parallel head actions.

    Uses the existing solver's uniqueness propagator via
    ``randomize_with()`` if resource fields overlap, otherwise
    performs direct bipartite matching for the common 2–4 branch case.
    """

    def solve_heads(
        self,
        head_action_types: list[type],
        ctx: "ActionContext",
    ) -> list[HeadAssignment]:
        """
        Return one HeadAssignment per branch with distinct instance_id
        values across all lock fields that share the same pool.

        For each pool P, gathers all lock claims from all branches that
        draw from P and assigns distinct instance_ids by random permutation
        of feasible values.
        """
        # Group (branch_index, field_name, pool, domain) by pool
        from .resource_rt import get_resource_fields

        pool_groups: dict[int, list[tuple]] = {}   # id(pool) → entries
        for bi, action_type in enumerate(head_action_types):
            for fi in get_resource_fields(action_type):
                if fi.claim != "lock":
                    continue
                # Create a temporary instance to resolve pool
                pool = ctx.pool_resolver.resolve_pool_by_type(
                    action_type, fi.name, ctx.comp
                )
                if pool is None:
                    continue
                domain = list(range(len(pool.resources)))
                pool_groups.setdefault(id(pool), []).append(
                    (bi, fi.name, pool, domain)
                )

        # Assign distinct instance_ids per pool group
        assignments: dict[int, dict[str, int]] = {i: {} for i in range(len(head_action_types))}
        rng = random.Random(ctx.seed)

        for pool_id, entries in pool_groups.items():
            # Feasible domain for this pool
            _, _, pool, domain = entries[0]
            n_claims = len(entries)
            if n_claims > len(domain):
                raise RuntimeError(
                    f"Pool has {len(domain)} instances but {n_claims} "
                    f"concurrent lock claims — binding is infeasible"
                )
            chosen = rng.sample(domain, k=n_claims)
            for (bi, field_name, _, _), instance_id in zip(entries, chosen):
                assignments[bi][field_name] = instance_id

        return [
            HeadAssignment(branch_index=i, resource_hints=assignments[i])
            for i in range(len(head_action_types))
        ]
```

> **Note on solver integration:** This initial implementation uses random
> sampling from the feasible set.  If resource fields carry algebraic
> constraints (e.g., `pad.role == CLOCK`), the solver must evaluate feasibility
> per-instance and filter the domain first.  Add `_compute_domain(action_type,
> field_name, pool, ctx)` to apply constraint filtering in a follow-up task.

---

### T2.5 — `ActivityRunner` — parallel, schedule, atomic, resource acquisition

**File:** `src/zuspec/dataclasses/rt/activity_runner.py`

Replace the Phase 2 stubs with implementations.

#### `_acquire_resources` / `_release_resources`

Call `acquire_resources()` / `release_resources()` from `resource_rt.py` within
`_traverse()`:

```python
# In _traverse(), replace Phase 1 direct call with:
claims = await acquire_resources(action, child_ctx)
try:
    await self._exec_action_body(action_type, action, child_ctx)
finally:
    release_resources(claims)
```

#### `_parallel()`

```python
async def _parallel(self, node: ActivityParallel, ctx: ActionContext) -> None:
    from .binding_solver import BindingSolver
    from .resource_rt import get_resource_fields

    # Identify head action type for each branch
    head_types = [_first_action_type(stmt, ctx) for stmt in node.stmts]

    # Solve head assignments (AllDifferent on lock fields)
    solver = BindingSolver()
    head_assigns = solver.solve_heads(
        [t for t in head_types if t is not None], ctx
    )

    # Build per-branch coroutines
    coros = []
    for i, stmt in enumerate(node.stmts):
        hints = head_assigns[i].resource_hints if i < len(head_assigns) else {}
        branch_ctx = ActionContext(
            action=ctx.action,
            comp=ctx.comp,
            pool_resolver=ctx.pool_resolver,
            parent=ctx,
            seed=ctx.seed ^ i,
            head_resource_hints=hints,
        )
        coros.append(self._exec(stmt, branch_ctx))

    await _gather_with_join(coros, node.join_spec)
```

#### `_schedule()`

For Phase 2, treat schedule as parallel (runtime arbitration).  Full dependency
analysis is Phase 4:

```python
async def _schedule(self, node: ActivitySchedule, ctx: ActionContext) -> None:
    # Phase 2: schedule = parallel without head-action pre-solve
    # (dependency ordering added in Phase 4)
    coros = [
        self._exec(stmt, ActionContext(
            action=ctx.action, comp=ctx.comp,
            pool_resolver=ctx.pool_resolver, parent=ctx,
            seed=ctx.seed ^ i,
        ))
        for i, stmt in enumerate(node.stmts)
    ]
    await _gather_with_join(coros, node.join_spec)
```

#### `_atomic()`

```python
async def _atomic(self, node: ActivityAtomic, ctx: ActionContext) -> None:
    # asyncio is cooperative; holding the lock without yielding is atomic.
    # Lock prevents other tasks from interleaving if they also respect it.
    async with _get_atomic_lock(ctx):
        for stmt in node.stmts:
            await self._exec(stmt, ctx)
```

#### `_gather_with_join()` and `_get_atomic_lock()`

Module-level helpers:

```python
async def _gather_with_join(coros: list, join_spec) -> None:
    from ..ir.activity import JoinSpec
    import asyncio, random

    if join_spec is None or join_spec.kind == "all":
        await asyncio.gather(*coros)

    elif join_spec.kind == "none":
        for c in coros:
            asyncio.create_task(c)

    elif join_spec.kind == "first":
        n = int(join_spec.count) if join_spec.count else 1
        tasks = [asyncio.create_task(c) for c in coros]
        done_count = 0
        pending = set(tasks)
        while done_count < n and pending:
            done, pending = await asyncio.wait(
                pending, return_when=asyncio.FIRST_COMPLETED
            )
            done_count += len(done)

    elif join_spec.kind == "branch":
        label = join_spec.branch_label
        labeled, unlabeled = [], []
        for c in coros:
            # coros tagged with label — pass label through ActionContext
            labeled.append(c)   # simplified; full label split in Phase 4
        for c in unlabeled:
            asyncio.create_task(c)
        await asyncio.gather(*labeled)

    elif join_spec.kind == "select":
        n = int(join_spec.count) if join_spec.count else 1
        tasks = [asyncio.create_task(c) for c in coros]
        chosen = random.sample(tasks, k=min(n, len(tasks)))
        for t in tasks:
            if t not in chosen:
                asyncio.create_task(t._coro)  # let run freely
        await asyncio.gather(*chosen)


_atomic_locks: dict[int, asyncio.Lock] = {}

def _get_atomic_lock(ctx: ActionContext) -> asyncio.Lock:
    key = id(ctx.pool_resolver)  # one lock per component tree
    if key not in _atomic_locks:
        _atomic_locks[key] = asyncio.Lock()
    return _atomic_locks[key]
```

#### `_first_action_type()` helper

```python
def _first_action_type(stmt: ActivityStmt, ctx: ActionContext) -> type | None:
    """Return the action type of the first traversal in a statement subtree."""
    from ..ir.activity import (
        ActivityTraversal, ActivityAnonTraversal, ActivitySequenceBlock
    )
    if isinstance(stmt, ActivityTraversal):
        handle = getattr(ctx.action, stmt.handle, None)
        return type(handle) if handle is not None else None
    if isinstance(stmt, ActivityAnonTraversal):
        return stmt.action_type_cls or None
    if isinstance(stmt, ActivitySequenceBlock) and stmt.stmts:
        return _first_action_type(stmt.stmts[0], ctx)
    return None
```

---

### T2.6 — Phase 2 Tests

Phase 2 tests span four files.  See **§ Testing Plan** for complete per-function
case lists.

| File | Cases |
|---|---|
| `test_rt_pool_resolver.py` (Phase 2 section) | Bind directives, __bind__, wildcard, type-scan |
| `test_rt_resource.py` | get_resource_fields(), acquire/release ordering, shared claim |
| `test_rt_binding_solver.py` | solve_heads(), AllDifferent, infeasibility |
| `test_rt_runner_parallel.py` | parallel/schedule/atomic, join variants, resource contention |
| `test_rt_decorators.py` (pool section) | pool() decorator metadata |

---

## Phase 3 — Control Flow

**Goal:** Implement all loop and conditional activity constructs.

---

### T3.1 — `rt/expr_eval.py` — Evaluate IR `Expr` nodes

**New file:** `src/zuspec/dataclasses/rt/expr_eval.py`

The activity IR stores conditions (for `ActivityIfElse`, `ActivityDoWhile`,
etc.) as `Expr` IR nodes.  `ExprEval` interprets them against an action's
fields.

```python
class ExprEval:
    def __init__(self, ctx: ActionContext) -> None:
        self._ctx = ctx

    def eval(self, expr: "Expr") -> Any:
        """Evaluate *expr* in the context of ctx.action's fields."""
        from ..ir.expr import (
            ExprConstant, ExprFieldRef, ExprBin, ExprUnary, ExprCond,
        )
        match type(expr):
            case t if t is ExprConstant:
                return expr.value
            case t if t is ExprFieldRef:
                return self._eval_field_ref(expr)
            case t if t is ExprBin:
                return self._eval_bin(expr)
            case t if t is ExprUnary:
                return self._eval_unary(expr)
            case t if t is ExprCond:
                cond = self.eval(expr.cond)
                return self.eval(expr.true_val) if cond else self.eval(expr.false_val)
            case _:
                raise RuntimeError(f"Unhandled Expr type: {type(expr).__name__}")

    def _eval_field_ref(self, expr) -> Any:
        obj = self._ctx.action
        for part in expr.path:
            obj = getattr(obj, part)
        return obj

    def _eval_bin(self, expr) -> Any:
        from ..ir.expr import BinOp
        lhs = self.eval(expr.lhs)
        rhs = self.eval(expr.rhs)
        match expr.op:
            case BinOp.ADD:  return lhs + rhs
            case BinOp.SUB:  return lhs - rhs
            case BinOp.MUL:  return lhs * rhs
            case BinOp.DIV:  return lhs // rhs
            case BinOp.MOD:  return lhs % rhs
            case BinOp.EQ:   return lhs == rhs
            case BinOp.NE:   return lhs != rhs
            case BinOp.LT:   return lhs < rhs
            case BinOp.LE:   return lhs <= rhs
            case BinOp.GT:   return lhs > rhs
            case BinOp.GE:   return lhs >= rhs
            case BinOp.AND:  return lhs & rhs
            case BinOp.OR:   return lhs | rhs
            case BinOp.XOR:  return lhs ^ rhs
            case BinOp.LAND: return bool(lhs) and bool(rhs)
            case BinOp.LOR:  return bool(lhs) or bool(rhs)
            case BinOp.SHL:  return lhs << rhs
            case BinOp.SHR:  return lhs >> rhs
            case _:
                raise RuntimeError(f"Unknown BinOp: {expr.op}")

    def _eval_unary(self, expr) -> Any:
        from ..ir.expr import UnaryOp
        val = self.eval(expr.operand)
        match expr.op:
            case UnaryOp.NEG:  return -val
            case UnaryOp.NOT:  return ~val
            case UnaryOp.LNOT: return not val
            case _:
                raise RuntimeError(f"Unknown UnaryOp: {expr.op}")
```

> **Note:** Inspect `ir/expr.py` to confirm the exact `BinOp`/`UnaryOp` enum
> member names before implementation.  Adjust accordingly.

---

### T3.2 — Control-flow implementations in `ActivityRunner`

Replace Phase 3 stubs in `rt/activity_runner.py`.

#### `_repeat()`

```python
async def _repeat(self, node: ActivityRepeat, ctx: ActionContext) -> None:
    from .expr_eval import ExprEval
    count = ExprEval(ctx).eval(node.count)
    for i in range(int(count)):
        iter_ctx = ActionContext(
            action=ctx.action, comp=ctx.comp,
            pool_resolver=ctx.pool_resolver, parent=ctx,
            seed=ctx.seed ^ i,
        )
        if node.index_var:
            setattr(ctx.action, node.index_var, i)
        for stmt in node.body:
            await self._exec(stmt, iter_ctx)
```

#### `_do_while()`

```python
async def _do_while(self, node: ActivityDoWhile, ctx: ActionContext) -> None:
    from .expr_eval import ExprEval
    i = 0
    while True:
        for stmt in node.body:
            await self._exec(stmt, ctx)
        if not ExprEval(ctx).eval(node.condition):
            break
        i += 1
```

#### `_while_do()`

```python
async def _while_do(self, node: ActivityWhileDo, ctx: ActionContext) -> None:
    from .expr_eval import ExprEval
    while ExprEval(ctx).eval(node.condition):
        for stmt in node.body:
            await self._exec(stmt, ctx)
```

#### `_foreach()`

```python
async def _foreach(self, node: ActivityForeach, ctx: ActionContext) -> None:
    from .expr_eval import ExprEval
    collection = ExprEval(ctx).eval(node.collection)
    for i, item in enumerate(collection):
        if node.index_var:
            setattr(ctx.action, node.index_var, i)
        setattr(ctx.action, node.iterator, item)
        for stmt in node.body:
            await self._exec(stmt, ctx)
```

#### `_replicate()`

```python
async def _replicate(self, node: ActivityReplicate, ctx: ActionContext) -> None:
    from .expr_eval import ExprEval
    count = int(ExprEval(ctx).eval(node.count))
    # Replicate expands in-place within the enclosing scope's semantics.
    # For a sequential enclosing context: execute body count times.
    for i in range(count):
        if node.index_var:
            setattr(ctx.action, node.index_var, i)
        for stmt in node.body:
            await self._exec(stmt, ctx)
```

#### `_select()`

```python
async def _select(self, node: ActivitySelect, ctx: ActionContext) -> None:
    import random
    from .expr_eval import ExprEval
    ev = ExprEval(ctx)
    eligible = [
        b for b in node.branches
        if b.guard is None or ev.eval(b.guard)
    ]
    if not eligible:
        raise RuntimeError("select: no eligible branch (all guards false)")
    weights = [
        int(ev.eval(b.weight)) if b.weight is not None else 1
        for b in eligible
    ]
    chosen = random.choices(eligible, weights=weights, k=1)[0]
    for stmt in chosen.body:
        await self._exec(stmt, ctx)
```

#### `_if_else()`

```python
async def _if_else(self, node: ActivityIfElse, ctx: ActionContext) -> None:
    from .expr_eval import ExprEval
    cond = ExprEval(ctx).eval(node.condition)
    body = node.if_body if cond else node.else_body
    for stmt in body:
        await self._exec(stmt, ctx)
```

#### `_match()`

```python
async def _match(self, node: ActivityMatch, ctx: ActionContext) -> None:
    from .expr_eval import ExprEval
    ev = ExprEval(ctx)
    subject = ev.eval(node.subject)
    for case in node.cases:
        pattern = ev.eval(case.pattern)
        if subject == pattern:
            for stmt in case.body:
                await self._exec(stmt, ctx)
            return
    # No match: silently skip (PSS allows unmatched cases)
```

---

### T3.3 — Phase 3 Tests

Phase 3 tests are in one file.  See **§ Testing Plan** for complete per-function
case lists.

| File | Cases |
|---|---|
| `test_rt_expr_eval.py` | All BinOp, UnaryOp, field refs, nesting, error paths |
| `test_rt_runner_control_flow.py` | repeat/do_while/while_do/foreach/replicate/select/if_else/match |

---

## Phase 4 — Flow Objects

**Goal:** Buffer, Stream, and State scheduling semantics.

---

### T4.1 — `rt/flow_obj_rt.py`

**New file:** `src/zuspec/dataclasses/rt/flow_obj_rt.py`

```python
from __future__ import annotations

import asyncio
import dataclasses as dc
from typing import Generic, Optional, TypeVar

T = TypeVar("T")


@dc.dataclass
class BufferInstance(Generic[T]):
    """
    Wraps a Buffer object.  Producer sets it ready; consumers await readiness.
    PSS semantics: one producer, N consumers (sequential each).
    """
    obj: T
    _ready: asyncio.Future = dc.field(init=False)

    def __post_init__(self):
        loop = asyncio.get_event_loop()
        self._ready = loop.create_future()

    def set_ready(self) -> None:
        """Called by the producing action after body() completes."""
        if not self._ready.done():
            self._ready.set_result(self.obj)

    async def wait_ready(self) -> T:
        """Called by consuming actions; blocks until producer completes."""
        return await self._ready


@dc.dataclass
class StreamInstance(Generic[T]):
    """
    Connects one producer and one consumer.
    PSS semantics: producer and consumer execute in parallel; channel is
    the synchronisation point (capacity 1 — producer blocks until consumed).
    """
    _queue: asyncio.Queue = dc.field(default_factory=lambda: asyncio.Queue(maxsize=1))

    async def put(self, obj: T) -> None:
        await self._queue.put(obj)

    async def get(self) -> T:
        return await self._queue.get()


@dc.dataclass
class StatePool(Generic[T]):
    """
    Manages a single mutable state object.
    PSS semantics:
      - One writer at a time (exclusive); waits for all readers to finish.
      - Multiple concurrent readers allowed; writer excluded.
      - ``initial`` attribute: True until first write.
    """
    current: Optional[T] = None
    initial: bool = True
    _writer_lock: asyncio.Lock = dc.field(default_factory=asyncio.Lock)
    _reader_count: int = 0
    _no_readers: asyncio.Event = dc.field(default_factory=asyncio.Event)

    def __post_init__(self):
        self._no_readers.set()   # no readers initially

    async def write_acquire(self) -> None:
        await self._writer_lock.acquire()
        while self._reader_count > 0:
            self._no_readers.clear()
            await self._no_readers.wait()

    def write_release(self, new_state: T) -> None:
        self.current = new_state
        self.initial = False
        self._writer_lock.release()

    async def read_acquire(self) -> T:
        # Writers hold _writer_lock; readers do not, but track count.
        self._reader_count += 1
        return self.current

    def read_release(self) -> None:
        self._reader_count -= 1
        if self._reader_count == 0:
            self._no_readers.set()
```

---

### T4.2 — `ScheduleGraph` in `rt/activity_runner.py`

Add `ScheduleGraph` to compute dependency order for `_schedule()`:

```python
class ScheduleGraph:
    """
    Builds a partial order from flow-object producer/consumer relationships
    among the statements in a schedule block.
    """

    @staticmethod
    def build(stmts: list[ActivityStmt], ctx: ActionContext) -> "ScheduleGraph":
        """
        Analyse output/input flow-object fields on each statement's first
        action type to build producer→consumer edges.
        """
        graph = ScheduleGraph()
        graph._stmts = stmts
        graph._edges: list[tuple[int, int]] = []   # (producer_idx, consumer_idx)
        # For each pair of statements: if stmt_a produces a flow object
        # that stmt_b consumes, add edge a→b.
        for i, s_a in enumerate(stmts):
            outputs = _flow_outputs(s_a, ctx)
            for j, s_b in enumerate(stmts):
                if i == j:
                    continue
                inputs = _flow_inputs(s_b, ctx)
                if outputs & inputs:
                    graph._edges.append((i, j))
        return graph

    def stages(self) -> list[list]:
        """
        Return statements grouped into parallel stages via topological sort.
        Statements within a stage have no ordering dependency between them.
        """
        # Kahn's algorithm
        from collections import deque
        n = len(self._stmts)
        in_degree = [0] * n
        adj: dict[int, list[int]] = {i: [] for i in range(n)}
        for src, dst in self._edges:
            adj[src].append(dst)
            in_degree[dst] += 1
        queue = deque(i for i in range(n) if in_degree[i] == 0)
        stages = []
        while queue:
            stage = list(queue)
            queue.clear()
            stages.append([self._stmts[i] for i in stage])
            for i in stage:
                for j in adj[i]:
                    in_degree[j] -= 1
                    if in_degree[j] == 0:
                        queue.append(j)
        return stages
```

Replace the Phase 2 `_schedule()` stub with the graph-based implementation:

```python
async def _schedule(self, node: ActivitySchedule, ctx: ActionContext) -> None:
    graph = ScheduleGraph.build(node.stmts, ctx)
    for stage in graph.stages():
        coros = [
            self._exec(stmt, ActionContext(
                action=ctx.action, comp=ctx.comp,
                pool_resolver=ctx.pool_resolver, parent=ctx,
                seed=ctx.seed ^ i,
            ))
            for i, stmt in enumerate(stage)
        ]
        await asyncio.gather(*coros)
```

---

### T4.3 — Flow binding in `ActionContext` and `_traverse()`

Extend `_traverse()` in `ActivityRunner` to inject flow-object instances:

Before calling `_exec_action_body`, inject flow bindings from `child_ctx.flow_bindings`
onto the action:

```python
for field_name, flow_inst in child_ctx.flow_bindings.items():
    if isinstance(flow_inst, BufferInstance):
        if _is_output_field(action_type, field_name):
            # Inject the buffer object; producer calls flow_inst.set_ready() in body
            setattr(action, field_name, flow_inst.obj)
        else:
            # Consumer: block until buffer is ready
            setattr(action, field_name, await flow_inst.wait_ready())
    elif isinstance(flow_inst, StreamInstance):
        setattr(action, field_name, flow_inst)
    elif isinstance(flow_inst, StatePool):
        setattr(action, field_name, flow_inst)
```

Helper `_is_output_field(action_type, field_name)` checks `dc.fields()` metadata
for `{"kind": "flow_ref", "direction": "output"}`.

---

### T4.4 — Phase 4 Tests

Phase 4 tests span two files.  See **§ Testing Plan** for complete per-function
case lists.

| File | Cases |
|---|---|
| `test_rt_flow_objects.py` | BufferInstance, StreamInstance, StatePool primitives |
| `test_rt_schedule_graph.py` | ScheduleGraph topological sort, cycle detection |
| `test_rt_runner_flow.py` | Flow binding in _traverse(), full schedule scenarios |

---

## Phase 5 — Extensions, Scheduling Constraints, Tracer, Watchdog

**Goal:** Complete the remaining constructs and add operational tooling.

---

### T5.1 — `@zdc.extend` support in `ActivityRunner._super()`

**File:** `src/zuspec/dataclasses/rt/activity_runner.py`

When an action class has `__is_extension__ = True`, its `activity()` body is
merged with its base class activity per PSS implied-schedule semantics.  The
`ActivityRunner._exec_action_body()` helper must handle this:

```python
async def _exec_action_body(self, action_type, action, ctx):
    # Collect this class + all @extend subclasses
    extensions = _collect_extensions(action_type)
    if len(extensions) <= 1:
        # No extensions: normal execution
        activity_ir = getattr(action_type, "__activity__", None)
        if activity_ir:
            await ActivityRunner().run(activity_ir, ctx)
        else:
            await action.body()
    else:
        # Multiple extensions: implied schedule block
        from ..ir.activity import ActivitySchedule
        from ..ir.base import Base
        implied = ActivitySchedule(
            stmts=[e.__activity__ for e in extensions if hasattr(e, "__activity__")]
        )
        await self._schedule(implied, ctx)


def _collect_extensions(action_type: type) -> list[type]:
    """Return action_type plus all @extend subclasses registered for it."""
    result = [action_type]
    for sub in action_type.__subclasses__():
        if getattr(sub, "__is_extension__", False) and sub.__extends__ is action_type:
            result.append(sub)
    return result
```

---

### T5.2 — `ActivityConstraint` runtime (scheduling constraints)

`ActivityConstraint` carries IR expressions that constrain relationships
between sub-action fields *within the current activity scope*.  In the
Python runtime these become additional `randomize_with` constraints
passed to each affected traversal.

For Phase 5, collect all `ActivityConstraint` nodes in a sequence block
before processing traversals, and attach their expressions to the `inline_constraints`
of matching traversals via name-based matching:

```python
# In _seq(), pre-scan for ActivityConstraint nodes and collect them
# into a dict keyed by referenced handle names.
# Pass matching constraints as inline_constraints to _traverse_handle/anon.
```

---

### T5.3 — Tracer hooks

**File:** `src/zuspec/dataclasses/rt/tracer.py`

Extend the existing `Tracer` base class with activity-level events (no-op defaults):

```python
def action_start(self, action_type: type, comp: Any, seed: int) -> None:
    """Called before pre_solve() on each action traversal."""

def action_solved(self, action: Any) -> None:
    """Called after randomize() (post-solve state)."""

def action_exec_begin(self, action: Any) -> None:
    """Called just before body() or sub-activity."""

def action_exec_end(self, action: Any) -> None:
    """Called after body() or sub-activity completes."""

def resource_lock(self, pool: Any, instance_id: int) -> None:
    """Called when a resource lock is acquired."""

def resource_unlock(self, pool: Any, instance_id: int) -> None:
    """Called when a resource lock is released."""
```

Add corresponding `tracer.action_start(...)` etc. calls in `ActivityRunner._traverse()`.
Tracer is passed via `ActionContext` (add `tracer: Optional[Tracer] = None` field).

---

### T5.4 — Deadlock watchdog in `ScenarioRunner`

**File:** `src/zuspec/dataclasses/rt/scenario_runner.py`

```python
async def run(self, action_type: Type, timeout_s: float = 30.0, **kwargs) -> None:
    try:
        async with asyncio.timeout(timeout_s):
            ...   # existing run logic
    except asyncio.TimeoutError:
        raise DeadlockError(
            f"Scenario did not complete within {timeout_s}s — "
            f"possible deadlock in resource acquisition"
        )


class DeadlockError(RuntimeError):
    pass
```

Export `DeadlockError` from `__init__.py`.

---

### T5.5 — Phase 5 Tests

Phase 5 tests span two files.  See **§ Testing Plan** for complete per-function
case lists.

| File | Cases |
|---|---|
| `test_rt_tracer.py` | All 8 tracer events, custom subclass, event ordering |
| `test_rt_runner_extensions.py` | @extend, ActivityConstraint, watchdog, bind |

---

## Testing Plan

All test files live in `packages/zuspec-dataclasses/tests/unit/` unless
noted as integration.  Naming convention: `test_rt_*.py` for runtime tests
(distinguished from existing `test_activity_*.py` activity-parser tests).

Tests use plain pytest functions (not classes), `pytest-asyncio` for async
fixtures, and `unittest.mock` for stubs.  Existing tests must continue to
pass throughout all phases.

---

### Test Infrastructure

**New file:** `packages/zuspec-dataclasses/tests/unit/conftest.py`

Shared fixtures and helpers used across all `test_rt_*.py` files.

```python
import asyncio
import dataclasses as dc
from typing import Optional
import pytest
import zuspec.dataclasses as zdc
from zuspec.dataclasses.rt.scenario_runner import ScenarioRunner


# ── Minimal domain model used by most tests ─────────────────────────────────

@zdc.dataclass
class SimpleCpu(zdc.Component):
    pass


@zdc.dataclass
class SimpleAction(zdc.Action[SimpleCpu]):
    x: int = zdc.rand(zdc.rangelist((0, 63)))
    y: int = zdc.rand(zdc.rangelist((0, 63)))
    _call_log: list = dc.field(default_factory=list, compare=False)

    async def body(self) -> None:
        self._call_log.append(("body", self.x, self.y))


@zdc.dataclass
class TrackingAction(zdc.Action[SimpleCpu]):
    """Records lifecycle events for ordering assertions."""
    events: list = dc.field(default_factory=list, compare=False)

    def pre_solve(self)  -> None: self.events.append("pre_solve")
    def post_solve(self) -> None: self.events.append("post_solve")
    async def body(self) -> None: self.events.append("body")


# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture
def simple_cpu():
    return SimpleCpu()


@pytest.fixture
def runner(simple_cpu):
    return ScenarioRunner(simple_cpu, seed=0)


@pytest.fixture
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


# ── Async helper ─────────────────────────────────────────────────────────────

def run(coro):
    """Run an async test coroutine synchronously."""
    return asyncio.get_event_loop().run_until_complete(coro)
```

---

### `test_activity_parser_loc.py` — Source Location Population

Extends the existing `test_activity_parser.py`.  All tests here require T1.1
(loc population) to be complete.

| Test function | What it verifies |
|---|---|
| `test_loc_populated_on_traversal` | `ActivityTraversal.loc.file` ends with the test source filename |
| `test_loc_populated_on_anon_traversal` | `ActivityAnonTraversal.loc.line > 0` |
| `test_loc_populated_on_parallel` | `ActivityParallel.loc` is not `None` |
| `test_loc_populated_on_repeat` | `ActivityRepeat.loc.line` is a positive int |
| `test_loc_line_increases_downward` | Second stmt in a sequence has `loc.line > first.loc.line` |
| `test_loc_file_matches_source_file` | `loc.file == inspect.getsourcefile(action_class.activity)` |
| `test_cache_key_includes_file` | Parsing identical body from two files gives different `loc.file` values |
| `test_loc_on_nested_block` | Statements inside a parallel branch carry correct `loc` |
| `test_action_type_cls_resolved` | `ActivityAnonTraversal.action_type_cls is MyAction` (not `None`) |
| `test_action_type_cls_qualified_name` | Qualified name `pkg.MyAction` resolves to the class object |

---

### `test_rt_debug.py` — Debugger Line Events

| Test function | What it verifies |
|---|---|
| `test_no_op_without_trace` | `_fire_line_event("f.py", 10, {})` completes silently when `sys.gettrace() is None` |
| `test_no_op_empty_filename` | `filename=""` is silently skipped even with trace active |
| `test_no_op_zero_lineno` | `lineno=0` is silently skipped |
| `test_trace_callback_called` | Installing a `sys.settrace` spy; `_fire_line_event` causes it to fire |
| `test_trace_filename_matches` | Trace callback receives `frame.f_code.co_filename == filename` |
| `test_trace_lineno_matches` | Trace callback receives `frame.f_lineno == lineno` |
| `test_local_vars_accessible` | `local_vars={"x": 42}` is visible in trace callback frame locals |
| `test_trace_with_none_local_vars` | Passing `local_vars=None` does not raise |
| `test_runner_fires_event_per_stmt` | `ActivityRunner` calls `_fire_line_event` once per statement with populated `loc` |
| `test_runner_skips_event_no_loc` | Statements with `loc=None` do not cause `_fire_line_event` to raise |

---

### `test_rt_action_context.py` — ActionContext

| Test function | What it verifies |
|---|---|
| `test_construct_minimal` | Required fields `action`, `comp`, `pool_resolver` |
| `test_defaults` | `parent=None`, `seed=0`, `inline_constraints=[]`, `flow_bindings={}`, `head_resource_hints={}` |
| `test_parent_chain` | `child.parent.parent is None` for depth-2 chain |
| `test_seed_type` | `seed` must be an `int` (not float, not None) |
| `test_flow_bindings_mutable_per_instance` | Two `ActionContext` instances do not share the same `flow_bindings` dict |
| `test_inline_constraints_mutable_per_instance` | Same for `inline_constraints` |

---

### `test_rt_pool_resolver.py` — PoolResolver

Covers both Phase 1 (component selection) and Phase 2 (bind directives).
Organised with `# --- Phase 1 ---` and `# --- Phase 2 ---` comment headers
within the file.

**Phase 1 — component selection:**

| Test function | What it verifies |
|---|---|
| `test_build_single_comp` | `PoolResolver.build(cpu)` indexes one instance of `SimpleCpu` |
| `test_build_nested_comp` | `build(soc)` indexes `soc.core0` and `soc.core1` separately |
| `test_select_comp_returns_instance` | Returns a `SimpleCpu` when action type is `Action[SimpleCpu]` |
| `test_select_comp_random` | With 2 `SimpleCpu` instances, both are selected across many calls |
| `test_select_comp_wrong_type_raises` | Action type requiring `DmaCpu` raises `RuntimeError` from `SimpleCpu` tree |
| `test_select_comp_error_message_includes_type` | Exception message contains `DmaCpu` |
| `test_action_comp_type_extracts_T` | `_action_comp_type(Action[SimpleCpu])` returns `SimpleCpu` |
| `test_action_comp_type_indirect_subclass` | Works for `class MyAction(Action[SimpleCpu])` |
| `test_action_comp_type_no_annotation_returns_none` | Bare `Action` without type param returns `None` |

**Phase 2 — bind directives:**

| Test function | What it verifies |
|---|---|
| `test_index_pools_finds_claim_pool` | `ClaimPool` field on component is indexed |
| `test_resolve_pool_explicit_bind` | `__bind__` mapping resolves to correct pool |
| `test_resolve_pool_wildcard` | Wildcard bind (`'*'`) matches any action field of that type |
| `test_resolve_pool_type_scan_fallback` | No `__bind__`; pool found by element type scan |
| `test_resolve_pool_none_if_not_found` | Returns `None` when no pool is discoverable |
| `test_multiple_pools_same_type` | Raises `RuntimeError` when ambiguous (two pools same elem type, no bind) |
| `test_bind_method_not_inherited` | `__bind__` defined on base not used for derived component |
| `test_index_buffer_pool_found` | `BufferPool` field is also indexed |
| `test_resolve_pool_by_type_method` | `resolve_pool_by_type(action_type, field_name, comp)` method used by `BindingSolver` |

---

### `test_rt_runner_sequential.py` — Sequential Traversal Lifecycle

| Test function | What it verifies |
|---|---|
| `test_atomic_body_called` | `body()` is awaited after `randomize()` |
| `test_rand_fields_not_default_after_run` | `x` and `y` are set (not both 0) after running `SimpleAction` |
| `test_solver_called_once_per_traversal` | `randomize` mock called exactly once per action traversal |
| `test_pre_solve_before_randomize` | `pre_solve()` fires before solver; verified via mock ordering |
| `test_post_solve_after_randomize` | `post_solve()` fires after solver; verified via mock ordering |
| `test_body_after_post_solve` | `body()` fires after `post_solve()` |
| `test_sequential_two_actions_ordered` | First action's body completes before second action's `pre_solve` |
| `test_comp_assigned_before_pre_solve` | `action.comp` is set before `pre_solve()` fires |
| `test_nested_compound_recurses` | Compound action's sub-activity is walked (not just `body()`) |
| `test_run_n_calls_body_n_times` | `ScenarioRunner.run_n(SimpleAction, 5)` → body called 5× |
| `test_no_comp_raises_runtime_error` | Action requiring `DmaCpu` on a `SimpleCpu` tree raises `RuntimeError` |
| `test_error_message_contains_action_type` | `RuntimeError` message includes action class name |

---

### `test_rt_runner_traversal.py` — Handle, Anonymous, Super Traversal

| Test function | What it verifies |
|---|---|
| `test_handle_traversal_resolves_type` | `self.write` handle is resolved; `WriteAction` is instantiated |
| `test_handle_traversal_missing_handle_raises` | Non-existent handle name raises `RuntimeError` |
| `test_anon_traversal_by_class_ref` | `do(WriteAction)` with pre-resolved `action_type_cls` works |
| `test_anon_traversal_by_string_fallback` | `action_type_cls=None` falls back to name lookup in module |
| `test_anon_traversal_unknown_type_raises` | Unknown type string raises `RuntimeError` |
| `test_anon_traversal_label_writeback` | `with do(WriteAction) as w:` — `action.w` is set after traversal |
| `test_super_traversal_runs_parent_body` | `super().activity()` runs parent's activity block |
| `test_super_traversal_no_parent_is_noop` | Action with no parent activity silently continues |
| `test_super_traversal_parent_fields_accessible` | Parent block can read child action fields |
| `test_inline_constraints_recorded` | `with do(Type) as x:` block stores constraints in IR node |

---

### `test_rt_scenario_runner.py` — ScenarioRunner and run_action

| Test function | What it verifies |
|---|---|
| `test_run_awaits_action_body` | `body()` called after `await runner.run(SimpleAction)` |
| `test_same_seed_same_result` | Two `ScenarioRunner(seed=42).run(SimpleAction)` produce identical field values |
| `test_different_seed_different_result` | Seeds 42 and 43 produce different field values (probabilistic) |
| `test_run_n_sequential` | `run_n(SimpleAction, 3)` calls body 3 times sequentially |
| `test_seed_advances_between_runs` | Second `run()` on same runner gives different result than first (seed advances) |
| `test_run_action_helper` | `await run_action(cpu, SimpleAction)` works without constructing runner |
| `test_run_action_sync_helper` | `run_action_sync(cpu, SimpleAction)` completes without event-loop setup |
| `test_run_action_sync_raises_on_error` | Exception from `body()` propagates through `run_action_sync` |
| `test_run_returns_action_instance` | `await runner.run(SimpleAction)` returns the traversed `SimpleAction` instance |
| `test_random_seed_when_none` | `ScenarioRunner(cpu, seed=None)` picks a random seed (runs without error) |

---

### `test_rt_regression_action_call.py` — `Action.__call__` Backwards Compatibility

These tests protect the existing interface used by all pre-runtime tests.

| Test function | What it verifies |
|---|---|
| `test_action_call_runs_body` | `await SimpleAction(cpu)(cpu)` still calls `body()` |
| `test_action_call_sets_comp` | After call, `action.comp is cpu` |
| `test_action_call_solves_fields` | Rand fields are non-zero after call |
| `test_existing_activity_e2e_dma_still_passes` | Re-run `test_activity_e2e_dma.py` cases via import — no regressions |
| `test_existing_parallel_tests_still_pass` | Re-run parser parallel tests via import |

---

### `test_rt_resource.py` — Resource Field Introspection and Acquisition

| Test function | What it verifies |
|---|---|
| `test_get_resource_fields_empty` | Action with no resource fields returns `[]` |
| `test_get_resource_fields_lock` | `lock()` field detected with `claim="lock"` |
| `test_get_resource_fields_share` | `share()` field detected with `claim="share"` |
| `test_get_resource_fields_both` | Action with one lock + one share — both returned |
| `test_get_resource_fields_type_hint` | `field_type` in `ResourceFieldInfo` matches declared type |
| `test_acquire_lock_claim_sets_field` | `acquire_resources(action, ctx)` sets action's lock field to pool item |
| `test_acquire_share_claim_sets_field` | Same for share field |
| `test_acquire_returns_claims_list` | Returns `[(pool, claim)]` pairs |
| `test_release_drops_all_claims` | All claims released in reverse order |
| `test_acquire_ordering_by_pool_id` | Multiple pools acquired in `id(pool)` order (deterministic) |
| `test_acquire_blocks_on_unavailable` | Second task blocks until first releases; both complete |
| `test_release_on_exception` | Exception in `body()` still releases resources via `finally` |

---

### `test_rt_binding_solver.py` — BindingSolver

| Test function | What it verifies |
|---|---|
| `test_solve_heads_single_branch` | One branch, one pool → one assignment with any valid instance_id |
| `test_solve_heads_two_branches_two_instances` | 2 branches, 2-instance pool → assignments are distinct |
| `test_solve_heads_three_branches_three_instances` | 3 branches, 3-instance pool → all three distinct |
| `test_solve_heads_no_lock_fields` | Actions with no lock fields → all assignments are empty dicts |
| `test_solve_heads_infeasible_raises` | 3 branches, 2-instance pool → `RuntimeError` |
| `test_solve_heads_error_message_informative` | `RuntimeError` includes pool size and claim count |
| `test_solve_heads_share_fields_not_constrained` | `share()` fields not included in AllDifferent constraint |
| `test_solve_heads_multiple_pools_independent` | Two independent pools solved independently |
| `test_assignments_within_domain` | Every `instance_id` is a valid index into pool domain |
| `test_solve_heads_deterministic_with_seed` | Same `ctx.seed` → same assignments |

---

### `test_rt_runner_parallel.py` — Parallel, Schedule, and Atomic Blocks

All tests use `pytest.mark.asyncio`.

| Test function | What it verifies |
|---|---|
| `test_parallel_two_branches_run` | Both branches' `body()` are called |
| `test_parallel_branches_get_distinct_resources` | Each branch holds a different `instance_id` for same pool |
| `test_parallel_join_all_waits` | Default `join_all`: parent awaits both branches |
| `test_parallel_join_none_parent_continues` | `join_none`: parent proceeds before branches finish |
| `test_parallel_join_first_one_branch` | `join_first=1`: parent resumes after earliest branch |
| `test_parallel_resource_contention` | 1-instance pool, 2 branches: only one branch active at a time |
| `test_schedule_two_independent_actions` | Two actions with no flow deps run concurrently |
| `test_schedule_producer_before_consumer` | Actions with buffer dependency run in dependency order |
| `test_schedule_resource_no_overlap` | Actions sharing a lock don't overlap |
| `test_atomic_no_interleaving` | External concurrent task cannot insert between atomic statements |
| `test_atomic_nested_in_parallel` | Atomic inside each parallel branch still preserves atomicity |
| `test_parallel_seed_differs_per_branch` | Each branch gets a different seed (`ctx.seed ^ i`) |
| `test_gather_with_join_all` | `_gather_with_join(coros, join_spec=None)` → all coros run |
| `test_gather_with_join_first_count` | `join_spec.count=2` → exactly 2 branches awaited |

---

### `test_rt_decorators.py` — Decorators

| Test function | What it verifies |
|---|---|
| `test_pool_returns_field_descriptor` | `pool()` return value is a `dataclasses.Field` (not `None`) |
| `test_pool_metadata_kind` | `field.metadata["kind"] == "pool"` |
| `test_pool_size_in_metadata` | `pool(size=4)` puts `"size": 4` in metadata |
| `test_pool_default_factory` | Component with `pool(default_factory=...)` creates pool at instantiation |
| `test_pool_field_is_usable_in_dataclass` | `@zdc.dataclass` component with `pool()` field compiles and instantiates |
| `test_lock_metadata_kind` | `lock()` field has `metadata["kind"] == "resource_ref"` |
| `test_lock_metadata_claim` | `lock()` field has `metadata["claim"] == "lock"` |
| `test_share_metadata_claim` | `share()` field has `metadata["claim"] == "share"` |
| `test_extend_sets_flag` | `@zdc.extend(Base)` sets `__is_extension__ = True` on subclass |
| `test_extend_sets_target` | `__extends__` is `Base` |

---

### `test_rt_expr_eval.py` — ExprEval

One test function per operator / expression type.  Uses IR nodes constructed
directly (not via parser) so tests are independent of parser correctness.

| Test function | What it verifies |
|---|---|
| `test_eval_constant_int` | `ExprConstant(42)` → `42` |
| `test_eval_constant_bool` | `ExprConstant(True)` → `True` |
| `test_eval_field_ref_simple` | `ExprFieldRef(path=["x"])` reads `action.x` |
| `test_eval_field_ref_nested` | `ExprFieldRef(path=["addr", "base"])` reads `action.addr.base` |
| `test_eval_field_ref_missing_raises` | Non-existent field raises `AttributeError` |
| `test_eval_add` | `BinOp.ADD` — integer addition |
| `test_eval_sub` | `BinOp.SUB` |
| `test_eval_mul` | `BinOp.MUL` |
| `test_eval_div` | `BinOp.DIV` — integer floor division |
| `test_eval_mod` | `BinOp.MOD` |
| `test_eval_eq_true` | `BinOp.EQ` when operands are equal |
| `test_eval_eq_false` | `BinOp.EQ` when operands differ |
| `test_eval_ne` | `BinOp.NE` |
| `test_eval_lt` | `BinOp.LT` |
| `test_eval_le` | `BinOp.LE` |
| `test_eval_gt` | `BinOp.GT` |
| `test_eval_ge` | `BinOp.GE` |
| `test_eval_bitwise_and` | `BinOp.AND` |
| `test_eval_bitwise_or` | `BinOp.OR` |
| `test_eval_bitwise_xor` | `BinOp.XOR` |
| `test_eval_logical_and` | `BinOp.LAND` short-circuits |
| `test_eval_logical_or` | `BinOp.LOR` short-circuits |
| `test_eval_shl` | `BinOp.SHL` |
| `test_eval_shr` | `BinOp.SHR` |
| `test_eval_neg` | `UnaryOp.NEG` |
| `test_eval_bitwise_not` | `UnaryOp.NOT` |
| `test_eval_logical_not` | `UnaryOp.LNOT` |
| `test_eval_cond_true` | `ExprCond(cond=T)` evaluates `true_val` branch |
| `test_eval_cond_false` | `ExprCond(cond=F)` evaluates `false_val` branch |
| `test_eval_nested_expr` | `(a + b) * (c - d)` with all IR nodes |
| `test_unknown_expr_type_raises` | Unrecognised `Expr` subclass raises `RuntimeError` |

---

### `test_rt_runner_control_flow.py` — Control Flow

All tests use `pytest.mark.asyncio`.

| Test function | What it verifies |
|---|---|
| `test_repeat_literal_count` | `repeat(3)` → body runs exactly 3 times |
| `test_repeat_rand_field_count` | `repeat(self.n)` — body runs `n` times where `n` was solved |
| `test_repeat_index_var_set` | Loop variable `i` is set on action for each iteration |
| `test_repeat_zero_count_skipped` | `repeat(0)` → body never runs |
| `test_do_while_runs_once_minimum` | Even with false condition, body runs once |
| `test_do_while_multiple_iterations` | Runs until condition becomes false |
| `test_while_do_false_initially_skipped` | Body never runs if condition starts false |
| `test_while_do_multiple_iterations` | Runs until condition becomes false |
| `test_foreach_list_all_items` | All items in list are visited |
| `test_foreach_empty_list_skipped` | Empty list → body never runs |
| `test_foreach_index_var_increments` | Index variable increases each iteration |
| `test_replicate_count` | `replicate(4)` runs body 4 times |
| `test_replicate_index_var` | Index variable set correctly per copy |
| `test_select_both_branches_reachable` | Equal-weight select: both branches hit across 200 runs |
| `test_select_guard_false_excluded` | Branch with `False` guard never selected |
| `test_select_guard_all_false_raises` | All guards false raises `RuntimeError` |
| `test_select_weight_biased` | 9:1 weight: high-weight branch taken ≥ 80% across 500 runs |
| `test_if_else_true_branch` | True condition → if body runs |
| `test_if_else_false_branch` | False condition → else body runs |
| `test_if_else_no_else_noop` | False condition, no else clause → silent skip |
| `test_match_first_case_matches` | Correct case body runs |
| `test_match_no_case_matches` | No matching case → silent skip (no exception) |
| `test_match_only_first_match_runs` | Multiple matching cases: only first is executed |

---

### `test_rt_flow_objects.py` — Flow Object Primitives

All tests use `pytest.mark.asyncio`.

| Test function | What it verifies |
|---|---|
| `test_buffer_set_ready_resolves_wait` | `set_ready()` unblocks a waiting `wait_ready()` |
| `test_buffer_consumer_gets_correct_object` | Correct object returned from `wait_ready()` |
| `test_buffer_double_wait_gets_same_object` | Two consumers both see the same object |
| `test_buffer_wait_before_ready` | Consumer task blocks until producer calls `set_ready()` |
| `test_stream_put_get_roundtrip` | `put(obj)` followed by `get()` returns `obj` |
| `test_stream_producer_blocks_until_consumed` | With `maxsize=1`, second `put()` blocks until `get()` |
| `test_stream_async_producer_consumer` | Producer and consumer tasks run concurrently; data transferred |
| `test_state_initial_flag_true` | `StatePool.initial` starts `True` |
| `test_state_initial_flag_false_after_write` | `initial` is `False` after first `write_release()` |
| `test_state_write_exclusive` | Second writer waits until first releases |
| `test_state_multiple_readers_concurrent` | Multiple `read_acquire()` calls proceed simultaneously |
| `test_state_write_waits_for_all_readers` | Writer blocks until all active readers call `read_release()` |
| `test_state_value_updated_after_write` | `current` reflects new value after `write_release()` |

---

### `test_rt_schedule_graph.py` — ScheduleGraph

| Test function | What it verifies |
|---|---|
| `test_no_deps_single_stage` | Three independent actions → one stage with all three |
| `test_single_dep_two_stages` | Producer→consumer → stage 0 has producer, stage 1 has consumer |
| `test_chain_three_stages` | A→B→C → three sequential stages |
| `test_diamond_dependency` | A→B, A→C, B→D, C→D → A / (B,C) / D |
| `test_cycle_detection_raises` | Cyclic dependency raises `RuntimeError` |
| `test_empty_stmts_returns_empty` | Zero statements → zero stages |
| `test_single_stmt_single_stage` | One statement → one stage of size 1 |

---

### `test_rt_runner_flow.py` — Flow Binding in ActivityRunner

All tests use `pytest.mark.asyncio`.

| Test function | What it verifies |
|---|---|
| `test_buffer_injected_into_producer` | Producer's buffer field is set to `BufferInstance.obj` |
| `test_buffer_consumer_blocks_until_produced` | Consumer action blocked until producer body runs |
| `test_stream_injected_into_both` | Both producer and consumer receive the same `StreamInstance` |
| `test_schedule_buffer_ordering_enforced` | Schedule block with buffer dep: producer completes before consumer |
| `test_schedule_independent_concurrent` | Schedule block without flow deps: actions run concurrently |
| `test_state_injected_as_pool` | State field receives `StatePool` instance |
| `test_flow_bindings_cleared_between_traversals` | Flow bindings from one traversal don't leak to sibling |

---

### `test_rt_tracer.py` — Tracer Hooks

| Test function | What it verifies |
|---|---|
| `test_action_start_called_once_per_traversal` | `action_start` fires exactly once per traversal |
| `test_action_solved_called_after_randomize` | `action_solved` fires after `randomize()`, action fields are set |
| `test_action_exec_begin_called` | `action_exec_begin` fires before `body()` |
| `test_action_exec_end_called` | `action_exec_end` fires after `body()` |
| `test_resource_lock_event_on_acquire` | `resource_lock(pool, instance_id)` fires on each lock |
| `test_resource_unlock_event_on_release` | `resource_unlock(pool, instance_id)` fires on each release |
| `test_ordering_start_solved_begin_end` | Events arrive in correct order for a single traversal |
| `test_no_tracer_no_error` | `ctx.tracer=None` (default) — runner completes without error |
| `test_custom_tracer_subclass` | User subclass overriding `action_start` receives correct `action_type` |
| `test_tracer_receives_comp_reference` | `action_start(action_type, comp, seed)` — `comp` is the bound component |
| `test_nested_traversal_events` | Compound action: events for outer and inner traversals both fired |
| `test_tracer_passed_via_context` | `ActionContext(tracer=my_tracer)` routes events to custom tracer |

---

### `test_rt_runner_extensions.py` — @extend, Constraints, Watchdog

All tests use `pytest.mark.asyncio`.

| Test function | What it verifies |
|---|---|
| `test_extend_single_extension_runs` | `@extend(Base)` body runs alongside base body |
| `test_extend_two_extensions_run` | Two extensions: all three (base + 2 ext) bodies run |
| `test_extend_implied_schedule_ordering` | Extended action obeys flow-object deps from extensions |
| `test_activity_constraint_restricts_field` | `constraint(self.x > 50)` — solved `x` is always > 50 |
| `test_activity_constraint_cross_action` | Constraint between two sub-action fields is satisfied |
| `test_watchdog_fires_on_deadlock` | Task holding lock, second task tries to acquire same lock → `DeadlockError` within timeout |
| `test_watchdog_does_not_fire_on_fast_completion` | Fast scenario completes before watchdog timeout |
| `test_deadlock_error_is_runtime_error` | `DeadlockError` inherits from `RuntimeError` |
| `test_activity_bind_connects_ref_to_pool` | `bind(self.out_buf, self.in_buf)` connects matching fields |

---

## Integration Test Scenarios

Integration tests live in `packages/zuspec-dataclasses/tests/unit/` using
the `test_rt_e2e_*.py` naming prefix.  They exercise complete, realistic
PSS patterns with multiple features active simultaneously.

---

### `test_rt_e2e_dma.py` — DMA Transfer Scenario

Models the canonical PSS LRM Example 45 DMA pattern.  A compound action
performs a parallel read + write using two channels from a `ClaimPool`.

| Test function | What it verifies |
|---|---|
| `test_dma_sequential_transfer` | Single `DmaTransfer` compound action: both `DmaRead` and `DmaWrite` body called |
| `test_dma_rand_fields_solved` | `addr` and `size` fields are set (non-default) after run |
| `test_dma_parallel_distinct_channels` | Parallel read/write each claim a distinct channel |
| `test_dma_channel_released_after_transfer` | After run, all channel claims are dropped (pool back to full) |
| `test_dma_run_n_no_channel_leak` | `run_n(10)` never deadlocks; pool always returns to full size |
| `test_dma_seed_reproducible` | Same seed → same address/size in both read and write sub-actions |
| `test_dma_component_hierarchy` | `DmaTop` has two `DmaEngine` children; both are viable comp assignments |

---

### `test_rt_e2e_pipeline.py` — Producer–Consumer Pipeline

Models a stream pipeline: `Encode → Compress → Send` via stream flow objects.

| Test function | What it verifies |
|---|---|
| `test_pipeline_end_to_end` | Full pipeline runs; all three stage bodies called |
| `test_pipeline_ordering_enforced` | Encode completes before Compress starts; Compress before Send |
| `test_pipeline_data_flows_correctly` | Encoded data arrives at Compress; compressed data arrives at Send |
| `test_pipeline_run_n_no_stall` | `run_n(5)` produces 5 complete pipeline runs without stalling |
| `test_pipeline_rand_payload_size` | Random payload size field is solved and consistent across stages |

---

### `test_rt_e2e_nested_parallel.py` — Nested Parallel with Shared Resources

Two-level parallel block where each outer branch contains an inner parallel
block, all sharing resources from a single `ClaimPool`.

| Test function | What it verifies |
|---|---|
| `test_nested_parallel_all_bodies_run` | All 4 leaf actions run |
| `test_nested_parallel_distinct_resources` | All 4 leaf actions hold distinct resource instances |
| `test_nested_parallel_no_deadlock` | Completes within watchdog timeout |
| `test_nested_parallel_total_resource_count` | Pool size == max concurrent claims (4 for 4 parallel leaves) |
| `test_nested_parallel_pool_empty_during_run` | Pool has 0 free slots while all leaves are active |
| `test_nested_parallel_pool_full_after_run` | Pool returns to full size after run |

---

### `test_rt_e2e_control_flow_compound.py` — Control Flow in Compound Actions

Tests loops and selects nested inside compound actions.

| Test function | What it verifies |
|---|---|
| `test_repeat_with_resource_per_iter` | Each repeat iteration locks then releases a resource |
| `test_foreach_with_parallel` | `foreach` containing a `parallel` — all iterations complete |
| `test_select_inside_parallel` | Parallel branches each independently select a sub-action |
| `test_while_do_with_shared_state` | Loop iterates until `State` object reaches a condition |
| `test_nested_compound_solver_per_action` | Every action at every nesting level has its rand fields solved |
| `test_control_flow_tracer_events` | Tracer receives correct number of `action_start` events for loop body |

---

## Documentation Tests

Documentation tests verify that:

1. Docstring examples in each new `rt/` module execute correctly.
2. Code blocks in `pss-python-execution-design.md` that are marked as
   executable remain valid Python as the implementation evolves.

---

### `test_rt_doctest.py` — Module Docstring Examples

Uses `pytest`'s built-in `doctest` integration to run all `>>>` examples
embedded in new module docstrings.

```python
"""Run doctests from all rt/ modules."""
import doctest
import importlib
import pytest

RT_MODULES = [
    "zuspec.dataclasses.rt.debug_rt",
    "zuspec.dataclasses.rt.action_context",
    "zuspec.dataclasses.rt.pool_resolver",
    "zuspec.dataclasses.rt.activity_runner",
    "zuspec.dataclasses.rt.scenario_runner",
    "zuspec.dataclasses.rt.resource_rt",
    "zuspec.dataclasses.rt.binding_solver",
    "zuspec.dataclasses.rt.expr_eval",
    "zuspec.dataclasses.rt.flow_obj_rt",
    "zuspec.dataclasses.rt.tracer",
]


@pytest.mark.parametrize("module_name", RT_MODULES)
def test_module_doctest(module_name):
    mod = importlib.import_module(module_name)
    results = doctest.testmod(mod, verbose=False, optionflags=doctest.ELLIPSIS)
    assert results.failed == 0, (
        f"{results.failed} doctest(s) failed in {module_name}"
    )
```

Each `rt/` module **must** contain at least one `>>>` example in its module
docstring or a top-level class/function docstring demonstrating the
primary usage.  Required examples per module:

| Module | Required docstring example |
|---|---|
| `debug_rt.py` | Show `_fire_line_event` call with `sys.gettrace() is None` check |
| `action_context.py` | Construct an `ActionContext` with minimal fields |
| `pool_resolver.py` | `PoolResolver.build(comp)` then `select_comp(ActionType, comp)` |
| `scenario_runner.py` | `run_action_sync(comp, MyAction)` usage block |
| `flow_obj_rt.py` | `BufferInstance` producer/consumer pattern |
| `resource_rt.py` | `get_resource_fields(MyAction)` output |

---

### `test_rt_design_doc_examples.py` — Design Document Code Snippets

The design document `pss-python-execution-design.md` contains code examples
that must remain valid Python.  These tests extract and execute marked blocks.

Convention: code blocks in the design doc that should be tested are preceded
by a comment line `<!-- test: <test_id> -->`.  The test extracts these blocks
by scanning for the marker pattern.

```python
"""
Validate runnable code examples in pss-python-execution-design.md.

Only blocks tagged with <!-- test: <id> --> are executed.
"""
import re
from pathlib import Path
import pytest

DESIGN_DOC = Path(__file__).parents[4] / "pss-python-execution-design.md"

def _extract_tagged_examples(path: Path) -> list[tuple[str, str]]:
    """Return list of (test_id, code_block) pairs."""
    text = path.read_text()
    pattern = re.compile(
        r"<!--\s*test:\s*(\S+)\s*-->\s*```python\s*\n(.*?)```",
        re.DOTALL,
    )
    return [(m.group(1), m.group(2)) for m in pattern.finditer(text)]


EXAMPLES = _extract_tagged_examples(DESIGN_DOC)


@pytest.mark.parametrize("test_id,code", EXAMPLES, ids=[e[0] for e in EXAMPLES])
def test_design_doc_example(test_id, code, tmp_path):
    """Execute a tagged code block from the design document."""
    globs: dict = {}
    try:
        exec(compile(code, f"design_doc:{test_id}", "exec"), globs)  # noqa: S102
    except Exception as exc:
        pytest.fail(f"Design doc example '{test_id}' raised: {exc}")
```

Code blocks to tag in `pss-python-execution-design.md`:

| Tag | Section | What the example shows |
|---|---|---|
| `basic-run-action` | §ScenarioRunner | `run_action_sync(comp, EntryAction)` pattern |
| `scenario-runner-construct` | §ScenarioRunner | `ScenarioRunner(comp, seed=42)` |
| `action-lifecycle` | §Action lifecycle | `pre_solve / randomize / post_solve / body` ordering |
| `claim-pool-usage` | §Resource management | `ClaimPool.fromList([...])` + `lock()` + `drop()` |
| `buffer-producer-consumer` | §Flow objects | `BufferInstance` producer → consumer |
| `state-pool-write-read` | §Flow objects | `StatePool` writer/reader pattern |
| `debug-line-event` | §Debugger integration | `_fire_line_event("file.py", 42, {})` no-op demo |

---

### Documentation Content Requirements

Beyond executable code, these narrative documentation requirements apply to
all new modules:

| Requirement | Where |
|---|---|
| Module-level docstring explaining purpose and usage | Every new `rt/*.py` file |
| Class-level docstring explaining invariants | `ActivityRunner`, `ScenarioRunner`, `PoolResolver`, all flow-object classes |
| Parameter and return-value docstrings | All public functions with non-obvious signatures |
| `Raises:` section | Functions that raise documented exceptions (`RuntimeError`, `DeadlockError`) |
| `Note:` for asyncio requirements | Any `async def` that must be awaited inside an event loop |
| Cross-reference to design doc | Each new module docstring links to § in `pss-python-execution-design.md` |

---

## Test File Inventory

All test paths are relative to `packages/zuspec-dataclasses/`.

| File | Tier | Phase | ~Cases |
|---|---|---|---|
| `tests/unit/conftest.py` | Infrastructure | 1 | — |
| `tests/unit/test_activity_parser_loc.py` | Unit | 1 | 10 |
| `tests/unit/test_rt_debug.py` | Unit | 1 | 10 |
| `tests/unit/test_rt_action_context.py` | Unit | 1 | 6 |
| `tests/unit/test_rt_pool_resolver.py` | Unit | 1–2 | 18 |
| `tests/unit/test_rt_runner_sequential.py` | Unit | 1 | 12 |
| `tests/unit/test_rt_runner_traversal.py` | Unit | 1 | 10 |
| `tests/unit/test_rt_scenario_runner.py` | Unit | 1 | 10 |
| `tests/unit/test_rt_regression_action_call.py` | Regression | 1 | 5 |
| `tests/unit/test_rt_resource.py` | Unit | 2 | 12 |
| `tests/unit/test_rt_binding_solver.py` | Unit | 2 | 10 |
| `tests/unit/test_rt_runner_parallel.py` | Unit | 2 | 14 |
| `tests/unit/test_rt_decorators.py` | Unit | 2 | 10 |
| `tests/unit/test_rt_expr_eval.py` | Unit | 3 | 31 |
| `tests/unit/test_rt_runner_control_flow.py` | Unit | 3 | 23 |
| `tests/unit/test_rt_flow_objects.py` | Unit | 4 | 13 |
| `tests/unit/test_rt_schedule_graph.py` | Unit | 4 | 7 |
| `tests/unit/test_rt_runner_flow.py` | Unit | 4 | 7 |
| `tests/unit/test_rt_tracer.py` | Unit | 5 | 12 |
| `tests/unit/test_rt_runner_extensions.py` | Unit | 5 | 9 |
| `tests/unit/test_rt_e2e_dma.py` | Integration | 1–2 | 7 |
| `tests/unit/test_rt_e2e_pipeline.py` | Integration | 2–4 | 5 |
| `tests/unit/test_rt_e2e_nested_parallel.py` | Integration | 2 | 6 |
| `tests/unit/test_rt_e2e_control_flow_compound.py` | Integration | 2–4 | 6 |
| `tests/unit/test_rt_doctest.py` | Documentation | 1–5 | 10 |
| `tests/unit/test_rt_design_doc_examples.py` | Documentation | 1–5 | 7 |
| **Total** | | | **~270** |

---

### New Files

**Runtime modules** (all under `src/zuspec/dataclasses/`):

| File | Phase |
|---|---|
| `rt/debug_rt.py` | 1 |
| `rt/action_context.py` | 1 |
| `rt/pool_resolver.py` | 1–2 |
| `rt/activity_runner.py` | 1–5 |
| `rt/scenario_runner.py` | 1, 5 |
| `rt/resource_rt.py` | 2 |
| `rt/binding_solver.py` | 2 |
| `rt/expr_eval.py` | 3 |
| `rt/flow_obj_rt.py` | 4 |

**Test files** (all under `packages/zuspec-dataclasses/tests/unit/`):

| File | Tier | Phase |
|---|---|---|
| `conftest.py` | Infrastructure | 1 |
| `test_activity_parser_loc.py` | Unit | 1 |
| `test_rt_debug.py` | Unit | 1 |
| `test_rt_action_context.py` | Unit | 1 |
| `test_rt_pool_resolver.py` | Unit | 1–2 |
| `test_rt_runner_sequential.py` | Unit | 1 |
| `test_rt_runner_traversal.py` | Unit | 1 |
| `test_rt_scenario_runner.py` | Unit | 1 |
| `test_rt_regression_action_call.py` | Regression | 1 |
| `test_rt_resource.py` | Unit | 2 |
| `test_rt_binding_solver.py` | Unit | 2 |
| `test_rt_runner_parallel.py` | Unit | 2 |
| `test_rt_decorators.py` | Unit | 2 |
| `test_rt_expr_eval.py` | Unit | 3 |
| `test_rt_runner_control_flow.py` | Unit | 3 |
| `test_rt_flow_objects.py` | Unit | 4 |
| `test_rt_schedule_graph.py` | Unit | 4 |
| `test_rt_runner_flow.py` | Unit | 4 |
| `test_rt_tracer.py` | Unit | 5 |
| `test_rt_runner_extensions.py` | Unit | 5 |
| `test_rt_e2e_dma.py` | Integration | 1–2 |
| `test_rt_e2e_pipeline.py` | Integration | 2–4 |
| `test_rt_e2e_nested_parallel.py` | Integration | 2 |
| `test_rt_e2e_control_flow_compound.py` | Integration | 2–4 |
| `test_rt_doctest.py` | Documentation | 1–5 |
| `test_rt_design_doc_examples.py` | Documentation | 1–5 |

### Modified Files

| File | Change | Phase |
|---|---|---|
| `ir/activity.py` | Add `action_type_cls: Optional[type]` to `ActivityAnonTraversal` | 1 |
| `activity_parser.py` | Populate `loc` on all IR nodes; resolve `action_type_cls`; fix cache key | 1 |
| `types.py` | Replace `Action.__call__` body with `ActivityRunner._traverse` delegation | 1 |
| `decorators.py` | Implement `pool()` properly (currently a stub) | 2 |
| `rt/tracer.py` | Add 6 new activity-level trace event methods | 5 |
| `__init__.py` | Export `ScenarioRunner`, `run_action`, `run_action_sync`, `DeadlockError` | 1, 5 |

---

## Dependency Order

```
T1.1 (loc in parser)
T1.2 (action_type_cls)
T1.3 (debug_rt)
T1.4 (action_context)
T1.5 (pool_resolver Phase 1)     ← needs T1.4
T1.6 (activity_runner Phase 1)   ← needs T1.3, T1.4, T1.5
T1.7 (scenario_runner)           ← needs T1.6
T1.8 (Action.__call__ update)    ← needs T1.6
T1.9 (__init__ exports)          ← needs T1.7
T1.10 (Phase 1 tests)            ← needs T1.1–T1.9

T2.1 (pool decorator)
T2.2 (pool_resolver Phase 2)     ← needs T2.1
T2.3 (resource_rt)               ← needs T2.2
T2.4 (binding_solver)            ← needs T2.2, T2.3
T2.5 (runner Phase 2)            ← needs T2.3, T2.4
T2.6 (Phase 2 tests)             ← needs T2.1–T2.5

T3.1 (expr_eval)                 ← needs T1.6
T3.2 (control flow in runner)    ← needs T3.1
T3.3 (Phase 3 tests)             ← needs T3.2

T4.1 (flow_obj_rt)
T4.2 (ScheduleGraph in runner)   ← needs T4.1, T2.5
T4.3 (flow binding in traverse)  ← needs T4.1, T4.2
T4.4 (Phase 4 tests)             ← needs T4.1–T4.3

T5.1 (extend support)            ← needs T1.6, T2.5
T5.2 (ActivityConstraint)        ← needs T3.1
T5.3 (tracer hooks)              ← needs T1.6
T5.4 (watchdog)                  ← needs T1.7
T5.5 (Phase 5 tests)             ← needs T5.1–T5.4
```

---

## Open Questions (Resolve Before or During Implementation)

1. **`ExprEval` IR shape** — Inspect `ir/expr.py` to confirm the exact field
   names on `ExprBin` (is the op field named `op`? are operands `lhs`/`rhs`
   or `left`/`right`?), `ExprFieldRef` (path structure), and `ExprConstant`
   (value field name).  Adjust `ExprEval` accordingly.

2. **`pool_resolver.resolve_pool_by_type`** — `BindingSolver` calls this
   method, but Phase 1 `PoolResolver` does not have it.  Add it as part of
   T2.2 using the component tree pool index built by `_index_pools()`.

3. **`_flow_outputs` / `_flow_inputs` helpers** for `ScheduleGraph` — Need to
   inspect action type field metadata for `{"kind": "flow_ref",
   "direction": "output"|"input"}`.  Confirm this metadata is set correctly by
   the `output()` / `input()` decorators in `decorators.py`.

4. **Inline constraints in `_traverse`** — Phase 1 calls `randomize()` even
   when `inline_constraints` is non-empty.  Phase 3 should integrate
   `ExprEval`-evaluated constraints into `randomize_with()`.  The existing
   `randomize_with()` parses constraints from Python source AST.  Adding a
   lower-level `add_ir_constraint(expr_ir, action)` path to
   `RandomizeWithContext._randomize_with_constraints()` is needed.

5. **Parse cache invalidation** — T1.1 changes the cache key to include
   `(hash(source), src_file, start_lineno)`.  Verify that the `_parse_cache`
   module-level dict is cleared between test runs (currently it is a
   module-level dict; use `pytest` fixture `autouse` to clear it if needed).
