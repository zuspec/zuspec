# PSS Inference — Implementation, Testing, and Documentation Plan

> **Scope**: Python runtime only — pure-Python constraint solver and native
> `zuspec-solver` invoked from Python.  The C/embedded code-generation path
> is excluded from this plan.
>
> **Design reference**: `pss-inference-design.md`

---

## 1. Current-State Assessment

### 1.1 What Already Exists

| Component | File | Notes |
|---|---|---|
| `ActivityRunner` | `rt/activity_runner.py` | Full PSS lifecycle; handles sequential, parallel, schedule, select, repeat, etc. |
| `ScheduleGraph` | (inside `activity_runner.py`) | Topological sort on explicit buffer/stream/state bindings; creates `BufferInstance`/`StreamInstance`/`StatePool` |
| `BindingSolver` | `rt/binding_solver.py` | Head-action AllDifferent via random permutation; ~79 lines |
| `ListClaimPool` | `rt/list_claim_pool.py` | Lock/share resource pool with asyncio blocking |
| `FlowObjectRt` | `rt/flow_obj_rt.py` | `BufferInstance`, `StreamInstance`, `StatePool` |
| `ScenarioRunner` | `rt/scenario_runner.py` | `run()` / `run_n()` entry points |
| `PoolResolver` | `rt/pool_resolver.py` | Maps `(component, action_type, field_name)` → pool instance |
| Pure-Python solver | `solver/` | Full CSP: propagators, backtracking, randc, uniqueness (AllDifferent), implication, conditional |
| `RandcManager` | `solver/randc/randc_manager.py` | Cyclic-permutation tracking per field |
| Native solver | `packages/zuspec-solver/` | `SolveProblem` / `SolveCtx` in Python; `ir_translator.py`; 24 unit tests |

### 1.2 What Is Missing (Inference-Specific)

| Component | Design Ref | Status |
|---|---|---|
| `FlowObjectConstraintStore` | §7.2, §8 P1 | ❌ Not implemented |
| ICL construction (elaboration tables) | §4.1, §8 P2 | ❌ Not implemented |
| Phase-S Structural Solver (single-level) | §4.2, §8 P2 | ❌ Not implemented |
| Phase-S Structural Solver (multi-level) | §4.2, §8 P3 | ❌ Not implemented |
| Constraint-driven ICL pruning | §3.1, §8 P3 | ❌ Not implemented |
| Cross-action sequential constraint propagation | §3.3, §8 P3 | ❌ Not implemented |
| Cross-branch joint data solve | §3.3, §8 P4 | ❌ Not implemented |
| Solver selection policy (pure-Python vs native) | §10.5 | ❌ Not implemented |
| Cycle detection in ICL graph | §13 Open Q2 | ❌ Not implemented |

### 1.3 Gap Summary

The runtime can execute **explicitly-specified** activity graphs including
schedule blocks with explicit bindings.  It cannot yet:

- **Infer** missing predecessor or partner actions when flow-object inputs are
  unbound (no ICL search).
- **Propagate** consumer flow-object constraints back into the producer's solve
  so the producer generates output the consumer can accept.  After the producer
  runs the flow object is concrete; the consumer is then randomized with those
  fixed values in context (each action is currently solved in isolation with no
  awareness of the paired action).
- **Select** the native solver automatically when constraint complexity exceeds
  the pure-Python threshold.

---

## 2. Architecture Overview

The following diagram shows the complete layered inference architecture with
the new components (bold) superimposed on the existing runtime:

```
┌─────────────────────────────────────────────────────────────────────┐
│                 Phase E — Elaboration (once per model load)         │
│                                                                     │
│  ElaborationEngine  ──────────────────────────────────────────────  │
│  ┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐  │
│  │ ICLTableBuilder  │  │ PoolBindingTable │  │ TypeFeasibility  │  │
│  │ (NEW)            │  │ PoolResolver     │  │ Pruner (NEW)     │  │
│  └──────────────────┘  │ (EXISTS)         │  └──────────────────┘  │
│                        └──────────────────┘                        │
└────────────────────────────┬────────────────────────────────────────┘
                             │ static ICL tables
┌────────────────────────────▼────────────────────────────────────────┐
│                 Phase S — Structural Solve (per scenario)           │
│                                                                     │
│  StructuralSolver (NEW)                                            │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │  ICL DFS + constraint-driven pruning + cycle detection       │  │
│  │  → augmented activity graph with inferred action nodes       │  │
│  └──────────────────────────────────────────────────────────────┘  │
└────────────────────────────┬────────────────────────────────────────┘
                             │ extended activity graph
┌────────────────────────────▼────────────────────────────────────────┐
│                 Phase A — Action-Execute / Data Solve               │
│                                                                     │
│  ActivityRunner (EXISTS, extended)                                  │
│  ┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐  │
│  │ FlowObj          │  │ FlowObjectConst  │  │ SolverSelector   │  │
│  │ Constraint       │  │ raintStore (NEW) │  │ (NEW)            │  │
│  │ Store inject     │  └──────────────────┘  │ pure-Python OR   │  │
│  └──────────────────┘                        │ native solver    │  │
│  ┌──────────────────┐  ┌──────────────────┐  └──────────────────┘  │
│  │ BindingSolver    │  │ RandcManager     │  ┌──────────────────┐  │
│  │ (EXISTS)         │  │ (EXISTS)         │  │ StatePoolFence   │  │
│  └──────────────────┘  └──────────────────┘  │ (EXISTS via      │  │
│                                              │  StatePool)      │  │
│                                              └──────────────────┘  │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 3. Implementation Phases

Each phase is self-contained: it adds new functionality and its own tests
without breaking existing behaviour.

---

### Phase P1 — Flow-Object Constraint Back-Propagation

**Rationale**: Today each action is solved in isolation.  When a producer and
consumer share a flow object, the producer has no knowledge of what values the
consumer needs, so it may produce output that forces the consumer's solve to
fail or backtrack heavily.

The correct solve order (per LRM §5.4, §16.4.3) is:

1. **Before the producer is randomized**: extract the consumer's constraints
   that reference the shared flow-object fields and inject them into the
   producer's solve context.
2. **Producer is randomized**: with the joint constraint set (its own
   constraints ∪ consumer's flow-field constraints) the producer generates
   output the consumer can accept.
3. **Consumer is randomized**: the flow object's fields are already concrete
   (determined by step 2); the consumer's remaining rand fields are solved
   treating those values as fixed input — the consumer is not asked to
   re-randomize the flow object.

This is the **opposite** direction from naïve forward propagation: consumer
constraints *back-propagate* to shape the producer, not producer constraints
forward-propagate to the consumer.

#### 3.1.1 New Module: `rt/flow_constraint_store.py`

```python
@dc.dataclass
class FlowObjectConstraintStore:
    """Collects consumer flow-input constraints for injection into producer solve.

    For each producer/consumer pair bound to a shared flow object, this store
    holds the consumer's constraint expressions that reference flow-object
    fields.  These are injected into the producer's randomize() call so the
    producer generates output the consumer can accept.

    After the producer runs, the flow object instance carries concrete field
    values; the consumer's randomize() sees those fields as already-determined
    (not re-randomized), then solves its own remaining rand fields.
    """

    # key: id(flow_object_slot_descriptor) → list of ConstraintExpr from consumer
    _consumer_constraints: dict[int, list] = dc.field(default_factory=dict)

    def register_consumer(
        self,
        flow_slot_key: int,          # stable key for this producer/consumer pair
        consumer_constraints: list,  # ConstraintExpr nodes touching flow-obj fields
    ) -> None:
        """Called during Phase-S (or schedule-graph build) when a producer/consumer
        pair is identified.  Stores consumer constraints for later producer injection.
        """

    def constraints_for_producer(self, flow_slot_key: int) -> list:
        """Return consumer constraints to add to the producer's solve context."""

    def clear(self, flow_slot_key: int) -> None:
        """Release stored constraints after the producer has run."""
```

**Design decisions**:

- Store lives on `ScenarioRunner` (persists across the scenario, reset
  between `run()` calls).
- Constraints are raw `ConstraintExpr` IR nodes extracted from the consumer
  action type's field annotations and `constraint` blocks.
- `flow_slot_key` is a stable integer derived from `(producer_type,
  consumer_type, field_name)` — it does not require a live flow instance.
- For stream objects: producer and consumer execute concurrently; constraints
  from both sides must be collected before either is spawned, then a joint
  solve runs before both start (see Phase P3 — stream joint solve).
- `ActionContext` gets a `flow_constraint_store: FlowObjectConstraintStore`
  field threaded down from `ScenarioRunner`.

#### 3.1.2 Integration Points

Integration is driven by the **schedule block** case (where both producer and
consumer are known before either is solved) and later by the **structural
solver** (Phase P2, where the inferred producer is selected before the
consumer runs).

1. **`ScheduleGraph.build()` / `StructuralSolver.solve()`** — when a
   producer/consumer pair is identified, call
   `store.register_consumer(flow_slot_key, consumer_constraints)`.
   This happens before either action is traversed.
2. **`ActivityRunner._traverse()` for the producer** — before calling
   `randomize()`, retrieve `store.constraints_for_producer(flow_slot_key)` and
   add them to `inline_constraints`.  The producer is then randomized with both
   its own constraints and the consumer's flow-field constraints.
3. **`ActivityRunner._traverse()` for the consumer** — the flow object's fields
   are already concrete (written by the producer's body).  The consumer's
   `randomize()` treats flow-input fields as non-rand (fixed values), solving
   only its own remaining rand fields.
4. **`ScenarioRunner.run()`** — create a fresh `FlowObjectConstraintStore` and
   pass it via `ActionContext`.

#### 3.1.3 Solver Integration

- **Pure-Python path**: Add consumer constraints to `inline_constraints` before
  the producer's `randomize()` call.  After the producer runs, pass the
  concrete flow-object field values as additional `inline_constraints` (equality
  constraints) in the consumer's `randomize()` call, preventing re-randomization
  of those fields.
- **Native-solver path**: Translate consumer `ConstraintExpr` nodes to
  `zuspec-solver` IR via `ir_translator.py` and add to the producer's
  `SolveCtx`.  For the consumer, add equality constraints on the concrete
  flow-object field values.

#### 3.1.4 Files Added / Modified

| File | Change |
|---|---|
| `rt/flow_constraint_store.py` | **New** |
| `rt/activity_runner.py` | Inject consumer constraints into producer solve in `_traverse()`; pass concrete values to consumer |
| `rt/action_context.py` | Add `flow_constraint_store` field |
| `rt/scenario_runner.py` | Create store, pass via context |
| `rt/activity_runner.py` (`ScheduleGraph.build`) | Register consumer constraints when producer/consumer pair is identified |

---

### Phase P2 — Single-Level Structural Inference

**Rationale**: Enables the runtime to automatically infer a sequential
predecessor (buffer/state) or a concurrent partner (stream) when an action
has an unbound flow-object input.  This covers the common PSS inference
pattern (ICL depth = 1).

#### 3.2.1 New Module: `rt/icl_table.py` — ICL Construction

```python
@dc.dataclass
class ICLEntry:
    """One candidate action type for satisfying an unbound flow-object slot."""
    action_type: type
    output_field: str       # which output field produces the required type
    flow_obj_type: type     # the flow-object type produced

@dc.dataclass
class ICLTable:
    """Pre-computed Inferencing Candidate List table (Phase E output).

    key: (consumer_action_type, input_field_name) → list[ICLEntry]
    """
    _table: dict[tuple, list[ICLEntry]] = dc.field(default_factory=dict)

    @staticmethod
    def build(registry: "ActionRegistry") -> "ICLTable":
        """Construct the table from all known action types."""

    def candidates(
        self, consumer_type: type, field_name: str
    ) -> list[ICLEntry]:
        """Return ICL candidates for (consumer_type, field_name)."""
```

**Action registry**: All action types reachable from a component tree must be
discoverable.  `PoolResolver.build()` already walks the component tree; extend
it (or add a parallel `ActionRegistry.build()`) to enumerate all action types
reachable per pool.

#### 3.2.2 New Module: `rt/structural_solver.py` — Phase-S Structural Solve

```python
class StructuralSolver:
    """Resolves unbound flow-object inputs by selecting ICL candidates.

    Depth-first search with a configurable depth limit (default: 5).
    Produces an augmented list of (action_type, ordering) tuples that
    the ActivityRunner inserts before/alongside the triggering action.
    """

    def __init__(
        self,
        icl_table: ICLTable,
        max_depth: int = 5,
        rng: random.Random = None,
    ) -> None: ...

    def solve(
        self,
        consumer_type: type,
        unbound_slots: list[tuple[str, type]],   # (field_name, flow_obj_type)
        ctx: ActionContext,
    ) -> list[InferredAction]:
        """Return inferred actions to add before/alongside consumer.

        Raises InferenceLimitError if depth limit exceeded.
        Raises InferenceFeasibilityError if ICL is empty for any slot.
        """

@dc.dataclass
class InferredAction:
    action_type: type
    ordering: Literal["sequential_before", "concurrent"]
    output_field: str      # field on inferred action that supplies the flow obj
    input_field: str       # field on consumer that receives the flow obj
```

**Ordering rules** (from LRM):
- Buffer/state inputs → inferred predecessor is **sequential_before**.
- Stream inputs → inferred partner is **concurrent**.

**Cycle detection**: Maintain a `seen: set[type]` during the DFS.  If a
candidate type is already in `seen`, skip it (would create an inference cycle).

#### 3.2.3 Integration with `ActivityRunner`

Extend `ActivityRunner._traverse()`:

```python
# Before the normal action lifecycle, check for unbound flow inputs:
unbound = _find_unbound_flow_inputs(action_type, ctx)
if unbound:
    inferred = ctx.structural_solver.solve(action_type, unbound, ctx)
    for ia in inferred:
        if ia.ordering == "sequential_before":
            await self._traverse(ia.action_type, [], inferred_ctx)
            # wire flow obj from inferred action to consumer
        else:  # concurrent
            # spawn both together via asyncio.gather()
            await asyncio.gather(
                self._traverse(ia.action_type, [], inferred_ctx),
                self._traverse(action_type, inline_constraints, ctx),
            )
            return  # consumer already traversed above
```

`_find_unbound_flow_inputs()` inspects the action type's dataclass fields for
`kind="flow_ref"` + `direction="input"` metadata where no binding has been
provided in `ctx.flow_bindings`.

#### 3.2.4 Files Added / Modified

| File | Change |
|---|---|
| `rt/icl_table.py` | **New** |
| `rt/structural_solver.py` | **New** |
| `rt/activity_runner.py` | Integrate structural solve in `_traverse()` |
| `rt/action_context.py` | Add `structural_solver` and `icl_table` fields |
| `rt/pool_resolver.py` | Extend to enumerate action types per pool |
| `rt/scenario_runner.py` | Build `ICLTable` and `StructuralSolver`; pass via context |

---

### Phase P3 — Multi-Level Inference Chains and Cross-Action Constraints

**Rationale**: Handles the full LRM ICL algorithm (Annex E): recursive
chain expansion, type-level constraint feasibility pruning, and forward
propagation of constraints across sequentially chained actions.

#### 3.3.1 Multi-Level ICL Expansion

Extend `StructuralSolver.solve()` to recurse: when an inferred action itself
has unbound flow-object inputs, apply ICL selection again (up to `max_depth`).

```python
def _solve_recursive(
    self,
    consumer_type: type,
    unbound_slots: list,
    depth: int,
    seen: set[type],
    ctx: ActionContext,
) -> list[InferredAction]:
    if depth > self.max_depth:
        raise InferenceLimitError(...)
    for slot_field, slot_type in unbound_slots:
        candidates = self._icl_table.candidates(consumer_type, slot_field)
        for entry in candidates:
            if entry.action_type in seen:
                continue   # cycle guard
            seen.add(entry.action_type)
            sub_unbound = _find_unbound_flow_inputs(entry.action_type, ctx)
            sub_actions = self._solve_recursive(
                entry.action_type, sub_unbound, depth + 1, seen, ctx
            )
            # Prepend sub_actions before entry
            ...
```

#### 3.3.2 Constraint-Driven ICL Pruning (Type-Level)

Add `TypeFeasibilityChecker` to `icl_table.py`:

```python
class TypeFeasibilityChecker:
    """Performs type-level constraint compatibility checks to prune ICL.

    Checks whether the type-level constraints of an ICL candidate are
    structurally compatible with the consumer's flow-object constraints.
    Does NOT do full data-value solving — that is Phase A.
    """

    def is_feasible(
        self,
        candidate: ICLEntry,
        consumer_type: type,
        consumer_field: str,
    ) -> bool:
        """Return False if constraints are structurally incompatible."""
```

Integrate into `ICLTable.build()`: when a pair is infeasible, omit it from
the ICL.  Infeasible pairs are logged for debugging.

#### 3.3.3 Cross-Action Sequential Constraint Propagation

New module: `rt/forward_constraint_propagator.py`

```python
class ForwardConstraintPropagator:
    """Propagates concrete field values from a completed action into the next
    sequential action's solve context.

    This handles cross-action constraints that reference *non-flow-object*
    fields of sequentially chained actions — for example:
        constraint b.offset == a.end_addr + 4;
    where `end_addr` is a local rand field of action `a`, not a flow object.

    Flow-object field constraints are handled separately by
    FlowObjectConstraintStore (Phase P1), which back-propagates consumer
    constraints into the producer's solve before the producer runs.
    This propagator handles the complementary case where the constraint
    source is a field that is only concrete AFTER the predecessor has run.
    """

    def record_completed(self, action: Any) -> None:
        """After action.body() completes, record its concrete field values."""

    def inject(self, next_action_constraints: list, solve_ctx) -> None:
        """Before the next action's randomize(), inject equality constraints
        derived from the previously completed action's field values."""
```

**Scope**: Sequential chains where constraint `b.x == f(a.y)` and `a.y` is
determined only after `a` runs (not a flow-object field — those are handled by
`FlowObjectConstraintStore`).  No cross-branch propagation (Phase P4).

#### 3.3.4 Files Added / Modified

| File | Change |
|---|---|
| `rt/icl_table.py` | Add `TypeFeasibilityChecker` |
| `rt/structural_solver.py` | Extend with recursive expansion and cycle detection |
| `rt/forward_constraint_propagator.py` | **New** |
| `rt/activity_runner.py` | Integrate forward propagator in sequential traversal |
| `rt/action_context.py` | Add `forward_propagator` field |

---

### Phase P4 — Joint Solve and Solver Selection Policy

**Rationale**: Completes LRM compliance for the hardest constraint cases
(cross-branch data constraints, large joint CSPs) and adds automatic
selection between pure-Python and native solvers.

#### 3.4.1 Solver Selection Policy

New module: `rt/solver_selector.py`

```python
class SolverSelector:
    """Chooses between pure-Python and native zuspec-solver.

    Selection criteria (from §10.5 of pss-inference-design.md):

    Use native solver when:
    - variable count > 16
    - AllDifferent set size > 4
    - cross-action constraints are present
    - flow-object constraint system involves > 5 actions

    Use pure-Python otherwise (preferred for simpler cases).
    """

    def select(self, problem: SolveProblem) -> Literal["python", "native"]:
        ...

    def solve(self, problem: SolveProblem, ctx: ActionContext) -> Solution:
        backend = self.select(problem)
        if backend == "native":
            return self._native_solve(problem, ctx)
        return self._python_solve(problem, ctx)

    def _native_solve(self, problem, ctx) -> Solution:
        from zuspec.solver import SolveCtx
        ...

    def _python_solve(self, problem, ctx) -> Solution:
        from ..solver.api import randomize
        ...
```

#### 3.4.2 Cross-Branch Joint Data Solve

When actions in parallel branches share data constraints
(`branch1.action.addr + branch2.action.len == total`), a joint solve over all
involved actions' rand fields is required.

**Approach**:

1. During Phase-S structural solve, detect cross-branch constraint references
   (constraints in one branch that reference fields from another).
2. Group all involved branch-head actions into a single `JointSolveGroup`.
3. During Phase-A, before spawning branches, call `SolverSelector.solve()`
   on the joint problem.  Write solved values back as `inline_constraints`
   for each branch.

**Native solver is required** for this case (>4 variables across branches).

#### 3.4.3 Compound Resource Constraints

Extend `BindingSolver.solve_heads()` to handle constraints that span multiple
resource fields (`r1.addr < r2.addr`):

1. Encode as a multi-variable CSP over resource field values.
2. Use `SolverSelector` to choose backend.
3. Return solved resource-field values alongside instance_id assignments.

#### 3.4.4 Files Added / Modified

| File | Change |
|---|---|
| `rt/solver_selector.py` | **New** |
| `rt/joint_solve_group.py` | **New** |
| `rt/binding_solver.py` | Extend for compound resource constraints |
| `rt/structural_solver.py` | Detect cross-branch constraint references |
| `rt/activity_runner.py` | Joint solve before `asyncio.gather()` in `_parallel()` |
| `rt/action_context.py` | Add `solver_selector` field |
| `rt/scenario_runner.py` | Create and pass `SolverSelector` |

---

## 4. Testing Plan

### 4.1 Test Organization

All tests live in `packages/zuspec-dataclasses/tests/`.  New inference tests
go into:

```
tests/
  inference/
    unit/
      test_icl_table.py
      test_structural_solver.py
      test_flow_constraint_store.py
      test_forward_constraint_propagator.py
      test_solver_selector.py
      test_type_feasibility.py
    integration/
      test_p1_buffer_constraints.py
      test_p1_state_constraints.py
      test_p2_buffer_inference.py
      test_p2_state_inference.py
      test_p2_stream_inference.py
      test_p3_multilevel_chain.py
      test_p3_constraint_pruning.py
      test_p3_cross_action_sequential.py
      test_p4_joint_solve.py
      test_p4_solver_selection.py
    e2e/
      test_e2e_dma_buffer_infer.py
      test_e2e_spi_state_infer.py
      test_e2e_stream_codec.py
      test_e2e_multichannel_dma.py
      test_e2e_bus_chain.py
```

### 4.2 Phase P1 Tests

#### `test_flow_constraint_store.py` (unit)

| Test | Verifies |
|---|---|
| `test_register_and_retrieve_single` | Consumer constraints registered; retrieved correctly for producer injection |
| `test_key_isolation` | Two different producer/consumer pairs do not share constraint lists |
| `test_clear_after_producer_runs` | Store clears correctly; no stale constraints on next scenario |
| `test_native_solver_injection` | Consumer constraints are correctly translated for native solver producer context |

#### `test_p1_buffer_constraints.py` (integration)

| Test | Verifies |
|---|---|
| `test_producer_respects_consumer_constraint` | Consumer constraint `data.val > 100` causes producer to generate `data.val > 100` |
| `test_consumer_sees_concrete_value` | Consumer action's `body()` sees the concrete value the producer generated |
| `test_consumer_rand_fields_free` | Consumer's own rand fields (unrelated to flow obj) are still freely randomized |
| `test_state_consumer_constraint_propagation` | Same back-propagation test for state flow objects |
| `test_infeasible_consumer_constraint_raises` | Consumer constraint `data.val > 200` + producer constraint `data.val < 10` raises solve error |
| `test_no_spurious_cross_scenario` | Consumer constraints do NOT carry over between consecutive `run()` calls |

### 4.3 Phase P2 Tests

#### `test_icl_table.py` (unit)

| Test | Verifies |
|---|---|
| `test_build_single_producer` | One producer type for a buffer slot produces one ICL entry |
| `test_build_multiple_producers` | Multiple producers for same flow type all appear in ICL |
| `test_no_wrong_type_candidates` | Incompatible flow types do not appear in ICL |
| `test_pool_scoping` | Actions not reachable to the correct pool are excluded |
| `test_empty_icl_for_unknown_type` | Non-registered type yields empty list |

#### `test_structural_solver.py` (unit)

| Test | Verifies |
|---|---|
| `test_buffer_single_level` | Resolves one unbound buffer input to one ICL candidate |
| `test_state_single_level` | Resolves one unbound state input to sequential predecessor |
| `test_stream_single_level` | Resolves one unbound stream input to concurrent partner |
| `test_empty_icl_raises` | `InferenceFeasibilityError` when no candidates exist |
| `test_cycle_detection` | Recursive type cycle does not produce infinite loop |
| `test_depth_limit` | `InferenceLimitError` when depth > max_depth |

#### `test_p2_buffer_inference.py` (integration)

| Test | Verifies |
|---|---|
| `test_infer_single_buffer_predecessor` | `ReadData` alone in activity; `WriteData` is inferred before it |
| `test_infer_runs_before_consumer` | Inferred action body() executes before consumer body() |
| `test_inferred_action_randomized` | Inferred action's rand fields are solved |
| `test_explicit_bind_not_re_inferred` | Explicitly bound flow obj is not replaced by inference |

#### `test_p2_state_inference.py` (integration)

| Test | Verifies |
|---|---|
| `test_infer_state_writer_before_reader` | State reader action gets state writer inferred before it |
| `test_infer_does_not_duplicate_writer` | If writer already present in schedule block, not re-inferred |

#### `test_p2_stream_inference.py` (integration)

| Test | Verifies |
|---|---|
| `test_infer_stream_partner_concurrent` | Stream consumer gets producer spawned concurrently |
| `test_stream_data_flows` | Data produced by inferred producer is received by consumer |

### 4.4 Phase P3 Tests

#### `test_p3_multilevel_chain.py` (integration)

| Test | Verifies |
|---|---|
| `test_depth_2_chain` | C needs B (buffer); B needs A (buffer); both A and B are inferred |
| `test_depth_3_chain` | D→C→B→A inference chain resolves correctly |
| `test_depth_limit_enforced` | Chain at depth > max_depth raises `InferenceLimitError` |
| `test_ordering_preserved` | Execution order is A→B→C (deepest first) |

#### `test_p3_constraint_pruning.py` (integration)

| Test | Verifies |
|---|---|
| `test_infeasible_candidate_pruned` | Type-level incompatible ICL candidate is excluded |
| `test_feasible_candidate_selected` | Compatible candidate is selected |
| `test_all_candidates_infeasible_raises` | All candidates infeasible → `InferenceFeasibilityError` |

#### `test_p3_cross_action_sequential.py` (integration)

| Test | Verifies |
|---|---|
| `test_constraint_a_field_used_in_b` | `b.in_val == a.out_val + 1` satisfied correctly |
| `test_propagation_does_not_affect_unrelated` | Cross-action propagation does not bleed into unrelated actions |

### 4.5 Phase P4 Tests

#### `test_solver_selector.py` (unit)

| Test | Verifies |
|---|---|
| `test_simple_problem_uses_python` | ≤16 variables → pure-Python backend |
| `test_large_problem_uses_native` | >16 variables → native solver |
| `test_alldifferent_small_uses_python` | AllDifferent ≤4 → pure-Python |
| `test_alldifferent_large_uses_native` | AllDifferent >4 → native solver |
| `test_cross_action_always_native` | Cross-action flag forces native |
| `test_native_solver_produces_valid_solution` | Native solver result passes constraint check |
| `test_python_solver_produces_valid_solution` | Pure-Python result passes constraint check |

#### `test_p4_joint_solve.py` (integration)

| Test | Verifies |
|---|---|
| `test_cross_branch_data_constraint` | `branch1.addr + branch2.len == total` solved jointly |
| `test_joint_solve_both_branches_valid` | Both branch actions satisfy their individual constraints |
| `test_joint_solve_backtrack_on_infeasible` | Joint solve backtracks when first assignment is infeasible |

### 4.6 Regression Guard

All existing tests must continue to pass after each phase:

```bash
pytest packages/zuspec-dataclasses/tests/ -x --timeout=60
```

A CI gate runs after each phase merge to enforce this.

---

## 5. Documentation Plan

### 5.1 API Reference (inline docstrings)

Every new public class and function must have a NumPy-style docstring with:

- One-line summary
- Extended description (2–5 sentences)
- Parameters section
- Returns/Raises section
- Notes section for LRM references (e.g., `See LRM §17.1`)
- Example section where non-trivial

Files requiring docstring updates: `flow_constraint_store.py`,
`icl_table.py`, `structural_solver.py`, `forward_constraint_propagator.py`,
`solver_selector.py`, `joint_solve_group.py`.

### 5.2 Architecture Document: `docs/inference_architecture.md`

Target audience: contributors and tool integrators.

Sections:
1. Design goals and non-goals
2. Three-phase model (E / S / A) — what happens in each phase, why the split
3. Flow-object constraint propagation — how producer constraints reach consumers
4. ICL construction — what the table contains, how it is built
5. Structural solve — DFS algorithm, depth limit, cycle detection
6. Solver selection policy — thresholds and rationale
7. Interaction with existing runtime (`ActivityRunner`, `ScheduleGraph`, `BindingSolver`)
8. Limitations and open questions (cross-branch joint solve, randc scoping, stream joint solve)
9. Glossary (ICL, Phase E/S/A, flow object, pool, inference chain)

### 5.3 User Guide: `docs/inference_user_guide.md`

Target audience: PSS model authors using zuspec-dataclasses.

Sections:
1. **What inference does** — plain-English explanation with a before/after example
2. **Buffer inference** — worked example: `ReadData` alone, `WriteData` inferred
3. **State inference** — worked example: `ReadRegister` inferred after `WriteRegister`
4. **Stream inference** — worked example: decoder with inferred encoder partner
5. **Multi-level chains** — example: 3-deep inference chain
6. **Controlling inference** — `max_depth`, disabling inference per slot
7. **Solver selection** — when native solver is used, performance implications
8. **Troubleshooting** — common errors (`InferenceLimitError`, `InferenceFeasibilityError`)

### 5.4 Example Inline Comments in Source

Each showcase example (§6) must have a module-level docstring explaining:
- What PSS scenario is modelled
- Which inference features it demonstrates
- Expected output (abbreviated)
- How to run it

### 5.5 CHANGELOG Entry

Add a `CHANGELOG.md` section for each phase release documenting:
- New public API
- Breaking changes (none expected for P1–P3)
- LRM compliance status (which §§ are now covered)

---

## 6. Showcase Examples

These are complete, runnable Python files that demonstrate inference
end-to-end.  Each can be executed directly (`python examples/...`) and
also used as pytest tests.

All showcase examples follow this structure:
```
examples/inference/
  01_dma_buffer_inference.py
  02_spi_state_inference.py
  03_streaming_codec.py
  04_multichannel_dma.py
  05_bus_arbitration_chain.py
  README.md
```

---

### Example 1: `01_dma_buffer_inference.py` — Buffer Inference

**Demonstrates**: Phase P2 — single-level buffer structural inference.

**Scenario**: A `ReadData` action requires a `DataBuffer` input but no
`WriteData` predecessor is listed in the activity.  The inference engine
detects the unbound buffer slot, selects `WriteData` from the ICL, and
inserts it as a sequential predecessor.

```
User writes:
  do ReadData      ← has a DataBuffer input, but no producer listed

Inference inserts:
  do WriteData     ← sequential predecessor, produces the DataBuffer
  do ReadData      ← now has its input bound
```

**Key things to observe in output**:
- `WriteData.body()` executes before `ReadData.body()`
- `WriteData`'s output `DataBuffer` is the same instance received by `ReadData`
- `ReadData`'s rand fields are constrained by whatever `WriteData` solved

**PSS LRM reference**: §5.3.2, §17.1

---

### Example 2: `02_spi_state_inference.py` — State Inference

**Demonstrates**: Phase P2 — single-level state structural inference.

**Scenario**: An SPI Flash memory model.  A `FlashRead` action requires the
flash device to be in `ChipSelected` state, but only `FlashRead` is listed in
the activity.  Inference inserts `SelectChip` as a sequential predecessor, and
`DeselectChip` as a sequential successor (if modelled as a state transition).

```
User writes:
  do FlashRead         ← requires flash in ChipSelected state

Inference inserts:
  do SelectChip        ← sequential predecessor, outputs ChipSelected state
  do FlashRead
```

**Component model**:
```python
@zdc.dataclass
class ChipSelectedState(zdc.State):
    chip_id: zdc.u4 = zdc.rand()

@zdc.dataclass
class SelectChip(zdc.Action[SpiController]):
    chip_state: ChipSelectedState = zdc.output()
    target_chip: zdc.u4 = zdc.rand()

@zdc.dataclass
class FlashRead(zdc.Action[SpiController]):
    chip_state: ChipSelectedState = zdc.input()
    address: zdc.u32 = zdc.rand()
    length: zdc.u16 = zdc.rand()
    async def body(self):
        print(f"Flash read: chip={self.chip_state.chip_id} "
              f"addr=0x{self.address:08x} len={self.length}")
```

**Key things to observe**:
- `SelectChip.body()` runs before `FlashRead.body()`
- `FlashRead.chip_state` is the same instance written by `SelectChip`
- Constraint propagation: `FlashRead`'s `chip_state.chip_id` cannot contradict `SelectChip`'s solve

---

### Example 3: `03_streaming_codec.py` — Stream Inference

**Demonstrates**: Phase P2 — stream structural inference (parallel partner).

**Scenario**: A video pipeline.  A `DecodeFrame` action has a stream input
(compressed frame data).  Only `DecodeFrame` is listed; inference infers an
`EncodeFrame` partner that runs concurrently in the other direction of the
stream.

```
User writes:
  do DecodeFrame       ← has a FrameStream input

Inference inserts:
  do EncodeFrame  ↕    ← runs concurrently with DecodeFrame
  do DecodeFrame  ↕    ← receives stream from EncodeFrame
```

**Component model**:
```python
@zdc.dataclass
class FrameStream(zdc.Stream):
    width: zdc.u16 = zdc.rand()
    height: zdc.u16 = zdc.rand()

@zdc.dataclass
class EncodeFrame(zdc.Action[VideoCore]):
    frame_out: FrameStream = zdc.output()

@zdc.dataclass
class DecodeFrame(zdc.Action[VideoCore]):
    frame_in: FrameStream = zdc.input()
    async def body(self):
        print(f"Decoding {self.frame_in.width}×{self.frame_in.height} frame")
```

**Key things to observe**:
- Both `EncodeFrame` and `DecodeFrame` spawn concurrently (asyncio gather)
- `EncodeFrame.body()` uses `frame_out.put()` to send compressed data
- `DecodeFrame.body()` blocks on `frame_in.get()` until data arrives
- The stream provides natural back-pressure

---

### Example 4: `04_multichannel_dma.py` — Parallel DMA with Resource AllDifferent

**Demonstrates**: Phase P2 + existing `BindingSolver` — parallel branches
each claiming a distinct DMA channel, combined with buffer inference.

**Scenario**: A DMA subsystem with 4 channels.  Two parallel `DmaXfer`
compound actions run concurrently; each must claim a **different** DMA
channel.  Within each `DmaXfer`, a `WriteData`→`ReadData` sequence flows
through a `DataBuffer`.

```
parallel {
    do DmaXfer    ← claims channel 0 (example); WriteData → ReadData
    do DmaXfer    ← claims channel 1 (example); WriteData → ReadData
}
```

**Key things to observe**:
- Both `DmaXfer` actions complete without deadlock
- Channel assignments are distinct (AllDifferent enforced by `BindingSolver`)
- Buffer inference fires inside each `DmaXfer` independently
- Output log shows which channels were assigned and the data flow within each

**Component model sketch**:
```python
@zdc.dataclass
class DmaChannel(zdc.Resource):
    bandwidth: zdc.u8 = zdc.rand()

@zdc.dataclass
class DataBuffer(zdc.Buffer):
    addr: zdc.u32 = zdc.rand()
    size: zdc.u16 = zdc.rand()

@zdc.dataclass
class WriteData(zdc.Action[DmaComp]):
    buf: DataBuffer  = zdc.output()
    chan: DmaChannel = zdc.lock()

@zdc.dataclass
class ReadData(zdc.Action[DmaComp]):
    buf: DataBuffer  = zdc.input()
    chan: DmaChannel = zdc.lock()
```

**Running it**:
```bash
python examples/inference/04_multichannel_dma.py
# Output shows channel assignments + data-buffer addresses for each parallel arm
```

---

### Example 5: `05_bus_arbitration_chain.py` — Multi-Level Inference Chain

**Demonstrates**: Phase P3 — depth-2 inference chain.

**Scenario**: A bus protocol stack.  A `SendPacket` action requires the bus
to be in `ArbitratedState` (state input).  `Arbitratebus` produces that
state but requires the bus to be in `ResetState` first.  `ResetBus` produces
`ResetState`.

```
User writes:
  do SendPacket        ← needs ArbitratedState

Level 1 inference:
  do ArbitrateBus      ← needs ResetState; produces ArbitratedState

Level 2 inference:
  do ResetBus          ← produces ResetState

Final execution order:
  ResetBus → ArbitrateBus → SendPacket
```

**Component model sketch**:
```python
@zdc.dataclass
class ResetState(zdc.State):
    bus_id: zdc.u4 = zdc.rand()

@zdc.dataclass
class ArbitratedState(zdc.State):
    bus_id: zdc.u4 = zdc.rand()
    winner_id: zdc.u4 = zdc.rand()

@zdc.dataclass
class ResetBus(zdc.Action[BusComp]):
    rst: ResetState = zdc.output()
    async def body(self): print("BUS RESET")

@zdc.dataclass
class ArbitrateBus(zdc.Action[BusComp]):
    rst: ResetState     = zdc.input()
    arb: ArbitratedState = zdc.output()
    async def body(self): print(f"ARBITRATED, winner={self.arb.winner_id}")

@zdc.dataclass
class SendPacket(zdc.Action[BusComp]):
    arb: ArbitratedState = zdc.input()
    payload_size: zdc.u8 = zdc.rand()
    async def body(self): print(f"SENT {self.payload_size}-byte packet")
```

**Key things to observe**:
- Three-action chain is inferred from a single `do SendPacket`
- `ResetBus.rst` is the same `ResetState` instance read by `ArbitrateBus`
- `ArbitrateBus.arb` is the same `ArbitratedState` instance read by `SendPacket`
- Output shows execution order and state values

---

### Example README: `examples/inference/README.md`

A concise guide (≤2 pages) covering:

1. **Prerequisites**: `pip install -e packages/zuspec-dataclasses`
2. **Running all examples**: `python -m pytest examples/inference/ -v`
3. **Quick descriptions** of each example with the one-line inference rule it demonstrates
4. **Disabling inference**: `ScenarioRunner(comp, enable_inference=False)`
5. **Depth control**: `ScenarioRunner(comp, inference_max_depth=3)`

---

## 7. Implementation Sequence and Dependencies

```
Phase P1  ─────────────────────────────────────────────────────────►  P1 complete
  FlowObjectConstraintStore
  Integration in ActivityRunner._traverse()
  ScenarioRunner wires store through ActionContext
  Tests: test_flow_constraint_store (unit), test_p1_buffer_constraints (integration)
  Examples: (partial) 04_multichannel_dma (buffer values visible)

Phase P2  (depends on P1)  ──────────────────────────────────────►  P2 complete
  ICLTableBuilder + ICLTable
  StructuralSolver (single-level, cycle detection)
  ActionRegistry.build() extension to PoolResolver
  Integration in ActivityRunner._traverse()
  Tests: test_icl_table, test_structural_solver (unit)
         test_p2_buffer/state/stream_inference (integration)
  Examples: 01, 02, 03 fully runnable; 04, 05 partial

Phase P3  (depends on P2)  ──────────────────────────────────────►  P3 complete
  Recursive ICL expansion in StructuralSolver
  TypeFeasibilityChecker in ICLTable
  ForwardConstraintPropagator
  Tests: test_p3_multilevel_chain, test_p3_constraint_pruning,
         test_p3_cross_action_sequential (integration)
  Examples: 05 fully runnable; all examples with constraint propagation

Phase P4  (depends on P3)  ──────────────────────────────────────►  P4 complete
  SolverSelector (policy + native backend invocation)
  JointSolveGroup for cross-branch constraints
  Compound resource constraint extension to BindingSolver
  Tests: test_solver_selector (unit), test_p4_joint_solve,
         test_p4_solver_selection (integration)
  Examples: heavy-constraint variants of 04; new stress examples
```

---

## 8. Key Design Decisions and Open Questions

### 8.1 Decisions Made (Aligned with Design Doc)

| Decision | Rationale |
|---|---|
| Separate Phase-S (structural) from Phase-A (data) | LRM semantics; structure must be known before resources are allocated |
| `FlowObjectConstraintStore` keyed by `(producer_type, consumer_type, field_name)` | Instance identity is not available at registration time (Phase S); a stable type-level key avoids dangling-reference issues |
| Consumer constraints back-propagate into producer solve | LRM §5.4, §16.4.3: the producer must generate output the consumer can accept; the consumer then randomizes with the flow object fixed |
| ICL table built at elaboration time (module load) | Avoids per-traversal overhead; type graph is static |
| Option B for mutex pairs (runtime resource-race) | Natural fit for asyncio-based runtime; `ListClaimPool.lock()` already implements this |
| Cycle detection via `seen: set[type]` in DFS | Sufficient for type-level cycles; instance-level cycles cannot occur at elaboration time |
| Solver threshold: >16 variables → native | Empirically fast threshold; configurable via `SolverSelector` constructor |

### 8.2 Open Questions (from §13 of Design Doc)

| # | Question | Proposed Resolution |
|---|---|---|
| 1 | Stream joint solve: does `BindingSolver.solve_heads()` extend to streams? | Add dedicated `solve_stream_pair()` method in Phase P3 |
| 3 | Anonymous instance ordering: always sequential/concurrent from flow type, or randomizable? | Default: determined by flow type; add `randomize_infer_ordering=True` flag in Phase P4 |
| 5 | Persistent `SolveCtx` across incremental steps vs. fresh context per action? | Fresh context per action for correctness; profile to decide if persistent context is worth the complexity |
| 6 | `deterministic_schedule` mode for reproducible mutex pair resolution? | Implement as `ScenarioRunner(comp, deterministic=True)` in Phase P4 |
| 7 | Phase S + Phase E interleaving for schedule blocks with deep inference chains? | Single-pass variant (process ICL candidates in topological order) in Phase P3 as optimization |

---

## 9. File Index (New and Modified)

### New Files

| File | Phase | Purpose |
|---|---|---|
| `rt/flow_constraint_store.py` | P1 | Cross-action constraint accumulation for flow objects |
| `rt/icl_table.py` | P2 | ICL construction and type-feasibility pruning |
| `rt/structural_solver.py` | P2/P3 | Phase-S DFS ICL search with multi-level and cycle detection |
| `rt/forward_constraint_propagator.py` | P3 | Sequential cross-action constraint propagation |
| `rt/solver_selector.py` | P4 | Policy for choosing pure-Python vs. native solver |
| `rt/joint_solve_group.py` | P4 | Cross-branch joint data solve grouping |
| `tests/inference/unit/test_icl_table.py` | P2 | Unit tests for ICL table |
| `tests/inference/unit/test_structural_solver.py` | P2/P3 | Unit tests for structural solver |
| `tests/inference/unit/test_flow_constraint_store.py` | P1 | Unit tests for constraint store |
| `tests/inference/unit/test_forward_constraint_propagator.py` | P3 | Unit tests for propagator |
| `tests/inference/unit/test_solver_selector.py` | P4 | Unit tests for solver selection |
| `tests/inference/unit/test_type_feasibility.py` | P3 | Unit tests for feasibility checker |
| `tests/inference/integration/test_p1_*.py` | P1 | Integration tests for P1 |
| `tests/inference/integration/test_p2_*.py` | P2 | Integration tests for P2 |
| `tests/inference/integration/test_p3_*.py` | P3 | Integration tests for P3 |
| `tests/inference/integration/test_p4_*.py` | P4 | Integration tests for P4 |
| `tests/inference/e2e/test_e2e_*.py` | P2+ | End-to-end showcase tests |
| `examples/inference/01_dma_buffer_inference.py` | P2 | Showcase: buffer inference |
| `examples/inference/02_spi_state_inference.py` | P2 | Showcase: state inference |
| `examples/inference/03_streaming_codec.py` | P2 | Showcase: stream inference |
| `examples/inference/04_multichannel_dma.py` | P2/P3 | Showcase: parallel + AllDifferent + buffer |
| `examples/inference/05_bus_arbitration_chain.py` | P3 | Showcase: multi-level chain |
| `examples/inference/README.md` | P2 | User-facing example guide |
| `docs/inference_architecture.md` | P2 | Architecture documentation |
| `docs/inference_user_guide.md` | P3 | User guide |

### Modified Files

| File | Phase | Change |
|---|---|---|
| `rt/activity_runner.py` | P1/P2/P3/P4 | Integrate store, structural solve, joint solve |
| `rt/action_context.py` | P1/P2/P3/P4 | Add `flow_constraint_store`, `structural_solver`, `forward_propagator`, `solver_selector` |
| `rt/scenario_runner.py` | P1/P2/P4 | Create and wire new components |
| `rt/pool_resolver.py` | P2 | Enumerate action types per pool for ICL |
| `rt/binding_solver.py` | P4 | Extend for compound resource constraints |

---

## 10. LRM Compliance Matrix (Post All Phases)

| LRM Section | Feature | After P1 | After P2 | After P3 | After P4 |
|---|---|---|---|---|---|
| §5.3.2 | Inference overview | — | ✅ Single-level | ✅ Multi-level | ✅ Full |
| §5.4 | Flow-object data constraints (producer→consumer) | ✅ | ✅ | ✅ | ✅ |
| §13.3 | State object semantics (reader/writer ordering) | — | ✅ | ✅ | ✅ |
| §15 | Object pools and binding | Existing | ✅ Extended | ✅ | ✅ |
| §16.4.1–2 | Single-action rand + randc | Existing | Existing | Existing | Existing |
| §16.4.3 | Flow-object data constraints | ✅ P1 | ✅ | ✅ | ✅ |
| §16.4.4 | Resource field constraints | Existing | Existing | Existing | ✅ Extended |
| §16.4.6 | Dynamic/inline constraints | Existing | Existing | Existing | Existing |
| §16.4.10 | Cross-action sequential constraints | — | — | ✅ P3 | ✅ |
| §17.1 | Buffer supply inference | — | ✅ P2 | ✅ | ✅ |
| §17.1 | State supply inference | — | ✅ P2 | ✅ | ✅ |
| §17.1 | Stream partner inference | — | ✅ P2 | ✅ | ✅ |
| §17.1 | Multi-level chain inference | — | — | ✅ P3 | ✅ |
| §17.3 | Constraint-driven inference | — | — | ✅ P3 | ✅ |
| Annex E | Full ICL algorithm | — | Partial | ✅ | ✅ |
