# PSS Inference Architecture

This document describes the internal design of the structural-inference and
constraint-propagation machinery in the `zuspec-dataclasses` Python runtime.

## Overview

PSS *inference* is the mechanism by which the runtime automatically inserts
actions that the user did not explicitly list in an activity.  When an action
has an unbound flow-input slot, the runtime searches the component tree for
action types that can produce the required flow object and inserts them as
sequential predecessors (or concurrent partners for streams).

The implementation is organised in three phases:

| Phase | Feature | Key files |
|-------|---------|-----------|
| P1 | Flow-object constraint back-propagation | *(deferred — see §6)* |
| P2 | Structural inference — single- and multi-level | `action_registry.py`, `icl_table.py`, `structural_solver.py` |
| P3 | Cross-action sequential constraint propagation | `forward_constraint_propagator.py` |

---

## 1. Action Registry (`rt/action_registry.py`)

`ActionRegistry` discovers every action type reachable from the root component
at scenario startup.

```
ScenarioRunner.__init__()
  └─ ActionRegistry(root_comp)
       └─ _discover_action_types(comp_type)
            ├─ walks __annotations__ for Component sub-fields (BFS)
            └─ for each Component: inspects zdc.Action[CompType] subclasses
```

**ObjFactory synthetic subclasses**: `@zdc.dataclass` wraps every user class
through an `ObjFactory` which creates a *runtime subclass* at instantiation
time.  The actual type of `NetComp()` is not `NetComp` but a synthetic
subclass with `__module__ = 'zuspec.dataclasses.rt.obj_factory'`.  The
registry therefore uses `issubclass` comparison (see `_types_compatible()`) to
match user-defined types against component instances.

---

## 2. ICL Table (`rt/icl_table.py`)

`ICLTable` pre-computes a mapping from *(consumer type, input field name)* to
a list of `ICLEntry` records.  Each entry describes one producer that can
satisfy the slot.

```
ICLTable.build(registry)
  └─ for each (consumer_type, field) with metadata kind='flow_ref' direction='input':
       └─ for each (producer_type, pfield) with kind='flow_ref' direction='output':
            if same flow-object type AND producer != consumer:
                add ICLEntry(producer_type, pfield_name)
```

**Self-exclusion**: An action type is never its own producer — this prevents
trivial single-node cycles at build time.

---

## 3. Structural Solver (`rt/structural_solver.py`)

`StructuralSolver.solve(consumer_type, ctx)` performs a DFS over the ICL to
find a feasible chain of producers for all unbound flow-input slots of
`consumer_type`.

```
solve(consumer_type, ctx)
  └─ _collect_unbound_inputs(consumer_type, ctx)
  └─ for each unbound (field_name, flow_type):
       └─ _solve_recursive(field_name, flow_type, depth, visited)
            ├─ look up ICL entries for (consumer_type, field_name)
            ├─ randomly select a candidate producer (seed-controlled)
            ├─ recursively check if producer itself needs inference
            └─ return InferredAction(...)
```

**Cycle guard**: `visited` set of `(consumer_type, field_name)` prevents
infinite recursion.

**Depth limit**: `max_depth=5` prevents pathologically deep chains.

**Ordering**:
- `Stream` flow objects → `concurrent` (parallel partner)
- `Buffer` and `State` flow objects → `sequential_before`

### `InferredAction` dataclass

```python
@dataclass
class InferredAction:
    action_type:  type          # the producer to insert
    ordering:     str           # 'sequential_before' | 'concurrent'
    output_field: str           # field name on the producer
    input_field:  str           # field name on the consumer
    flow_obj_type: type         # the flow-object class
    prerequisites: list[InferredAction]  # chain predecessors
```

---

## 4. Activity Runner Integration (`rt/activity_runner.py`)

### 4.1 Inference trigger point: `_traverse_anon()`

`_traverse_anon()` is called for every anonymous `do(Type)` statement.  Before
running the traversal it:

1. Calls `_collect_unbound_flow_inputs(action_type, ctx)` to detect any
   flow-input fields not already covered by `ctx.flow_bindings`.
2. If unbound slots exist and a `StructuralSolver` is available in `ctx`,
   calls `_apply_inferred_actions()`.

Only anonymous traversals trigger inference.  Handle-based traversals
(`_traverse_handle()`) use the pre-defined handles and don't infer.

### 4.2 Applying inferred actions: `_apply_inferred_actions()`

For each `InferredAction` with `ordering == 'sequential_before'`:

1. Recursively apply any prerequisites (depth-first).
2. Traverse the producer action via `_traverse()`.
3. Create a `BufferInstance` wrapping the produced flow object.
4. Add it to `ctx.flow_bindings` so the consumer picks it up.

Stream inference (`ordering == 'concurrent'`) raises `NotImplementedError` —
see §6.

### 4.3 Orphan output buffers: `_create_orphan_output_buffers()`

When an action with a `flow_output` field is traversed but there is no
explicit consumer, the field would be `None` and `body()` would crash.
`_create_orphan_output_buffers()` pre-populates such fields with a fresh
object created via `make_resource()`.

### 4.4 Context propagation

`structural_solver` is propagated through **all** child `ActionContext`
constructions, including:
- `_seq()` → per-statement contexts
- `_parallel()` → per-branch `branch_ctx`
- `_schedule()` → per-stage `stage_ctx`
- `_traverse()` → child action's `child_ctx`

---

## 5. Forward Constraint Propagation (`rt/forward_constraint_propagator.py`)

P3 enables constraints of the form `b.in_val == a.out_val + 1` where
`a` is an earlier action in the same sequence block.

### 5.1 `ForwardConstraintPropagator`

Lifecycle:
1. `_seq()` creates one `ForwardConstraintPropagator` per sequence block.
2. After each action completes, `record_completed(action, label)` stores its
   scalar field values keyed by label.
3. Before the *next* action's `randomize_with_ast_constraints()`,
   `substitute(stmts)` runs `_CrossActionSubstitutor` — an AST transformer
   that rewrites `label.field` attribute-access nodes as `ast.Constant(value)`.
4. The solver sees concrete values and can solve cross-action constraints
   as simple numeric equalities.

### 5.2 `_CrossActionSubstitutor`

An `ast.NodeTransformer` that matches:

```
Attribute(value=Name(id='<label>'), attr='<field>')
```

and replaces it with `Constant(value=<stored_value>)` when the label has been
recorded.  Unrecognised labels are left untouched.

---

## 6. Not-Yet-Implemented: Stream Inference

Stream flow objects require a concurrent partner action to run *at the same
time* as the consumer, exchanging data via an async queue.  The current
`_apply_inferred_actions()` raises `NotImplementedError` for
`ordering == 'concurrent'`.

Stream inference requires:
- Spawning a parallel coroutine for the inferred producer.
- Connecting a `StreamInstance` queue between producer and consumer.
- Joining the coroutine after both sides complete.

---

## 7. Not-Yet-Implemented: P4 Joint Solve / Solver Selection

Phase P4 (planned, not implemented) covers:
- **`SolverSelector`** — heuristic choice between pure-Python solver and the
  native `zuspec-solver` C++ backend.
- **Cross-branch joint data solve** — constraints spanning parallel arms.
- **Compound resource constraints** — multi-field CSPs in `BindingSolver`.

See `pss-inference-implementation-plan.md §3.4` for the design.

---

## 8. Data-Flow Diagram

```
ScenarioRunner.run(ScenarioType)
  │
  ├─ [startup] ActionRegistry ──► ICLTable ──► StructuralSolver
  │
  └─ ActivityRunner.run(activity_ir, ctx)
       │
       ├─ _seq(block, ctx)
       │    └─ creates ForwardConstraintPropagator
       │
       ├─ _traverse_anon(stmt, ctx)
       │    ├─ _collect_unbound_flow_inputs(action_type, ctx)
       │    └─ _apply_inferred_actions(inferred, consumer, ctx)
       │         └─ _traverse(producer_type, [], ctx)  [recursive]
       │
       └─ _traverse(action_type, constraints, ctx)
            ├─ pre_solve()
            ├─ randomize / randomize_with_ast_constraints
            │    └─ ForwardConstraintPropagator.substitute(constraints)
            ├─ post_solve()
            ├─ acquire_resources()   ← lock/share fields set HERE
            ├─ _exec_action_body()
            └─ ForwardConstraintPropagator.record_completed(action, label)
```
