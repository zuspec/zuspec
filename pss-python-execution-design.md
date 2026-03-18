# Design: Pure-Python PSS Execution Runtime

Date: 2026-03-18
Status: Proposed — for review

---

## 1. Overview

### 1.1 Scope

This document designs a pure-Python PSS execution runtime for
`packages/zuspec-dataclasses`.  It targets the same semantic goals as
`pss-to-c-execution-design.md` but replaces the C frame-chain coroutine
scheduler with Python `asyncio` and the generated C solve functions with the
existing pure-Python constraint solver (`solver/api.py`).

The runtime sits entirely inside `packages/zuspec-dataclasses/src/zuspec/
dataclasses/rt/` as new modules alongside the existing channel, register,
memory, and clock runtime pieces.

### 1.2 What Already Exists

| Component | File | Status |
|---|---|---|
| Activity IR nodes | `ir/activity.py` | Complete (Phases 1–4) |
| `ActivityParser` | `activity_parser.py` | Complete |
| `Action.__call__` | `types.py` | Partial — comp binding, no solve |
| `ListClaimPool` | `rt/list_claim_pool.py` | Complete — lock/share/drop |
| Constraint solver | `solver/api.py` | Complete — `randomize()` |
| Component factory | `rt/obj_factory.py` | Complete |
| `Buffer`, `Stream`, `State`, `Resource` | `types.py` | Declared, no runtime |

### 1.3 What Is Missing

- `ActivityRunner` — walks activity IR and executes each node
- Solver integration in action traversal (call `randomize()` per action)
- Pool binding resolver (map resource/flow-object field → pool instance)
- Head-action coordinated solve for parallel blocks (AllDifferent)
- Flow-object runtime (`BufferInstance`, `StreamInstance`, `StatePool`)
- `ScenarioRunner` — user-facing entry point
- Component instance selection respecting `bind` directives

### 1.4 Design Philosophy

- **Asyncio as the concurrency model.** Python coroutines and
  `asyncio.gather()` / `asyncio.TaskGroup` replace the C frame-chain
  scheduler.  No custom scheduler is needed.
- **Per-action solving.** Each action traversal calls `randomize()` on the
  action instance after `pre_solve()` and before `post_solve()`.  No
  monolithic scenario solve.
- **Cooperative resource blocking.** Resource claims use `asyncio.Event`
  (already in `ListClaimPool`) for blocking, exactly analogous to the C
  waiter-list mechanism.
- **Head-action coordination for parallel.** Before spawning parallel
  branches, the runtime solves resource assignments for each branch's first
  action together, using the existing `uniqueness` / AllDifferent propagator
  so no two branches start holding the same resource instance.
- **Interpreted IR, not code generation.** The activity IR on
  `cls.__activity__` is walked at runtime by `ActivityRunner`.  There is no
  code-generation step.

---

## 2. Execution Model

### 2.1 Action Traversal Lifecycle

Every action traversal — whether from `ActivityTraversal` (`self.handle()`)
or `ActivityAnonTraversal` (`do(Type)`) — executes this sequence:

```
1. Instantiate action type (already exists as a handle or created on-the-fly)
2. Resolve component assignment (comp field)
3. Call action.pre_solve()
4. Randomize rand fields: randomize(action_instance)
   – Inline constraints from the with-block are added here
5. Call action.post_solve()
6. Acquire resource locks/shares (may block)
7. Call action.body()  — if atomic
   OR recurse into ActivityRunner(action.__activity__, action)  — if compound
8. Release resource locks/shares (LIFO order)
```

This matches the LRM (Section 12.3.1) traversal order and the C design's
per-step solve philosophy.

### 2.2 Asyncio Concurrency Map

| PSS Construct | Python asyncio equivalent |
|---|---|
| Sequential block | `for stmt in stmts: await execute(stmt)` |
| Parallel block | `asyncio.gather(*branch_coros)` |
| Schedule block | topological sort on flow/resource deps → `asyncio.gather()` |
| Atomic block | wrap in `asyncio.Lock` to prevent interleaving |
| do_while / while_do | `while` loop with `await execute(body)` |
| Repeat | `for i in range(count): await execute(body)` |
| Foreach | `for item in collection: await execute(body)` |
| Replicate | expand N copies in-place per enclosing block semantics |
| Select/Branch | weighted random choice → `await execute(chosen_branch)` |
| Resource lock | `await claim_pool.lock(filter=...)` (existing) |
| Resource share | `await claim_pool.share(filter=...)` (existing) |
| Buffer produce/consume | `asyncio.Future` set by producer, awaited by consumer |
| Stream produce/consume | `asyncio.Queue(maxsize=1)` shared between branches |
| State read/write | `asyncio.Lock` for writers; readers share freely |

---

## 3. New Modules

All new modules live in `src/zuspec/dataclasses/rt/`:

```
rt/
  activity_runner.py     # Core IR walker + execution engine
  action_context.py      # Execution context for one action traversal
  pool_resolver.py       # Maps resource/flow fields to pool instances
  flow_obj_rt.py         # Buffer, Stream, State runtime objects
  binding_solver.py      # Head-action AllDifferent solver for parallel
  scenario_runner.py     # User-facing entry point
  debug_rt.py            # _fire_line_event() and debugger helpers
```

---

## 4. `ActionContext` — Execution Context

Each action traversal runs inside an `ActionContext`.  It carries everything
the `ActivityRunner` needs without threading it through every function call.

```python
@dataclass
class ActionContext:
    action: Any                      # the action instance
    comp: Component                  # assigned component instance
    pool_resolver: PoolResolver      # resolves field → pool
    parent: Optional[ActionContext]  # enclosing traversal (for super())
    seed: int                        # RNG seed for this traversal
    inline_constraints: list         # extra constraints from with-blocks
    flow_bindings: dict              # field_name → FlowObjInstance
```

`ActionContext` is created by `ActivityRunner._traverse()` before each action
traversal and discarded when the traversal completes.

---

## 5. `ActivityRunner` — IR Walker

`ActivityRunner` is the core execution engine.  It takes an
`ActivitySequenceBlock` (or any `ActivityStmt`) and an `ActionContext`, and
executes the tree recursively.

### 5.1 Class Sketch

```python
class ActivityRunner:
    async def run(self, block: ActivitySequenceBlock,
                  ctx: ActionContext) -> None:
        for stmt in block.stmts:
            await self._exec(stmt, ctx)

    async def _exec(self, stmt: ActivityStmt, ctx: ActionContext) -> None:
        match type(stmt):
            case ActivitySequenceBlock: await self._seq(stmt, ctx)
            case ActivityTraversal:     await self._traverse_handle(stmt, ctx)
            case ActivityAnonTraversal: await self._traverse_anon(stmt, ctx)
            case ActivityParallel:      await self._parallel(stmt, ctx)
            case ActivitySchedule:      await self._schedule(stmt, ctx)
            case ActivityAtomic:        await self._atomic(stmt, ctx)
            case ActivityRepeat:        await self._repeat(stmt, ctx)
            case ActivityDoWhile:       await self._do_while(stmt, ctx)
            case ActivityWhileDo:       await self._while_do(stmt, ctx)
            case ActivityForeach:       await self._foreach(stmt, ctx)
            case ActivityReplicate:     await self._replicate(stmt, ctx)
            case ActivitySelect:        await self._select(stmt, ctx)
            case ActivityIfElse:        await self._if_else(stmt, ctx)
            case ActivityMatch:         await self._match(stmt, ctx)
            case ActivityConstraint:    await self._constraint(stmt, ctx)
            case ActivityBind:          await self._bind(stmt, ctx)
            case ActivitySuper:         await self._super(stmt, ctx)
            case _:
                raise RuntimeError(f"Unknown activity node: {type(stmt)}")
```

### 5.2 Action Traversal

```python
async def _traverse(self, action_type: type,
                    inline_constraints: list,
                    ctx: ActionContext,
                    label: Optional[str] = None) -> Any:
    # 1. Instantiate
    action = action_type.__new__(action_type)
    action.__init__()   # default-initializes all fields

    # 2. Assign component context
    action.comp = ctx.pool_resolver.select_comp(action_type, ctx.comp)

    # 3. pre_solve
    action.pre_solve()

    # 4. Randomize (solver integration)
    if inline_constraints:
        with randomize_with(action) as rw:
            for c in inline_constraints:
                rw._add_inline_constraints(c)
    else:
        randomize(action)

    # 5. post_solve
    action.post_solve()

    # 6. Build child context
    child_ctx = ActionContext(
        action=action,
        comp=action.comp,
        pool_resolver=ctx.pool_resolver,
        parent=ctx,
        seed=ctx.seed ^ id(action),
        inline_constraints=[],
        flow_bindings={},
    )

    # 7. Acquire resources (sorted by pool_id, instance_id for deadlock freedom)
    claims = await self._acquire_resources(action, child_ctx)

    try:
        # 8a. Atomic: call body()
        if hasattr(type(action), '__atomic__') or not hasattr(type(action), '__activity__'):
            await action.body()
        # 8b. Compound: recurse into sub-activity
        else:
            await ActivityRunner().run(type(action).__activity__, child_ctx)
    finally:
        # 9. Release resources in reverse order
        await self._release_resources(claims, child_ctx)
```

`_traverse_handle` resolves the handle name from `ctx.action` (e.g.
`self.a1`) and calls `_traverse` with the handle's type.
`_traverse_anon` creates a fresh instance of the anonymous type.

### 5.3 Parallel Block

Parallel is the most complex construct because head actions on concurrent
branches must be pre-solved to guarantee distinct resource assignments.

```python
async def _parallel(self, node: ActivityParallel, ctx: ActionContext) -> None:
    # Phase 1: Solve head-action resource assignments across all branches
    head_assignments = await BindingSolver().solve_heads(node.stmts, ctx)

    # Phase 2: Build per-branch coroutines
    async def run_branch(stmt, head_assign):
        branch_ctx = ActionContext(..., head_resource_hints=head_assign)
        await self._exec(stmt, branch_ctx)

    coros = [
        run_branch(stmt, head_assignments[i])
        for i, stmt in enumerate(node.stmts)
    ]

    # Phase 3: Launch and join per JoinSpec
    await self._gather_with_join(coros, node.join_spec)
```

`_gather_with_join` wraps `asyncio.gather()` with the appropriate join
semantics (see Section 7).

### 5.4 Schedule Block

A schedule block executes all branches in any order that satisfies
flow-object and resource constraints.

```python
async def _schedule(self, node: ActivitySchedule, ctx: ActionContext) -> None:
    # Build a dependency graph from flow-object producer/consumer edges
    graph = ScheduleGraph.build(node.stmts, ctx)
    # Topological sort, run stages in parallel
    for stage in graph.stages():
        await asyncio.gather(*(self._exec(stmt, ctx) for stmt in stage))
```

`ScheduleGraph` analyses each statement's input/output flow-object fields to
determine which must complete before others start.  Statements with no
dependency on each other form a parallel stage.

### 5.5 Atomic Block

```python
async def _atomic(self, node: ActivityAtomic, ctx: ActionContext) -> None:
    async with ctx.pool_resolver.atomic_lock:
        for stmt in node.stmts:
            await self._exec(stmt, ctx)
```

A single per-component-tree `asyncio.Lock` prevents any other coroutine from
being scheduled (since asyncio is cooperative, holding the lock without
yielding achieves atomicity; `asyncio.Lock` ensures that any yield inside the
atomic block blocks other tasks from entering).

### 5.6 Select / Branch

```python
async def _select(self, node: ActivitySelect, ctx: ActionContext) -> None:
    # Filter branches by guard condition
    eligible = [
        b for b in node.branches
        if b.guard is None or ExprEval(ctx).eval(b.guard)
    ]
    if not eligible:
        raise RuntimeError("select: no eligible branch")

    # Weighted random selection
    weights = [ExprEval(ctx).eval(b.weight) if b.weight else 1
               for b in eligible]
    chosen = random.choices(eligible, weights=weights, k=1)[0]

    await self._exec(chosen.body, ctx)
```

---

## 6. `PoolResolver` — Binding Resolution

`PoolResolver` is constructed once per component-tree root.  It answers two
questions at runtime:

1. Given an action type and a candidate component, which pools are bound to
   each resource/flow-object field?
2. Which component instances are candidates for a given action type?

### 6.1 Bind Topology Construction

At `ScenarioRunner` init time, `PoolResolver.build(root_comp)` traverses the
component tree and collects all `@bind` declarations.  Each bind entry maps:

```
(component_instance, action_type, field_name)  →  pool_instance
```

The resolution precedence follows the LRM (Section 15.3):
1. Explicit bind on the nearest-ancestor component wins over a wildcard bind.
2. Wildcard (`*`) bind propagates to all matching action types in the subtree.

```python
class PoolResolver:
    def build(self, root: Component) -> None:
        self._explicit: dict = {}   # (comp_id, action_cls, field) → pool
        self._wildcard: dict = {}   # (comp_id, field_type) → pool
        self._comp_instances: dict  # action_cls → List[Component]
        self._walk(root)

    def resolve_pool(self, action: Any, field_name: str) -> ClaimPool | BufferPool | ...:
        """Return the pool bound to action.field_name given action.comp."""
        ...

    def select_comp(self, action_type: type,
                    context_comp: Component) -> Component:
        """Randomly select a component instance of the correct type
        from within context_comp's subtree."""
        candidates = self._comp_instances.get(action_type, [])
        if not candidates:
            raise RuntimeError(...)
        return random.choice(candidates)
```

### 6.2 Resource Acquisition

`ActivityRunner._acquire_resources()` enumerates the action's `resource_ref`
fields, resolves each to a pool, and acquires the claim:

```python
async def _acquire_resources(self, action, ctx) -> list[Claim]:
    claims = []
    # Collect (pool_id, instance_id, claim_mode) tuples, sort for deadlock freedom
    resource_fields = _get_resource_fields(type(action))
    resource_fields.sort(key=lambda f: id(ctx.pool_resolver.resolve_pool(action, f.name)))

    for field_info in resource_fields:
        pool = ctx.pool_resolver.resolve_pool(action, field_info.name)
        instance_id = getattr(action, field_info.name + '.instance_id', None)

        if field_info.claim == 'lock':
            claim = await pool.lock(
                claim_id=instance_id,
                filter=lambda r, i: i == instance_id if instance_id is not None else True
            )
        else:  # share
            claim = await pool.share(claim_id=instance_id)

        # Write solved resource object back onto the action field
        setattr(action, field_info.name, claim.t)
        claims.append((pool, claim))

    return claims
```

The **solver already assigns `instance_id`** during `randomize(action)` using
the domain constraints on the resource field.  `_acquire_resources` then
acquires the specific instance the solver chose.  If that instance is already
held (by a concurrent branch), the `ListClaimPool.lock()` blocks — this is
the tail-action runtime arbitration path.

---

## 7. Join Semantics

`_gather_with_join` implements the four join variants using standard asyncio
primitives:

```python
async def _gather_with_join(self, coros, join_spec: Optional[JoinSpec]) -> None:
    if join_spec is None or join_spec.kind == 'all':
        # Default: wait for all branches
        await asyncio.gather(*coros)

    elif join_spec.kind == 'none':
        # Fire-and-forget: schedule all, don't wait
        for coro in coros:
            asyncio.create_task(coro)

    elif join_spec.kind == 'first':
        n = join_spec.count
        tasks = [asyncio.create_task(c) for c in coros]
        done_count = 0
        pending = set(tasks)
        while done_count < n:
            done, pending = await asyncio.wait(
                pending, return_when=asyncio.FIRST_COMPLETED)
            done_count += len(done)
        # Remaining tasks continue independently

    elif join_spec.kind == 'branch':
        # Wait only for tasks corresponding to labeled branches
        labeled, unlabeled = _split_by_label(coros, join_spec.branch_label)
        for coro in unlabeled:
            asyncio.create_task(coro)
        await asyncio.gather(*labeled)

    elif join_spec.kind == 'select':
        n = join_spec.count
        all_tasks = [asyncio.create_task(c) for c in coros]
        chosen = random.sample(all_tasks, k=n)
        remaining = [t for t in all_tasks if t not in chosen]
        for t in remaining:
            asyncio.create_task(t)   # let them run freely
        await asyncio.gather(*chosen)
```

---

## 8. `BindingSolver` — Head-Action AllDifferent

When entering a `parallel` block, each branch's first traversal is a "head
action".  To guarantee no two branches start with the same resource instance,
the runtime solves their resource fields jointly before spawning any branches.

### 8.1 Problem Formulation

For a parallel block with N branches, each having a first action of type
`T_i` with resource fields `{f_ij}`:

1. Instantiate all N head actions (without binding `comp` yet).
2. For each resource field, compute the feasible `instance_id` domain
   (intersection of the pool size and any explicit domain constraints).
3. Use the solver's existing `uniqueness` propagator to assign distinct
   `instance_id` values across all lock fields that draw from the same pool.
4. Write the assigned `instance_id` values back onto the head action instances.

### 8.2 Implementation

```python
class BindingSolver:
    async def solve_heads(
            self,
            branch_stmts: list[ActivityStmt],
            ctx: ActionContext) -> list[dict]:
        """
        Returns one dict per branch: {field_name: instance_id}
        with AllDifferent satisfied across lock fields in the same pool.
        """
        head_actions = [_instantiate_head(s, ctx) for s in branch_stmts]

        # Group by pool, build joint constraint system
        pool_groups = _group_by_pool(head_actions, ctx.pool_resolver)

        for pool, entries in pool_groups.items():
            if not any(e.claim == 'lock' for e in entries):
                continue  # no uniqueness needed for share-only groups

            # Use solver's uniqueness propagator
            _solve_alldiff(entries, pool)

        return [{f.name: getattr(a, f.name + '.instance_id')
                 for f in _get_resource_fields(type(a))}
                for a in head_actions]
```

`_solve_alldiff` builds a small `ConstraintSystem` with one integer variable
per lock claim (domain = pool feasible set after constraint propagation) and
adds a `UniquenessConstraint` across them.  It then calls the existing solver
backtracking engine to assign values.

For the common case of 2–4 branches with small pool sizes, this solve is
trivial (microseconds).  For the pad_configuration scale (26 claims, 60
instances), the solver's `UniquenessConstraint` propagator (Regin-style
matching) handles it efficiently.

---

## 9. Flow Object Runtime

### 9.1 `BufferInstance`

```python
@dataclass
class BufferInstance:
    obj: Buffer
    _ready: asyncio.Future = field(default_factory=asyncio.get_event_loop().create_future)

    def set_ready(self):
        """Called by the producing action on body() completion."""
        if not self._ready.done():
            self._ready.set_result(self.obj)

    async def wait_ready(self) -> Buffer:
        """Called by consuming actions; blocks until producer completes."""
        return await self._ready
```

The activity executor creates one `BufferInstance` per `output()` field when
elaborating a schedule block.  Consuming actions receive the `BufferInstance`
via the `flow_bindings` dict in their `ActionContext`.

### 9.2 `StreamInstance`

```python
@dataclass
class StreamInstance:
    _queue: asyncio.Queue = field(default_factory=lambda: asyncio.Queue(maxsize=1))

    async def put(self, obj: Stream):
        await self._queue.put(obj)

    async def get(self) -> Stream:
        return await self._queue.get()
```

Producer and consumer are launched as parallel branches (by the schedule
block or an explicit parallel block).  The `StreamInstance` is created once
and passed to both branches via `flow_bindings`.

### 9.3 `StatePool`

```python
@dataclass
class StatePool:
    current: Optional[State]
    _initial: bool = True
    _writer_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    _reader_count: int = 0
    _no_readers: asyncio.Event = field(default_factory=asyncio.Event)

    async def write_acquire(self):
        async with self._writer_lock:
            while self._reader_count > 0:
                await self._no_readers.wait()

    def write_release(self, new_state: State):
        self.current = new_state
        self._initial = False

    async def read_acquire(self) -> State:
        # Multiple concurrent readers allowed; writer excluded
        self._reader_count += 1
        return self.current

    def read_release(self):
        self._reader_count -= 1
        if self._reader_count == 0:
            self._no_readers.set()
            self._no_readers.clear()
```

### 9.4 Flow Binding Resolution

`PoolResolver` also resolves flow-object bindings.  When the runner
encounters a schedule block with producer/consumer relationships, it:
1. Identifies `output()` / `input()` fields on each traversal's action type.
2. Creates `BufferInstance` / `StreamInstance` / `StatePool` objects.
3. Injects them into each branch's `ActionContext.flow_bindings`.

The activity executor passes the right object to each action via
`action.<field_name> = flow_bindings[field_name].obj` after solving.

---

## 10. `ScenarioRunner` — User-Facing API

### 10.1 Entry Points

Users interact with two functions:

```python
async def run_action(
        comp: Component,
        action_type: type,
        seed: Optional[int] = None,
        **kwargs) -> None:
    """
    Run one PSS action traversal on a component tree.

    Args:
        comp:        Root component instance (built by ObjFactory).
        action_type: The action class to traverse (must be associated
                     with a component type in comp's subtree).
        seed:        Random seed for reproducibility.  If None, a
                     random seed is generated.
        **kwargs:    Additional inline constraints applied to the
                     root action (same semantics as randomize_with).
    """
    ...


class ScenarioRunner:
    """
    Stateful runner for multi-action scenarios.  Maintains RNG state,
    coverage collectors, and an optional tracer across calls.
    """
    def __init__(self, comp: Component, seed: Optional[int] = None):
        self._comp = comp
        self._resolver = PoolResolver.build(comp)
        self._seed = seed or random.randrange(2**32)
        self._tracer: Optional[Tracer] = None

    async def run(self, action_type: type, **kwargs) -> None:
        """Traverse action_type once, advancing the internal RNG state."""
        ...

    async def run_n(self, action_type: type, n: int, **kwargs) -> None:
        """Traverse action_type n times sequentially."""
        for _ in range(n):
            await self.run(action_type, **kwargs)

    def attach_tracer(self, tracer: Tracer) -> None:
        self._tracer = tracer
```

### 10.2 Usage Example

```python
import asyncio
import zuspec.dataclasses as zdc
from zuspec.dataclasses.rt.scenario_runner import ScenarioRunner
from zuspec.dataclasses.rt.obj_factory import ObjFactory

# -- Model definition -------------------------------------------------
@zdc.dataclass
class DmaChannel(zdc.Resource):
    priority: zdc.u4 = zdc.rand()

@zdc.dataclass
class DmaComponent(zdc.Component):
    channels: zdc.ClaimPool[DmaChannel] = zdc.field(
        default_factory=lambda: zdc.ClaimPool.fromList([
            DmaChannel(priority=0),
            DmaChannel(priority=0),
        ])
    )

@zdc.dataclass
class DmaXfer(zdc.Action[DmaComponent]):
    chan: DmaChannel = zdc.lock()
    src_addr: zdc.u32 = zdc.rand()
    length:   zdc.u16 = zdc.rand(domain=(1, 4096))

    async def body(self):
        print(f"DMA: chan={self.chan.instance_id} src={self.src_addr:#x} len={self.length}")

@zdc.dataclass
class ParXfer(zdc.Action[DmaComponent]):
    xfer_a: DmaXfer
    xfer_b: DmaXfer

    async def activity(self):
        with zdc.parallel():
            self.xfer_a()
            self.xfer_b()

@zdc.dataclass
class Top(zdc.Component):
    dma: DmaComponent

# -- Running ----------------------------------------------------------
async def main():
    top = ObjFactory.inst().mkComponent(Top)
    runner = ScenarioRunner(top, seed=42)
    await runner.run(ParXfer)

asyncio.run(main())
```

### 10.3 Synchronous Convenience Wrapper

For test frameworks that are not async-native:

```python
def run_action_sync(
        comp: Component,
        action_type: type,
        seed: Optional[int] = None,
        **kwargs) -> None:
    asyncio.run(run_action(comp, action_type, seed=seed, **kwargs))
```

---

## 11. Component Assignment

### 11.1 comp Field Selection

When `ActivityRunner._traverse()` needs to assign `action.comp`:

1. Determine the action's component type `T` from `Action[T]` type parameter.
2. Call `PoolResolver.select_comp(action_type, context_comp)` which returns a
   randomly chosen instance of `T` from `context_comp`'s subtree.
3. If the action carries a `with`-block constraint on `comp` (e.g.
   `do(VideoAction) with { comp == self.comp.pipeA }`), the `inline_constraints`
   list carries this as an IR expression; `select_comp` evaluates and filters.

### 11.2 Subtree Search

`PoolResolver._walk()` builds `_comp_instances: dict[type, list[Component]]`
by doing a depth-first traversal of the component tree at construction time.
`select_comp` filters by type and calls `random.choice()`.

For constrained comp selection (when an inline `comp ==` constraint is
present), `select_comp` filters the candidate list before sampling.

---

## 12. Constraint Solving Integration

### 12.1 Per-Action Solve

`ActivityRunner._traverse()` calls `randomize(action)` between `pre_solve()`
and `post_solve()`.  This invokes the full solver pipeline:

```
ConstraintSystemBuilder → PropagationEngine → BacktrackingSearch
```

The solver randomizes all `@rand` fields (including `instance_id` on resource
fields) subject to all `@constraint` methods on the action class.

### 12.2 Inline Constraints from with-Blocks

When the activity has `with self.h(): assert self.h.length < 100`, the parsed
`inline_constraints` list on the `ActivityTraversal` node contains the
constraint IR.  `ActivityRunner._traverse()` feeds these into
`randomize_with()`:

```python
if node.inline_constraints:
    with randomize_with(action) as _:
        for c_expr in node.inline_constraints:
            _.add_ir_constraint(c_expr, action)
else:
    randomize(action)
```

### 12.3 Resource Instance_id Domain

Resource fields declared with `lock()` or `share()` carry `instance_id` as a
`@rand` field (from `Resource` base class).  The pool size provides the
domain maximum.  `PoolResolver` injects the domain bound into the action's
constraint system before solving:

```python
pool = ctx.pool_resolver.resolve_pool(action, field_name)
pool_size = len(pool.resources)
# Inject: field_name.instance_id in [0, pool_size-1]
```

This integrates with the existing `@constraint` machinery so the user can
further constrain which resource instance is selected:

```python
@zdc.dataclass
class SpiMaster(zdc.Action[PadComponent]):
    clock_pad: Pad = zdc.lock()

    @zdc.constraint
    def clock_constraint(self):
        return self.clock_pad.role == PadRole.CLOCK
```

The solver assigns an `instance_id` such that the resource at that index
satisfies the role constraint.

---

## 13. Deadlock Prevention

### 13.1 Canonical Lock Ordering

`_acquire_resources()` sorts all resource claims by a canonical key before
acquiring:

```python
resource_fields.sort(key=lambda f: (
    id(ctx.pool_resolver.resolve_pool(action, f.name)),  # pool identity
    getattr(action, f.name + '.instance_id', 0)          # instance_id
))
```

All actions acquire in the same global order ⇒ no circular wait.

### 13.2 Deadlock Detection

`ScenarioRunner` runs a watchdog coroutine that fires after a configurable
timeout (default 30 s).  If all active tasks are blocked on resource
acquisition or flow-object events, it raises `DeadlockError` with a dump of
which tasks are blocked on which resources.

```python
async def _watchdog(self, timeout_s: float):
    await asyncio.sleep(timeout_s)
    blocked = [t for t in asyncio.all_tasks() if t._is_blocked_on_resource]
    if blocked and len(blocked) == len(asyncio.all_tasks()) - 1:
        raise DeadlockError(f"Deadlock: {len(blocked)} tasks blocked")
```

---

## 14. Tracing

`ActivityRunner` calls the optional `Tracer` at key points:

| Event | Tracer call |
|---|---|
| Action traversal begins | `tracer.action_start(action_type, comp, seed)` |
| Rand fields solved | `tracer.action_solved(action, fields)` |
| Body/activity begins | `tracer.action_exec_begin(action)` |
| Body/activity ends | `tracer.action_exec_end(action)` |
| Resource acquired | `tracer.resource_lock(pool, instance_id)` |
| Resource released | `tracer.resource_unlock(pool, instance_id)` |

The existing `Tracer` base class in `rt/tracer.py` is extended with these new
event methods (default implementations are no-ops so existing tracers are
unaffected).

---

## 15. Debugger Integration

Users write PSS activities as ordinary Python source files.  The goal is that
a user can set a breakpoint on any line inside `async def activity(self)` in
their IDE (VS Code + debugpy, PyCharm, pdb, ipdb — any `sys.settrace`-based
debugger) and have execution pause there when `ActivityRunner` processes the
corresponding IR node.

### 15.1 The Problem

`ActivityRunner` executes IR nodes, not the original Python coroutine.  Its
own stack frames point at `activity_runner.py`, not the user's source file.
A debugger watching `sys.settrace` line events sees only runner internals and
never pauses at the user's `self.a1()` or `with parallel():` lines.

### 15.2 Mechanism: Compiled Stub at Source Location

The solution is to `exec` a minimal AST stub that is compiled with the
**original filename and line number** stored in the IR node.  This creates a
real CPython frame at the user's source location.  Any active `sys.settrace`
debugger fires a `line` event there, checks its breakpoint table, and pauses
if a breakpoint is set — exactly as if the interpreter had reached that line
normally.

```python
import ast
import sys

def _fire_line_event(filename: str, lineno: int, local_vars: dict) -> None:
    """
    Create a real Python frame at filename:lineno so that any sys.settrace
    debugger (pdb, debugpy/VS Code, PyCharm) sees a line event there.
    No-op when no debugger is attached.
    """
    if sys.gettrace() is None:
        return                      # fast path — zero overhead in production

    # Build `pass` AST node at the target line
    stmt = ast.Pass()
    stmt.lineno     = lineno
    stmt.col_offset = 0
    mod = ast.Module(body=[stmt], type_ignores=[])
    ast.fix_missing_locations(mod)
    code = compile(mod, filename, 'exec')

    # exec creates a real CPython frame at filename:lineno
    exec(code, local_vars)          # noqa: S102
```

Because `filename` points to the real `.py` file on disk, debuggers can
display the source without any `linecache` registration.

### 15.3 Source Location in IR Nodes

`ActivityParser` must store two additional attributes on every IR node it
creates:

```python
@dc.dataclass(kw_only=True)
class ActivityStmt(Base):
    src_file: str = ""   # absolute path from inspect.getsourcefile(method)
    src_line: int = 0    # AST node.lineno from the parsed activity method
```

In `ActivityParser.parse()`, before constructing each IR node:

```python
import inspect

def parse(self, method: Callable) -> ActivitySequenceBlock:
    self._src_file = inspect.getsourcefile(method) or ""
    # ... existing AST walk; pass src_file=self._src_file,
    #     src_line=ast_node.lineno to every IR node constructor
```

The source file is determined once per `parse()` call (same file for all
nodes in the same activity method).  Each IR node records its own `lineno`
from the Python AST, which is the line the user wrote.

### 15.4 Integration in `ActivityRunner`

`ActivityRunner._exec()` calls `_fire_line_event` as its first act for each
statement it dispatches:

```python
async def _exec(self, stmt: ActivityStmt, ctx: ActionContext) -> None:
    _fire_line_event(stmt.src_file, stmt.src_line, vars(ctx.action))

    match type(stmt):
        case ActivitySequenceBlock: await self._seq(stmt, ctx)
        ...
```

`local_vars` is passed as `vars(ctx.action)` so that the debugger's variable
inspector shows the current action's fields (rand values, comp, etc.) when
the user inspects locals at the breakpoint.

### 15.5 Step-Into Behaviour

When a user steps into an `ActivityTraversal` (`self.a1()`), the next line
event fires at the first statement inside the child action's `activity()`
body (or at the `body()` function itself for atomic actions).  This gives
natural step-into / step-over / step-out navigation across action boundaries.

### 15.6 Python Version Notes

| Python | Mechanism | Notes |
|---|---|---|
| 3.10 – 3.11 | `sys.settrace` (via compiled stub) | Fully supported |
| 3.12+ | `sys.settrace` (via compiled stub) | Also works; `sys.gettrace()` still valid |
| 3.12+ | `sys.monitoring` | Future enhancement: replace `sys.gettrace()` guard with `sys.monitoring.get_tool(sys.monitoring.DEBUGGER_ID)` for lower overhead |

The `sys.gettrace() is None` guard means the entire stub compilation and
`exec` is skipped in normal (non-debug) runs.  Debugger attach/detach is
handled transparently: if a debugger is attached mid-run, subsequent `_exec`
calls automatically begin firing events.

### 15.7 Interaction with `asyncio`

`asyncio` coroutines are traced individually; each `await` point potentially
suspends the trace.  `sys.settrace` is per-thread in CPython.  Since
`asyncio` runs on a single thread, all coroutines share the same trace
function.  The compiled stub approach is safe across `await` boundaries —
each `_exec` call independently re-fires the line event at the right source
location regardless of which coroutine is currently scheduled.

---

## 16. File and Class Summary

| New File | Key Classes / Functions |
|---|---|
| `rt/activity_runner.py` | `ActivityRunner`, `ScheduleGraph` |
| `rt/action_context.py` | `ActionContext` |
| `rt/pool_resolver.py` | `PoolResolver` |
| `rt/flow_obj_rt.py` | `BufferInstance`, `StreamInstance`, `StatePool` |
| `rt/binding_solver.py` | `BindingSolver` |
| `rt/scenario_runner.py` | `ScenarioRunner`, `run_action()`, `run_action_sync()` |
| `rt/debug_rt.py` | `_fire_line_event()` |

Changes to existing files:

| File | Change |
|---|---|
| `types.py` — `Action.__call__` | Replace with delegation to `ActivityRunner` |
| `types.py` — `Action.activity` | Keep as stub; runner uses `__activity__` IR |
| `ir/activity.py` — `ActivityStmt` | Add `src_file: str` and `src_line: int` fields |
| `activity_parser.py` — `ActivityParser.parse()` | Populate `src_file`/`src_line` on all IR nodes |
| `rt/tracer.py` | Add `action_start/solved/exec_begin/exec_end`, `resource_lock/unlock` |
| `__init__.py` | Export `ScenarioRunner`, `run_action`, `run_action_sync` |

---

## 17. Implementation Roadmap

### Phase 1 — Sequential Traversal + Solver Integration
- `ActionContext`
- `ActivityRunner._traverse()` with `randomize()` integration
- `ActivityRunner._seq()` for `ActivitySequenceBlock`
- `PoolResolver` component-instance selection (no bind directives yet)
- `ScenarioRunner.run()` for simple atomic actions
- `debug_rt.py` — `_fire_line_event()` stub
- `ActivityParser` — populate `src_file` / `src_line` on all IR nodes
- Tests: atomic actions, sequential compound actions, rand fields solved, breakpoint fires at correct source line

### Phase 2 — Parallel / Schedule + Resource Management
- `ActivityRunner._parallel()` with `asyncio.gather()`
- `ActivityRunner._schedule()` with `ScheduleGraph`
- `BindingSolver.solve_heads()` (AllDifferent via uniqueness propagator)
- `_acquire_resources()` / `_release_resources()` using `ListClaimPool`
- `PoolResolver` bind-directive traversal
- Tests: parallel DMA example, lock/share semantics, head-action uniqueness

### Phase 3 — Control Flow
- `_repeat`, `_do_while`, `_while_do`, `_foreach`, `_replicate`
- `_select` (weighted branch selection)
- `_if_else`, `_match`
- Tests: all control-flow constructs

### Phase 4 — Flow Objects
- `BufferInstance`, `StreamInstance`, `StatePool`
- Flow binding injection in `ActionContext.flow_bindings`
- `ScheduleGraph` flow-dependency analysis
- Tests: buffer producer/consumer, stream parallel exchange, state read/write

### Phase 5 — Extensions and Polish
- `@zdc.extend` support in `ActivityRunner._super()`
- `ActivityConstraint` (scheduling constraint blocks)
- `ActivityBind` (explicit flow-object bind statements)
- Deadlock watchdog
- Tracer hooks
- Synchronous `run_action_sync()` wrapper

---

## 18. Open Issues

1. **`randomize_with` IR injection** — The existing `randomize_with` parses
   inline constraints from Python source AST.  When inline constraints come
   from the activity IR (already parsed), a lower-level API is needed to add
   pre-parsed IR constraints directly to the constraint system.
   `_solve_constraint_system()` should accept an extra `ir_constraints` list.

2. **Variable-count replicate in parallel** — When `replicate(N)` appears
   inside a parallel block and `N` is a rand field, the head-action solve
   must first determine `N` before allocating branches.  Handle this by
   solving the outer action's `N` before entering the parallel solve.

3. **Cross-branch data constraints** — PSS allows constraints that span
   action handles in the same activity (e.g., `self.a.addr + self.a.len ==
   self.b.addr`).  These are not handled by per-action solving.
   For Phase 1–2, document this as unsupported; address in Phase 5 via
   a multi-action joint solve.

4. **`randc` across traversals** — If a resource field is `randc`, the
   `RandcManager` state must persist across `run()` calls on the same
   `ScenarioRunner`.  Pass the manager through `ActionContext`.

5. **Abstract action selection** — When an `ActivityAnonTraversal` targets an
   abstract action type, the runner must select a concrete subtype.  This
   requires a subtype registry; defer to Phase 5.

6. **`@zdc.extend` implied schedule** — Multiple extensions of the same
   action produce an implied `schedule` block.  The runner must collect all
   `@zdc.extend` subclasses of the target type and build a virtual
   `ActivitySchedule` IR node.  Design details deferred to Phase 5.
