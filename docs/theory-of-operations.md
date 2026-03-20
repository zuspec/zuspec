# Zuspec PSS Execution: Theory of Operations

## 1. The Problem with Monolithic Solving

The PSS Language Reference Manual (LRM) implicitly assumes a **single-solve
model**: the entire activity tree — all actions, their scheduling relationships,
resource assignments, data-flow bindings, and constraint systems — is resolved
as one unified problem before any execution begins.

This model is logically clean but practically limiting:

- The full scenario graph may not fit in memory on embedded targets.
- Solve time grows combinatorially as the number of concurrent actions
  increases.
- Embedded targets have no OS, no heap allocator, and restricted stack depth.
- Even on workstations, waiting for a monolithic solve before seeing any
  execution results hurts developer iteration speed.

Zuspec takes a different approach that produces **equivalent results** while
decomposing the hard global problem into a stream of small, local ones.

---

## 2. Core Insight: Per-Step Solving

Zuspec replaces the monolithic solve with a **per-action-traversal solve**.
Each time the runtime reaches an action, it:

1. Instantiates the action.
2. Assigns it a component instance.
3. Calls `pre_solve()`.
4. Solves only that action's randomized fields (subject to its own
   constraints).
5. Calls `post_solve()`.
6. Acquires required resources (may block cooperatively).
7. Executes the action body or recurses into its sub-activity.
8. Releases resources in reverse acquisition order.

This reduces the solve problem at any moment to **one action's constraints
plus a small resource-acquisition check**. Memory and compute costs are
bounded regardless of total scenario size.

### 2.1 LRM Conformance

Per-step solving is **fully conformant** with the LRM because the LRM defines
the required observable outcomes (solved values, execution ordering, resource
mutual exclusion) but does not mandate the mechanism. Zuspec satisfies all
those outcomes through:

- Correct solve per action.
- Deadlock-free resource management.
- Proper parallel-branch coordination at the one point where it matters.

The only scenario where per-step solving differs from monolithic solving is
**cross-action constraints that span unrelated sequential branches**. These are
an open item documented in the design and are not required by the core LRM.

---

## 3. The Three-Phase Execution Model

Because inference, binding, and data solving have very different computational
costs and timing requirements, Zuspec separates execution into three phases:

### Phase E — Elaboration (compile-time or scenario-init time)

Performed **once** before any action executes. On the C embedded target this
happens entirely at code-generation time; on the Python target it runs when
the `ScenarioRunner` or `ObjFactory` is constructed.

What is resolved here:

- **Pool binding tables**: For every `(component_instance, action_type,
  field_name)` triple, determine which pool instance applies following the
  LRM §15.3 precedence (explicit bind on nearest ancestor wins over wildcard).
- **ICL construction**: For each unbound flow-object slot on each action type,
  pre-compute the Inferencing Candidate List — the set of action types that
  could legally satisfy it (same pool, type-compatible, no structural
  contradiction).
- **Component subtree reachability**: Index which component instances are
  reachable for each action type.
- **Schedule block constraint graphs**: For each `schedule` block, build the
  sequential-edge graph (buffer/state/resource bindings) and concurrent-pair
  set (stream bindings); detect infeasibility (cycles, sequential/concurrent
  conflicts); emit a staged execution plan.
- **Abstract action type sets**: Enumerate concrete subtypes for each abstract
  action field.

### Phase S — Structural Solve (per top-level action traversal)

Performed **once per `run()` call**, before the first action executes.

What is resolved here:

- **Structural decisions**: For each unbound flow-object slot in the activity,
  select an element from its ICL (or confirm an existing explicitly-traversed
  action satisfies it).
- **Inference chain expansion**: Recursively apply ICL selection until no
  unbound slots remain (or the depth limit is reached).
- **Ordering insertion**: Inferred predecessors for buffer/state slots are
  inserted as sequential predecessors; inferred partners for stream slots are
  inserted as parallel peers.
- **Constraint-driven pruning**: ICL candidates whose type-level constraints
  are structurally incompatible with the rest of the scenario are eliminated
  before selection.

The output is a **fully-structured activity graph** — all action instances
exist, all flow-object slots are bound, and the ordering relationship of every
action is determined. On the C target this graph is encoded at code-generation
time; the embedded runtime never performs structural decisions.

### Phase A — Action-Execution / Data Solve (per-action)

Performed **once per action instance**, just before execution.

What is resolved here:

- **Per-action rand field randomization** (Section 11).
- **Flow-object data fields**: Constraints accumulated from the producer action
  are injected into the consumer's solve context.
- **Resource instance selection**: Choose which pool instance to acquire;
  head-action AllDifferent for parallel blocks (Section 6.1).
- **Inline constraint injection**: `with`-block constraints are added before
  the solve.
- **randc cycling**: Advance the cyclic-permutation state for each `randc`
  field.

Phase A is the inner loop of execution and must be fast. It is deliberately
kept small: one action's constraint system at a time.

---

## 4. Inference

### 4.1 What PSS Inference Means

The LRM (§5.3.2, §17) describes inference as the mechanism by which a tool
**completes a partially-specified activity**. An action may declare that it
needs a buffer input, a state input, or a stream partner, without explicitly
naming the action that provides it. The tool must deduce which action(s) to
insert and where to place them.

Three normative rules govern inference:

1. **Necessity**: Only infer what is required — directly or indirectly — to
   make the scenario legal.
2. **Completeness**: Inference chains continue until all unbound flow-object
   references are satisfied or the inferencing depth limit is exceeded.
3. **Constraint consistency**: Inferred actions that produce constraint
   contradictions are excluded; at least one valid solution must exist.

### 4.2 The Inferencing Candidate List Algorithm

For each unbound flow-object reference (LRM Annex E):

1. Identify the pool(s) of the appropriate type that the reference may bind to.
2. Find all already-traversed actions that could satisfy it (correct type,
   consistent data constraints, compatible scheduling relationship).
3. If none qualify, add an anonymous instance of every compatible action type
   to the ICL.
4. If the ICL is empty, report an error.
5. Recurse: for each newly added instance, apply steps 1–4 until fully bound
   or the depth limit is reached.

In practice, PSS models tend to have shallow inference chains (depth 1–3) and
small ICLs (2–5 candidates), so the search is fast.

### 4.3 Taxonomy of Inference Types

Inference divides into three orthogonal concerns:

**Structural inference** — *"Which action instances exist and how are they
ordered?"*

| Sub-type | Description |
|---|---|
| Buffer supply inference | Infer a sequential predecessor to supply an unbound buffer input |
| State supply inference | Infer a sequential predecessor to supply an unbound state input |
| Stream partner inference | Infer a parallel partner for an unbound stream in/out |
| Type-conversion inference | Infer an intermediate action to convert incompatible flow types |
| Multi-level chain inference | Transitively infer further actions whose own inputs are also unbound |
| Constraint-driven inference | Data constraints rule out existing ICL candidates, forcing new instances |

Structural inference is a **backtracking search over the type graph** (NP-hard
in general; tractable for typical shallow PSS models). It runs entirely in
Phase S on the solve platform; it is never performed on the embedded target.

**Binding inference** — *"Which pool instance does a field refer to?"*

| Sub-type | Description |
|---|---|
| Buffer/state pool binding | Assign a flow-object reference to a specific pool instance |
| Resource instance selection | Choose which resource instance (lock/share) an action claims |
| Component assignment | Choose which component instance an action executes in |
| Cross-component binding | Infer binding across component boundaries via default pool scope |

Binding inference for resource instances requires **bipartite matching /
AllDifferent** when multiple parallel branches compete for the same pool (see
Section 6). It runs in Phase A (per-action) for data-solve and Phase E
(elaboration) for pool binding tables.

**Data inference** — *"What values do rand fields take?"*

| Sub-type | Description |
|---|---|
| Single-action randomization | Solve rand fields of one action in isolation (Phase A) |
| Flow-object data constraints | Combine producer + consumer constraints on a shared flow object |
| Resource field constraints | Combine constraints from all actions sharing a resource object |
| Dynamic/inline constraints | `with`-block constraints added at traversal time |
| Cross-action sequential constraints | Constraints spanning multiple actions in a sequential chain |
| `randc` cycling | Random-cyclic fields that must not repeat until all values exhausted |

### 4.4 Complexity Categories

Different inference types require very different solver machinery:

| Category | Examples | Solver requirement |
|---|---|---|
| **1 — Trivial** | Non-rand fields; fully-determined rand fields | Direct computation; no solver |
| **2 — Simple** | Single-action rand fields; small resource pool selection; randc cycling | Bounds propagation (AC-3); pure-Python solver |
| **3 — Moderate** | Multi-field constraints; flow-object with N producers/consumers; abstract action selection | Full CSP with backtracking; constraint accumulation |
| **4 — Heavy** | Head-action AllDifferent; cross-action sequential constraints; compound resource constraints | Bipartite matching (Regin/Hopcroft-Karp); native solver |
| **5 — Complex** | Structural inference chains; constraint-driven ICL pruning; multi-level inference | ICL graph search with type-level CP; solve-platform only |

Category 5 is **never performed on the embedded target**. The C runtime
receives a structurally-complete execution plan from the code generator.

### 4.5 Flow-Object Constraint Accumulation

A key data structure required for Phases S and A is the
**`FlowObjectConstraintStore`**: when a producer action is solved, its
constraints on shared flow-object fields are stored, keyed by
`(pool_id, instance_id)`. When the consumer action is solved, those stored
constraints are injected into its constraint context, ensuring the consumer
sees values consistent with what the producer will write.

```
on producer action solve:
    store.add(pool_id, instance_id, producer.flow_out.constraints)

on consumer action solve (Phase A):
    inject store.get(pool_id, instance_id) into solver context
    solve consumer rand fields including flow input fields
```

For stream objects (producer and consumer run in parallel), both are solved
jointly in a shared solve context — neither can be solved independently.

### 4.6 Platform Boundary

Structural inference and the constraint graph analyses for schedule blocks are
**solve-platform concerns**:

- **Python runtime**: Phases E and S run on the host before the first action.
- **C embedded runtime**: Phases E and S run entirely on the build machine
  during code generation. The embedded target only ever executes Phase A.

---

## 5. Activity Execution as Concurrent Tasks

A PSS activity is a tree of control-flow constructs (`sequence`, `parallel`,
`schedule`, `repeat`, `select`, etc.) that organize action traversals. Zuspec
maps this tree to a set of cooperative concurrent tasks:

| PSS Construct | Runtime Mapping |
|---|---|
| Sequential block | Tasks executed one after another |
| Parallel block | N tasks launched concurrently; parent waits for join |
| Schedule block | Tasks with flow-object dependency ordering |
| do_while / while_do | Looping task |
| Repeat | Bounded loop task |
| Foreach | Iteration over a collection |
| Replicate | N copies in enclosing block context |
| Select / Branch | Weighted random choice of one branch task |
| Atomic block | All sub-tasks execute without interleaving |

Two backend implementations target different environments:

- **Python asyncio backend** (`zuspec-dataclasses`): for host-side simulation,
  testing, and prototyping. Concurrency via Python coroutines and
  `asyncio.gather()`.
- **C frame-chain backend** (`zuspec-be-sw`): for bare-metal embedded targets.
  Concurrency via the `zsp_timebase` stackless coroutine scheduler.

Both backends share the same conceptual model. The Python backend interprets
the activity IR at runtime; the C backend uses a code generator to produce
static C task functions.

---

## 6. The Parallel-Branch Coordination Problem

Sequential branches are trivially handled by per-step solving — each action is
solved when the branch reaches it. Parallel blocks require extra care.

Consider two parallel branches that both need to lock a resource from the same
pool. If each branch independently solves and then tries to acquire its
resource at runtime, both might choose the same instance. One branch would then
block waiting for the other to release — which the other never will if the
execution order is unfortunate, resulting in deadlock.

### 4.1 Head-Action Coordinated Solve

Zuspec solves this with a **head-action coordinated solve**:

> Before any parallel branch is allowed to run, all branches' **first (head)**
> actions are solved **jointly** using an AllDifferent constraint over their
> resource lock fields.

The algorithm:

1. Identify the first action on each branch.
2. Collect all `lock`-mode resource claims across all head actions.
3. For claims from the same pool, apply an AllDifferent (bipartite matching)
   constraint so each branch gets a distinct resource instance.
4. Write the solved instance IDs back onto the head action instances.
5. Spawn all branches. Head actions acquire their pre-assigned resources
   immediately (no blocking is possible; the assignment was guaranteed conflict-free).

This is the **only cross-branch coordination point** in the entire execution
model. All subsequent resource management is handled at runtime.

### 4.2 Tail-Action Runtime Arbitration

After the head action, subsequent actions on each branch acquire resources at
runtime:

1. The per-step solver assigns a desired resource instance ID.
2. The runtime attempts to acquire that instance.
3. If it is currently held by another branch, the branch yields (blocks
   cooperatively) and is placed on the resource pool's waiter list.
4. When the holding branch releases the resource, the waiter is woken and
   retries acquisition.

Because branches block cooperatively rather than spinning, there is no CPU
waste and no starvation risk (given fair scheduling).

---

## 7. Deadlock Prevention

Deadlock in resource acquisition requires a circular wait: branch A holds X
and waits for Y; branch B holds Y and waits for X.

Zuspec eliminates circular wait with **canonical lock ordering**:

> All resource claims within a single action are acquired in ascending order
> by `(pool_id, instance_id)`.

Because every action acquires in the same global order, no cycle can form.
This is the standard resource-ordering technique; it requires no runtime
overhead beyond the sort (done once per action).

In addition, both backends include a **deadlock detection** fallback:

- **Python backend**: A watchdog coroutine fires after a configurable timeout.
  If all active tasks are blocked on resource acquisition or flow-object events,
  it raises `DeadlockError` with a diagnostic dump.
- **C backend**: The scheduler run loop checks whether all threads are blocked
  with no pending timed events. If so, it calls `zsp_runtime_panic` with a
  `ZSP_PANIC_DEADLOCK` code.

---

## 8. Resource Management

### 6.1 Lock vs. Share

Resources support two claim modes:

- **Lock**: Exclusive. Only one action may hold the lock on a given resource
  instance at a time. Compatible with neither another lock nor any share on
  the same instance.
- **Share**: Non-exclusive. Multiple actions may share the same instance
  simultaneously, as long as no lock is held. A lock cannot be acquired
  while any share is active.

The runtime tracks per-instance `lock_held` flags and `share_count` reference
counts. Unlocking or unsharing wakes any waiting threads.

### 6.2 Resource Lifetime

A resource claim is held for the **entire duration of the action's execution**,
including the full traversal of any sub-activity. Release happens when the
action's frame is popped (i.e., the action fully completes). This matches the
LRM's resource-lifetime semantics.

### 6.3 Pool Binding Resolution

At initialization time, the component tree is traversed to collect all `bind`
declarations. Each bind entry maps `(component_instance, action_type,
field_name) → pool_instance`. The resolution precedence follows the LRM:

1. An explicit bind on the nearest-ancestor component wins over a wildcard.
2. A wildcard (`*`) bind propagates to all matching action types in the
   component subtree.

This resolved mapping is used at runtime whenever an action field needs to be
resolved to a concrete pool.

---

## 9. Data Flow Objects

PSS defines three categories of data-flow objects that carry information
between actions:

### 7.1 Buffers

A buffer is a **one-shot producer/consumer** object. The producer writes data
when its body completes. Any consumer(s) block until the producer has
completed. In schedule blocks, buffer dependencies drive the execution ordering
(actions that consume a buffer must run after the action that produces it).

- Python: `asyncio.Future` set by the producer, awaited by each consumer.
- C: A `valid` flag and a waiter thread pointer; the consumer blocks until
  the flag is set.

### 7.2 Streams

A stream is a **repeated producer/consumer** channel, used when producer and
consumer run concurrently (typically in parallel branches). The producer sends
values; the consumer receives them in order. Back-pressure is applied when the
channel is full.

- Python: `asyncio.Queue(maxsize=1)`.
- C: Same channel-style blocking as `zsp_channel_t`.

### 7.3 States

A state pool represents a **persistent piece of mutable state** (e.g., power
state, configuration register). It supports:

- Multiple concurrent readers (no lock required).
- A single exclusive writer (blocks all readers and other writers until done).

The `current`, `previous`, and `initial` fields track the state across
traversals.

---

## 10. Component Assignment

Each action type is parameterized by a component type. When an action is
traversed, the runtime selects a concrete component instance of that type from
within the enclosing component's subtree. Selection is random by default;
inline `comp ==` constraints can pin it to a specific instance.

Component instances are enumerated once at initialization by a depth-first
walk of the component tree and indexed by type for O(1) lookup at execution
time.

---

## 11. Constraint Solving

### 9.1 Per-Action Solve

Every action traversal invokes the solver on that action's `@rand` fields:

```
ConstraintSystemBuilder → PropagationEngine → BacktrackingSearch
```

All `@constraint` methods on the action class are collected and added to the
system. The solver assigns values that satisfy all constraints.

### 9.2 Inline Constraints from With-Blocks

When an activity traversal includes a `with`-block (e.g., `do(T) with {
self.length < 100 }`), the parsed constraint IR is added to the action's
constraint system before the solve. This is functionally equivalent to an
anonymous subclass with an additional constraint.

### 9.3 Resource Instance Domain

A resource field declared with `lock()` or `share()` carries an `instance_id`
as a randomized integer. The pool size provides the domain upper bound. The
solver assigns an `instance_id`; any further constraints on the resource's own
fields (e.g., `chan.priority > 2`) are propagated through the solve so that
only instances satisfying those constraints are considered.

### 9.4 Pre_solve / Post_solve

The solve lifecycle for each action is:

1. `pre_solve()` — user hook; may read external state to set up solve.
2. Constraint solve — assigns all `@rand` fields.
3. `post_solve()` — user hook; may read solved values and compute derived
   fields.

For parallel head actions, all `pre_solve()` calls run sequentially (one per
branch in order) before the coordinated head-action solve. This matches the
LRM's required ordering.

---

## 12. Concurrency Backends

### 10.1 Python asyncio Backend

The Python backend uses Python coroutines and `asyncio` for concurrency. The
activity IR (a tree of `ActivityStmt` nodes built by `ActivityParser`) is
walked at runtime by `ActivityRunner`. No code generation is involved.

Key components:

| Component | Role |
|---|---|
| `ActivityRunner` | Walks the activity IR tree; dispatches each node type |
| `ActionContext` | Carries execution context (action instance, comp, resolver, seed) |
| `PoolResolver` | Maps resource/flow fields to pool instances; selects comp |
| `BindingSolver` | Head-action AllDifferent solve for parallel blocks |
| `ScenarioRunner` | User-facing entry point; manages seed, tracer, run loops |
| `BufferInstance` / `StreamInstance` / `StatePool` | Flow-object runtime |

Concurrency map:

| PSS Construct | Python asyncio |
|---|---|
| Sequential block | `for stmt in stmts: await execute(stmt)` |
| Parallel block | `asyncio.gather(*branch_coros)` |
| Schedule block | Topological sort on flow deps → staged `asyncio.gather()` |
| Atomic block | `asyncio.Lock` held across the block |
| Resource lock | `await claim_pool.lock(...)` (may block) |
| Buffer produce | Set `asyncio.Future` |
| Buffer consume | `await future` |
| Stream exchange | `asyncio.Queue(maxsize=1)` |

### 10.2 C Frame-Chain Backend

The C backend targets bare-metal embedded systems via the `zsp_timebase`
stackless coroutine scheduler. A code generator emits static C source from the
PSS model; no runtime IR interpretation occurs.

Each compound action's activity maps to a **task function** with an `idx`
parameter that acts as a resume-point dispatcher:

```c
static zsp_frame_t *my_activity_task(
    zsp_timebase_t *tb, zsp_thread_t *thread, int idx, va_list *args)
{
    switch (idx) {
    case 0:   /* initial call: allocate frame, solve first action, yield */
    case 1:   /* resume: execute first action body, solve second, yield  */
    case 2:   /* resume: execute second action body, return              */
    }
}
```

- `idx == 0` with non-NULL `args`: initial call; allocate frame and extract
  arguments.
- `idx > 0` with NULL `args`: resume after a yield or unblock.
- **Yield** (`SUSPEND` flag): the scheduler re-enqueues the thread for the
  next run-loop pass.
- **Block** (`BLOCKED` flag): the thread is placed on a waiter list; it is
  not re-enqueued until the blocking condition (resource release, join
  completion, timed event) is resolved.

Parallel blocks spawn child threads via `zsp_timebase_thread_create`. The
parent blocks on a `zsp_join_t` until the required number of children complete.

New runtime primitives required by this model:

| Primitive | Purpose |
|---|---|
| `zsp_resource_pool_t` | Per-pool lock/share state and waiter lists |
| `zsp_join_t` | Parallel-block join synchronization |
| Deadlock detection | Scheduler panic when all threads are blocked and no timed events remain |

---

## 13. Join Semantics

The PSS `parallel` construct supports four join modes:

| Mode | Semantics |
|---|---|
| `join_all` (default) | Parent waits for every branch to complete |
| `join_none` | Parent continues immediately; branches run independently until the enclosing sequence boundary |
| `join_first(N)` | Parent waits for the first N branches to complete; remaining branches continue |
| `join_branch(label)` | Parent waits only for branches with the specified label |
| `join_select(N)` | N branches are randomly selected; parent waits for those N |

In the C backend, `zsp_join_t` tracks a `remaining` counter initialized to the
number of branches the parent is waiting for. Each relevant branch calls
`zsp_join_signal` on exit; when `remaining` reaches zero, the parent thread is
woken.

---

## 14. Schedule Blocks

A `schedule` block specifies that its branches may execute in any order that
satisfies their data-flow and resource dependencies. This is closely related
to inference: both are instances of the same underlying constraint-graph
problem applied to different action sets and at different phases.

| Aspect | Inference | Schedule block |
|---|---|---|
| Action set | Discovers which actions exist | Actions are explicitly listed |
| What is solved | Structural: which actions to add and where | Ordering: what execution order to impose |
| Buffer rule | Infer a sequential predecessor | Listed producer must complete before listed consumer |
| Stream rule | Infer a parallel partner | Listed producer and consumer must execute in parallel |
| Resource rule | Infer ordering to avoid conflicts | Impose ordering when pool too small for simultaneous claims |

### 14.1 Constraint Graph (Phase E)

During elaboration, each `schedule` block is analysed to produce a
**staged execution plan**:

**Sequential edges** (`A → B`, A must complete before B starts):
- Buffer bind `producer.out → consumer.in` (LRM §5.1.1)
- State bind `writer.out → reader.in` (LRM §13.3)
- Resource contention: two actions locking the same single-instance resource
- Explicit `constraint sequence(A, B)` (LRM §16.2)

**Concurrent edges** (`A ↔ B`, A and B must start simultaneously):
- Stream bind `producer.out_stream → consumer.in_stream` (LRM §5.1.2)
- Explicit `constraint parallel(A, B, ...)` (LRM §16.2)

Note: a buffer or state bind between two actions that are both in a `parallel`
block (not `schedule`) is **illegal** — it would require both sequential and
concurrent ordering simultaneously. This is detected and reported during
Phase E.

### 14.2 Constraint Graph Analysis Algorithm

1. **Build `G_seq`**: collect all sequential edges.
2. **Cycle detection** (DFS): a cycle in `G_seq` is an error.
3. **Build `S_con`**: collect all concurrent pairs.
4. **Sequential/concurrent conflict check**: compute the transitive closure of
   `G_seq`; for each concurrent pair `(A, B)`, verify neither is reachable
   from the other in `G_seq`. Violation is an error.
5. **Concurrent group formation** (Union-Find): merge all actions linked
   (directly or transitively) by concurrent edges into execution units. An
   execution unit is either a single action or a stream-linked concurrent group.
6. **Intra-group sequential check**: a sequential edge between two members of
   the same concurrent group is an error.
7. **Level assignment** (Kahn's topological sort on the unit DAG): assign each
   unit to a level; units at the same level may run concurrently.

Output: an ordered list of **stages**, where each stage is a set of execution
units that may start once all units from the previous stage have completed.

**Complexity**: O(V²/64) with bitset transitive closure for V ≤ 64 actions per
schedule block; adequate for typical PSS models.

### 14.3 Mutex Pairs (Resource Contention)

When two actions in a `schedule` block both lock the same single-instance
resource, a sequential ordering is required but the direction is
undetermined. Zuspec resolves these **at runtime** (Phase A): the first action
to successfully call `try_lock` proceeds; the other blocks and retries when the
resource is released. This matches the natural behaviour of the resource pool
and avoids the need to pick an order at elaboration time.

### 14.4 Interaction with Inference

When Phase S inference inserts new action instances into a schedule block, those
inferred actions bring new binding edges. Phase E constraint graph analysis is
re-run over the extended action set. The loop is:

```
loop:
    Phase E: analyse current action set → detect conflicts, compute stages
    Phase S: for each unbound flow-object slot:
                 select ICL candidate, add to action set with binding edges
    if no new actions added: break
emit staged execution plan
```

The loop terminates because each iteration adds at least one action or finds
no unbound slots.

### 14.5 Runtime Execution of Schedule Blocks

Given the staged execution plan from Phase E:

- **Python backend**: Each stage is executed as an `asyncio.gather()` call over
  its execution units. Within a concurrent group (stream partners), all members
  are gathered together. In-degree counters drive stage advancement: when all
  units in a stage complete, the next stage's units become ready.
- **C backend**: Treated as a parallel block; the cooperative scheduler and
  resource-pool blocking naturally produce a legal ordering. The C backend does
  not require explicit topological analysis because the coroutine scheduler's
  round-robin dispatch and blocking semantics are equivalent to the runtime
  resolution of undirected ordering constraints.

Both approaches satisfy the LRM requirement (any legal ordering is acceptable).
The Python backend may achieve higher concurrency through explicit stage
parallelism; the C backend trades this for implementation simplicity.

---

## 15. Debugger Integration (Python Backend)

Because `ActivityRunner` walks an IR tree rather than executing the original
Python coroutine, a standard debugger would not see the user's source lines.
Zuspec solves this via a **compiled stub at source location**:

For each IR node, `ActivityParser` records the original source file and line
number. Before dispatching each node, `ActivityRunner` calls
`_fire_line_event(filename, lineno, vars(action))`, which:

1. Checks whether a debugger is active (`sys.gettrace() is not None`). If not,
   returns immediately (zero overhead in production).
2. Compiles a minimal AST `pass` statement with `filename:lineno` as its
   location.
3. `exec`s that stub, creating a real CPython frame at the user's source
   location.
4. The debugger's `sys.settrace` handler fires a `line` event at that location
   and checks its breakpoint table.

The result is that users can set breakpoints on any line inside their `activity`
method and have execution pause there, with the action's current field values
visible in the variable inspector.

---

## 16. Correctness Summary

| Property | How it is guaranteed |
|---|---|
| Rand fields solved | Per-action `randomize()` call with full constraint system (Phase A) |
| Resource mutual exclusion | `lock_held` / `share_count` per-instance tracking |
| No two concurrent lock holders | Head-action AllDifferent (Phase A/S) + runtime try-lock |
| Deadlock freedom | Canonical lock ordering (pool_id, instance_id) |
| LRM traversal order | pre_solve → solve → post_solve → acquire → execute → release |
| Parallel-branch isolation | Each branch has its own `ActionContext` and resource assignments |
| Data-flow ordering | Buffer futures, stream queues, and schedule-graph stages |
| Deterministic replay | Per-traversal seed derived from parent seed and action identity |
| Flow-object constraint consistency | Producer constraints accumulated and injected into consumer solve |
| Structural completeness | All flow-object slots bound before first action executes (Phase S) |
| Schedule block legality | Sequential/concurrent conflict detection at elaboration (Phase E) |
| Inference necessity | Only infer actions required to satisfy unbound flow-object slots (LRM §5.3.2) |
| Inference termination | Depth limit and cycle detection in ICL graph search |

---

## 17. Worked Example: Parallel DMA Transfer

Consider two DMA transfers running in parallel, each requiring exclusive use of
one DMA channel from a two-channel pool.

**PSS model (conceptual):**
```pss
component dma_c {
    pool[2] channel_s channels;  /* two DMA channels */
    bind channels *;

    action transfer {
        lock channel_s chan;      /* exclusive channel */
        rand bit[31:0] src_addr;
        rand bit[15:0] length;
        constraint length in [1..4096];
    }
}

action par_xfer {
    activity {
        parallel {
            do dma_c::transfer;
            do dma_c::transfer;
        }
    }
}
```

**Execution flow:**

```
1. par_xfer task starts
2. Head-action coordinated solve:
     branch[0].chan.instance_id = 1   (AllDifferent ensures ≠ branch[1])
     branch[1].chan.instance_id = 0
3. Join initialized (waiting for 2 completions)
4. Branch[0] and branch[1] spawned concurrently

5. Branch[0]: force-lock channel[1], solve src_addr/length, yield
6. Branch[1]: force-lock channel[0], solve src_addr/length, yield

7. Branch[0] resumes: execute transfer body, unlock channel[1], done → signal join
8. Branch[1] resumes: execute transfer body, unlock channel[0], done → signal join
                                                                        (remaining=0: wake parent)

9. par_xfer resumes: both branches joined, return DONE
```

Key observations:
- Neither branch ever blocks waiting for a channel (AllDifferent prevents
  both from wanting the same channel upfront).
- If par_xfer were extended with a third sequential transfer after the parallel
  block, that transfer would solve and acquire a channel at runtime — whoever
  has one free first wins.
- If three transfers were run in parallel against a two-channel pool, the
  head-action solve would assign channels to two of them; the third would block
  until one of the first two releases.

---

## 18. Key Design Decisions

| Decision | Rationale |
|---|---|
| **Per-step solving instead of monolithic** | Bounds memory and compute; enables streaming execution; matches embedded constraints; produces equivalent results for independent sequential chains |
| **Three-phase execution (E / S / A)** | Separates concerns with very different cost profiles: elaboration and structural inference are cheap amortised across all traversals; per-action data solving is the tight inner loop |
| **Structural inference on solve platform only** | Backtracking ICL search is NP-hard in general; embedded targets receive a pre-solved, structurally complete execution plan |
| **Head-action coordinated solve** | The only point where cross-branch resource assignments must agree; doing it upfront prevents blocking at branch start |
| **Runtime arbitration for tail actions** | Eliminates the need to solve the entire parallel sub-tree upfront; any legal ordering is acceptable |
| **Canonical lock ordering** | Zero runtime overhead; provably prevents circular-wait deadlock |
| **Asyncio for Python / frame-chain for C** | Each matches the idioms and constraints of its target environment; the semantic model is the same |
| **Schedule block = constraint graph + staged execution** | Phase E analysis detects illegal orderings early; runtime handles undirected mutex pairs organically via resource-pool blocking |
| **Schedule and inference share the same constraint graph infrastructure** | Flow-object binding edges, concurrent-pair sets, and topological ordering are the same problem regardless of whether actions are explicit or inferred |
| **Per-traversal RNG seed** | Enables deterministic replay: same root seed → same sequence of solved values |
