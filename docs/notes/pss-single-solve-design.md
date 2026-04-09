# Design: PSS Single-Solve Static Scenario Generation

Date: 2026-03-23
Status: Proposed — for review

---

## 1. Overview

### 1.1 Scope

This document designs a **single-solve** PSS scenario generation scheme targeting
**static code generators** — tools that produce completely-elaborated directed
or directed-random tests as fixed artifact outputs (C structs, register-write
sequences, JSON test vectors, Python test scripts, etc.).

The two companion designs (`pss-python-execution-design.md` and
`pss-to-c-execution-design.md`) decompose the PSS semantic solve into a
sequence of per-action runtime solves for efficiency and memory-boundedness on
embedded targets.  That incremental approach is incompatible with static code
generation because it requires a live solver on the target and cannot produce
the fully-determined, seed-reproducible output that directed tests require.

This design occupies the opposite extreme of the design space:

| Property | Incremental execution | Single-solve static gen |
|---|---|---|
| Solver runs on | Target (runtime) | Solve platform (generation time) |
| Solve granularity | One action at a time | All actions together (partitioned) |
| Cross-action constraints | Limited (forward-prop only) | Fully supported |
| Generated artifact | Coroutine/executor code | Value tables + execution trace |
| Runtime solver needed | Yes | No |
| Reproducible from seed | Per-step | Globally |
| Target memory footprint | High (solver) | Low (static tables) |
| Generation time | O(1) per action | O(scenario) at gen time |

### 1.2 Relationship to LRM

LRM §16.4 specifies randomization semantics in terms of traversal order:
rand fields of an action are solved when the action is traversed.  The LRM
also states (§16.4.7) that a processing tool has freedom in the order it
selects random values, subject to scheduling constraints.  The single-solve
approach exploits this freedom by resolving all values at generation time,
provided the resulting assignment satisfies all constraints that would hold
in any compliant incremental execution.

LRM §13.636–13.639 explicitly names the two targets of this design:

- **Directed-random test**: actions fully determined; data fields randomized
  (still subject to constraints; solver required at generation time).
- **Directed test**: actions and all data fields fully specified; tool emits
  fixed values; no solver required at runtime.

### 1.3 Use Cases

1. **Embedded bare-metal tests** where the solver library is too large to link.
2. **Regression suites** that must be deterministic from a known seed.
3. **Coverage-closure tests** where value distributions are externally computed
   and injected, not randomized.
4. **Simulation acceleration** where the test is pre-compiled into a trace for
   fast replay (e.g., an RTL simulation stimulus file).
5. **Hardware bring-up** where the test must survive without an OS or
   randomization infrastructure.

---

## 2. Phases of Single-Solve Generation

The generation pipeline has four phases.  Phases 1–2 are shared with the
structural inference design (`pss-inference-design.md`).  Phases 3–4 are new.

```
 ┌─────────────────────────────────────────────────────────┐
 │  Phase 1: Elaboration                                   │
 │  • Component tree instantiation                        │
 │  • Pool binding table construction                     │
 │  • ICL construction per flow-object slot               │
 │  • Type-level constraint feasibility check             │
 │  • compile-if evaluation; abstract type enumeration    │
 └───────────────────────────┬─────────────────────────────┘
                             │ static tables
 ┌───────────────────────────▼─────────────────────────────┐
 │  Phase 2: Structural Solve                              │
 │  • Action instance graph construction                  │
 │  • select / replicate / abstract-type resolution       │
 │  • ICL depth-first search + constraint-driven pruning  │
 │  • Inferred action insertion (buffer/state/stream)     │
 │  • Scheduling constraint graph validation              │
 │  • randc cycling order assignment                      │
 └───────────────────────────┬─────────────────────────────┘
                             │ structured scenario graph
 ┌───────────────────────────▼─────────────────────────────┐
 │  Phase 3: Data Solve                                    │
 │  • pre_solve exec-block execution per action           │
 │  • Constraint system construction (all actions)        │
 │  • Partition into independent subproblems              │
 │  • Topological / wave-ordered solve                    │
 │  • Flow-object constraint propagation                  │
 │  • Head-action AllDifferent (parallel blocks)          │
 │  • Global backtracking if subproblem UNSAT             │
 └───────────────────────────┬─────────────────────────────┘
                             │ fully-valued scenario
 ┌───────────────────────────▼─────────────────────────────┐
 │  Phase 4: Code / Artifact Generation                   │
 │  • Emit action sequence with concrete field values     │
 │  • Emit post_solve exec-block calls                    │
 │  • Emit body exec-block calls                          │
 │  • Emit coverage sampling calls                        │
 └─────────────────────────────────────────────────────────┘
```

---

## 3. Phase 1: Elaboration

Phase 1 is identical to the elaboration phase described in
`pss-inference-design.md` §4.1.  Key outputs used by the single-solve pipeline:

- **Pool binding table**: `(component_instance, action_type, field_name)` →
  `pool_instance`.
- **ICL table**: `(action_type, flow_slot_name)` → `[candidate_action_types]`.
- **Component reachability**: `action_type` → `[component_instances]`.
- **Type-level constraint feasibility matrix**: pairs of action types sharing a
  flow-object pool that are mutually infeasible (data constraints contradict at
  the type level).

---

## 4. Phase 2: Structural Solve

### 4.1 Goal

Determine the complete set of action instances and their scheduling
relationships — the **scenario graph** — before any data values are chosen.

### 4.2 Structural Decisions Required

| Decision | Where Made | Notes |
|---|---|---|
| Select branch choice | Phase 2 | Weighted random; constraint-checked |
| Abstract type concretization | Phase 2 | Choose concrete subtype for each abstract action handle |
| Replicate count (rand expression) | Phase 2 | Must be resolved before instances can be created |
| ICL candidate selection (buffer/state/stream) | Phase 2 | Depth-first search; backtrack on UNSAT |
| Inferred action ordering | Phase 2 | Buffer/state: sequential before; stream: parallel partner |
| randc cycling order | Phase 2 | Assign visit-order indices across instances of the same type |
| Schedule block ordering | Phase 2 | Topological sort of mixed sequential/concurrent constraint graph |

### 4.3 Select / Replicate Resolution

`select` and `replicate` constructs with rand count expressions represent
**structural randomness**: the scenario structure itself varies.  In the
single-solve scheme both must be resolved in Phase 2 before Phase 3 begins,
because Phase 3 requires a fixed set of action instances.

For `select`, use weighted random sampling over the branch weights.  For
branches with guard constraints, check type-level feasibility before choosing.

For `replicate` with a rand count, the count is a structural decision.  Treat
it as a bounded integer drawn from the constraint system of the containing
action's rand fields, resolved via a single constraint solve on the count
variable alone before expanding instances.

### 4.4 Scenario Graph Representation

The structural solve emits a **Scenario Graph** — a directed, labeled graph:

```
Nodes:    ActionInstance(id, type, comp_instance)
Edges:    ScheduleEdge(from, to, kind ∈ {sequential, concurrent})
Slots:    FlowSlot(action_id, field_name, pool_id, flow_type)
Bindings: FlowBinding(producer_slot, consumer_slot)
```

This graph is the sole input to Phase 3.

---

## 5. Phase 3: Data Solve

Phase 3 is the core of the single-solve design.  Given the scenario graph, it
assigns concrete values to every rand field of every action instance and every
rand field of every flow object instance.

### 5.1 Pre_solve Execution

LRM §16.4.12 requires `pre_solve` exec blocks to run before randomization.
The single-solve equivalent:

1. Instantiate all action instances (all rand fields at their default/zero
   values).
2. Walk the scenario graph in topological order of sequential edges.
3. For each action instance, run its `pre_solve` exec block.  Any assignments
   in `pre_solve` become **fixed constants** in that action's constraint
   system.

`pre_solve` for inferred actions is governed by the same topological ordering
as for explicit actions (LRM §17, opening paragraph).

### 5.2 Constraint System Construction

For each action instance `a`, construct a `ConstraintSystem` containing:

1. **Own rand fields**: all rand-qualified fields of `type(a)`, with their
   declared domain ranges as initial bounds.
2. **pre_solve assignments**: treated as equality constraints (`field == value`).
3. **Class-level constraints**: all `@constraint` methods of `type(a)` and
   all supertypes, evaluated symbolically.
4. **Flow-object constraints**: for each output flow slot, add the rand fields
   of the flow object and their constraints.  For each input flow slot, add
   the constraints from the **producer's** solved or pending flow-object values
   (see §5.5).
5. **Resource field constraints**: rand fields of resource objects locked/shared
   by this action (LRM §16.4.4).
6. **Inline / `with`-block constraints**: any constraints added via inline
   constraint expressions in the containing activity (LRM §16.4.11).
7. **randc constraints**: no-repeat constraints derived from randc cycling order
   assigned in Phase 2 (see §5.6).

### 5.3 Partition-Based Solving

#### 5.3.1 Level 0: Within-Action Partition

Apply the existing `Partitioner` (from `zuspec-solver/partitioner.py`) to each
action's `ConstraintSystem` independently:

```python
unconstrained, subproblems = Partitioner().partition(system)
for var_name in unconstrained:
    randomize_unconstrained(var_name)
for component in subproblems:
    solve_component(system, component)
```

Fields in the unconstrained group need no solver call — they are drawn
uniformly from their declared domain.  This is a significant fast path in
practice: many PSS actions have large rand fields with no inter-field
constraints.

#### 5.3.2 Level 1: Cross-Action Partition

Build a **cross-action dependency graph** where action instances are nodes and
an edge exists between two instances if:

- They share a flow object binding (producer → consumer constraint chain), or
- There is an explicit cross-action constraint (LRM §16.4.8: `a.handle.field`
  in a constraint of the parent action), or
- They share a resource object whose rand fields appear in both actions'
  constraints.

Apply union-find (DSU) over this graph to find **independent action clusters**.
Each cluster is an independent subproblem that can be solved without reference
to other clusters.

For typical PSS models, this partition isolates:
- Parallel branches with no cross-branch data constraints (common case).
- Actions in distinct component subtrees with no shared pools.
- Sequential chains connected only by one-way constraint propagation.

#### 5.3.3 Level 2: Temporal Wave Partition

Within each cross-action cluster, order action instances by their **logical
start wave**: the earliest wave index at which the action can execute, given
sequential ordering constraints.

```
Wave 0: root action rand fields (no predecessors)
Wave 1: actions whose only predecessors are in Wave 0
Wave k: actions whose predecessors are all in waves < k
```

Within a wave, actions are independent (no sequential edge between them) and
can be solved in any order.  Actions in different waves within the same cluster
can be solved sequentially: solve Wave k's constraint systems, extract solved
values, inject as constants into Wave k+1's constraint systems.

This reduces each cluster from a joint multi-action CSP to a sequence of
smaller, mostly-independent CSPs with one-directional constraint flow.

### 5.4 Solving Order Summary

```
for cluster in cross_action_partition(scenario_graph):
    for wave in temporal_waves(cluster):
        for action in wave:
            system = build_constraint_system(action)
            unconstrained, subproblems = Partitioner().partition(system)
            randomize_unconstrained(unconstrained)
            for sp in subproblems:
                solve(system, sp)              # one solver call per component
        propagate_solved_values_forward(wave)  # inject into next wave
```

### 5.5 Flow-Object Constraint Propagation

Flow-object constraints span multiple actions: the producing action provides
constraints on the flow-object's rand fields; the consuming action adds
further constraints on the same fields.

**For buffer and state (sequential):**

1. When solving the producing action, include the flow-object's rand fields
   in the producer's constraint system.  Solve them jointly with the
   producer's own rand fields.
2. After the producer's solve, record the solved flow-object field values as
   **equality constants**.
3. When building the consuming action's constraint system, inject those
   equality constants plus the consumer's own constraints on the flow-object
   fields.  If the injected constants are inconsistent with the consumer's
   constraints, propagate a `FLOW_UNSAT` error back to Phase 2 for
   structural backtracking (a different producer may be selected).

**For stream (concurrent):**

Stream producer and consumer execute simultaneously and share the same flow
object.  Their constraints on the stream object's rand fields must be
satisfied jointly.  This is handled as a joint solve:

1. Create a merged constraint system containing the rand fields of the stream
   object, plus all constraints from both the producer and the consumer.
2. Solve the merged system as a single subproblem.
3. Distribute the solved values back to both action instances.

**For state with multiple consumers:**

When multiple actions read the same state pool instance (allowed when they
execute concurrently), all consumer constraints are merged and solved jointly
over the shared state's rand fields, with the producer's solved values as
equality constants.

### 5.6 randc Handling

In incremental execution, `randc` fields cycle across repeated traversals.
In single-solve, all instances are present simultaneously.  The Phase 2
structural solve assigns a **visit-order index** to each instance of an action
type that has randc fields.

Phase 3 converts this into a `no_repeat` constraint:

```
For action type T with randc field f, and instances t₀, t₁, ..., tₙ₋₁
    ordered by visit-order index:

  constraint AllDifferent(t₀.f, t₁.f, ..., tₙ₋₁.f)
```

This AllDifferent constraint is added to the cross-action constraint system
for the group of instances.  If n ≤ 4, it can be solved with the existing
bipartite matching approach.  If n is larger, use Régin's AllDifferent
propagator in the native solver.

### 5.7 Head-Action Resource Binding (Parallel Blocks)

For each parallel block, the head action on each branch must claim a
**distinct resource instance**.  This is unchanged from the incremental
design's `BindingSolver`:

1. Collect the resource claim fields of each branch's head action.
2. Construct an AllDifferent constraint over the instance-id variables across
   all branches.
3. Invoke the native solver (or bipartite matching for small N).
4. The solved instance ids are fixed constants in each head action's
   constraint system.

Unlike the incremental design, this is done entirely at generation time and
the result is baked into the emitted artifact.

### 5.8 Backtracking Strategy

The data solve can fail (UNSAT) when:
- A flow-object constraint is inconsistent between producer and consumer.
- A joint stream solve has no solution.
- A randc AllDifferent constraint is unsatisfiable (n > domain size).
- A complex cross-action constraint cluster is globally UNSAT.

The backtracking hierarchy:

```
Level 3: Re-solve with different random seed (fast; change local ordering)
Level 2: Backtrack within structural cluster: change flow binding or
         ICL candidate for a specific flow slot
Level 1: Full Phase 2 re-solve (new structural choices: select branch,
         abstract type, replicate count)
Level 0: Error — no valid scenario exists (report UNSAT explanation)
```

The solver should attempt Level 3 first (up to a configurable limit, e.g. 32
tries) before escalating to Level 2.

For diagnostics, maintain an **UNSAT core** annotation: when the native solver
returns `SOLVE_UNSAT`, extract the minimal set of conflicting constraints
(using UNSAT core extraction, available via CDCL-style solvers) and report
them as actionable errors referencing source-level PSS constructs.

---

## 6. Solve Algorithm Details

### 6.1 Decision Procedure Per Subproblem

| Subproblem Type | Recommended Algorithm | Fallback |
|---|---|---|
| Unconstrained scalars | Uniform random from domain | — |
| Small bounded integers (≤16 vars, ≤32-bit domains) | Bounds propagation (AC-3) + random order value assignment | Pure Python solver |
| Medium CSP (≤64 vars) | CDCL with integer propagators (native solver) | Pure Python backtracking |
| Large CSP (>64 vars) | Phase-saving CDCL + restarts | CDCL without restarts |
| AllDifferent ≤4 | Bipartite matching (Hopcroft-Karp inlined) | — |
| AllDifferent 5–100 | Régin's propagator (native solver) | — |
| AllDifferent >100 | Precomputed permutation table at gen-time | Error if infeasible |
| Linear arithmetic | Simplex preprocessing → CDCL | Bounds narrowing |
| Nonlinear (mul, div, mod) | Interval propagation + case split | Monte Carlo feasibility |

### 6.2 Bounds Propagation Pass (Fast Pre-Solve)

Before invoking the full CSP solver on any subproblem, run a single AC-3 pass:

1. Initialize domains from declared ranges plus pre_solve equality constants.
2. Propagate constraints: for each binary constraint `f(x, y)`, narrow domains
   of `x` and `y` given the other's domain.
3. If any domain becomes empty → immediately UNSAT, no solver call needed.
4. If all domains are singletons → all values are determined, no solver call.
5. Otherwise, invoke the CSP solver with tightened bounds.

In practice, AC-3 resolves a significant fraction of subproblems without a
full solver invocation (especially for well-constrained PSS models targeting
specific address ranges, alignment requirements, etc.).

### 6.3 Lazy Constant Injection

When a sequential predecessor's values are solved, they become constants in
the successor's constraint system.  Rather than re-building the constraint
system, implement **lazy constant injection**:

- The `ConstraintSystem` maintains a `fixings` dict: `var_name → value`.
- When building the successor's system, existing `fixings` from predecessors
  are pre-loaded before adding the successor's constraints.
- This allows the per-class `SolveProblem` cache (already in the native
  backend) to be reused: the cached problem is compiled once, and at solve
  time, fixings are injected as equality constraints into a fresh `SolveCtx`.

### 6.4 Parallel Solve (Opportunity)

Independent action clusters from §5.3.2 have no data dependencies on each
other.  They can be solved in parallel using Python's `concurrent.futures`
(process pool, to bypass the GIL) or, for the native solver, by launching
concurrent `SolveCtx` instances on separate threads.

Each cluster needs its own `SolveProblem` buffer and `SolveCtx` buffer
(native solver buffers are not thread-safe).  Since `SolveProblem`s are
already per-class-cached, parallel solve creates new `SolveCtx` instances
per thread but shares the compiled `SolveProblem`.

Expected speedup: roughly proportional to the number of independent clusters,
bounded by hardware parallelism.  For typical PSS models with 2–8 branches,
this can reduce wall-clock time by 2–4×.

---

## 7. Phase 4: Code / Artifact Generation

Phase 4 consumes the fully-valued scenario graph and emits the target artifact.

### 7.1 Execution Trace Representation

The solved scenario is linearized into an **execution trace**: a sequence of
action invocations, each carrying a concrete field-value record.

```
Trace := [TraceEntry]
TraceEntry := {
    action_type: str,
    comp_instance: str,
    fields: dict[str, int | bool | str],
    flow_inputs: dict[str, dict[str, int]],   # field → value
    flow_outputs: dict[str, dict[str, int]],  # field → value
    resource_claims: list[(str, int)],        # (pool, instance_id)
}
```

This trace is a backend-agnostic intermediate representation that can be
consumed by multiple artifact emitters.

### 7.2 Artifact Emitter Targets

| Target | Description | Backend |
|---|---|---|
| C struct table | `static const dma_xfer_t tests[] = {...}` | zuspec-be-sw / codegen |
| Python test script | `def test_scenario(): action_a(addr=0x1000, ...)` | zuspec-dataclasses rt |
| JSON vector file | Machine-readable register/field values | Generic |
| SV transaction table | UVM sequence item initialization | zuspec-be-sv |
| RTL stimulus | Cycle-accurate signal toggles | zuspec-be-hdlsim |
| Markdown trace | Human-readable scenario description | Debug |

### 7.3 Post_solve and Body Exec Blocks

`post_solve` exec blocks must run after the data solve but before the body.
In the static artifact, they are evaluated at generation time:

1. Run `post_solve` for each action in topological order (same as pre_solve).
2. Any side-effects (assignments to non-rand fields) are reflected into the
   trace entry.
3. `body` exec blocks are emitted in the artifact as calls to target-language
   functions (template exec blocks) or as inline code (native exec blocks).

---

## 8. Comparison with Incremental Execution

| Aspect | Incremental | Single-Solve |
|---|---|---|
| **Solver location** | Target runtime | Generation platform |
| **Solve granularity** | Per action | Partitioned clusters |
| **Cross-action constraints** | Forward-prop only | Fully supported |
| **Flow-object constraints** | Accumulator → forward | Joint solve (stream) or forward-propagated constants (buffer/state) |
| **randc** | Per-traversal cycle | AllDifferent across instances |
| **select branch** | Runtime weighted random | Generation-time structural decision |
| **replicate count** | Runtime rand eval | Generation-time structural decision |
| **Pre/post_solve** | Runtime exec | Generation-time exec |
| **Runtime solver** | Required | Not required |
| **Target memory** | Solver lib + buffers | Static tables only |
| **Reproducibility** | Per-step seed | Global seed → deterministic trace |
| **Backtracking** | Per-action | Hierarchical (global) |

---

## 9. Solver Selection Policy

| Condition | Pure Python solver | Native solver |
|---|---|---|
| ≤ 8 rand fields in subproblem | Preferred | Optional |
| 9–32 rand fields | Adequate | Preferred |
| > 32 rand fields | Slow (>100ms risk) | Required |
| AllDifferent ≤ 4 | Adequate | Equivalent |
| AllDifferent > 4 | Possible (slow) | Required |
| Cross-action joint CSP | Possible (small) | Required |
| Nonlinear constraints (mul, mod) | Slow | Preferred |
| Native lib not available | Mandatory | N/A |

The native backend (`zuspec-solver`) already falls back to the Python backend
when `libzsp_solver.so` is not found.  The single-solve pipeline inherits this
behaviour.

---

## 10. Capacity and Performance Estimates

### 10.1 Pure Python Solver

The pure Python solver (`zuspec-dataclasses/solver/api.py`) uses AC-3 bounds
propagation with backtracking search.

| Scenario | Actions | Vars/action | Est. solve time |
|---|---|---|---|
| Simple directed sequence | 10 | 5 | 50–200ms |
| Directed-random with constraints | 50 | 10 | 0.5–5s |
| Complex pipeline with flow objects | 100 | 20 | 5–60s |
| Large parallel scenario | 200 | 15 | 20–300s |

**Bottlenecks:**
- The Python solver's inner loop is pure Python; each constraint evaluation
  involves dynamic attribute lookup and Python integer arithmetic.
- Backtracking in complex CSPs is exponential; pathological models can time
  out at the default 1000ms limit.
- The per-class `ConstraintSystem` build (parsing `@constraint` methods via
  AST inspection) adds ~5–20ms per distinct action type (amortized after
  caching).

**Practical capacity:** single-solve of scenarios up to ~50 actions with
simple-to-moderate constraints is feasible within a few seconds.  Beyond
that, the native solver is required.

### 10.2 Native C Solver (`zuspec-solver`)

The native solver uses a CDCL engine with bit-vector propagators, phase
saving, and configurable restart policies.

| Scenario | Actions | Vars/action | Est. solve time |
|---|---|---|---|
| Simple directed sequence | 10 | 5 | 1–5ms |
| Directed-random with constraints | 50 | 10 | 10–100ms |
| Complex pipeline with flow objects | 100 | 20 | 50–500ms |
| Large parallel scenario | 200 | 15 | 100ms–2s |
| Very large scenario | 1000 | 10 | 0.5–10s |

**Key advantages:**
- Per-class `SolveProblem` caching means type-level compilation happens once;
  subsequent instances only pay for `SolveCtx` creation (~5µs) + solve.
- `SolveCtx` creation from a pre-compiled `SolveProblem`: ~10µs.
- Solve time for a simple 10-variable system: ~50–200µs.
- With bounds propagation pre-pass eliminating trivial cases: many actions
  cost 1–5µs total.

**Practical capacity:** scenarios of 500–2000 actions are tractable within
1–30 seconds depending on constraint complexity.  With parallel cluster solve
(§6.4), throughput scales further.

### 10.3 Partitioning Impact on Performance

The cross-action partition (§5.3.2) is the key performance lever:

| Partition quality | Example | Speedup over joint |
|---|---|---|
| Fully independent actions | All actions independent | N× (N = action count) |
| 2 clusters of N/2 | Two parallel test threads | ~2× |
| One big cluster | All actions share a flow pool | 1× (no benefit) |
| Temporal wave within cluster | Sequential pipeline | Reduces each wave size |

In practice, PSS models for hardware test generation tend to decompose well:
each component subtree is a natural independent cluster, and within a
subtree, sequential pipelines form small temporal waves (depth 2–5).  This
suggests typical partition speedups of 4–20× over a naive global solve.

### 10.4 Comparison with Incremental Execution

| Metric | Incremental (py) | Incremental (C) | Single-solve (py) | Single-solve (C) |
|---|---|---|---|---|
| Time per action | 0.5–50ms | 50–500µs | (amortized) 5–100ms | 0.1–10ms |
| 100-action scenario | 50ms–5s | 5–50ms | 0.5–60s | 10–500ms |
| Cross-action constraints | Limited | Limited | Full | Full |
| Parallelism exploit | No | No | Yes (clusters) | Yes |

The single-solve approach with the native solver is within 2–10× of the
incremental C approach for scenarios up to ~200 actions, while supporting
richer cross-action constraints that the incremental approach cannot handle.

---

## 11. Implementation Architecture

### 11.1 New Modules (in `zuspec-dataclasses`)

```
src/zuspec/dataclasses/
  ssg/                       # Single-Solve Generator package
    scenario_graph.py        # ScenarioGraph + ActionInstance data structures
    structural_solver.py     # Phase 2: ICL search, select/replicate resolution
    data_solver.py           # Phase 3: constraint system build + partitioned solve
    flow_propagator.py       # Flow-object constraint forwarding
    randc_manager.py         # AllDifferent constraint generation for randc
    execution_trace.py       # Phase 3→4 intermediate representation
    trace_emitter.py         # Base class for Phase 4 artifact emitters
    emitters/
      python_emitter.py      # Python test script emitter
      c_struct_emitter.py    # C struct table emitter
      json_emitter.py        # JSON vector file emitter
      markdown_emitter.py    # Human-readable trace emitter
```

### 11.2 Reused Components

| Component | Location | Reuse |
|---|---|---|
| `Partitioner` | `zuspec-solver/partitioner.py` | Within-action and cross-action partition |
| `randomize()` | `zuspec-dataclasses/solver/api.py` | Per-subproblem solve |
| `SolveProblem` / `SolveCtx` | `zuspec-solver/ctx.py` | Native solver integration |
| `ConstraintSystemBuilder` | `zuspec-dataclasses/solver/frontend/` | Constraint system construction |
| `ICLTable` | `zuspec-dataclasses/rt/icl_table.py` | Phase 2 structural search |
| `StructuralSolver` | `zuspec-dataclasses/rt/structural_solver.py` | Phase 2 (adapt for offline use) |

### 11.3 Entry Point

```python
from zuspec.dataclasses.ssg import SingleSolveGenerator

gen = SingleSolveGenerator(
    root_action_type=MyTest,
    seed=42,
    solver_backend="native",   # or "python"
    max_backtrack_level=2,
    max_seed_retries=32,
)
trace = gen.generate()
gen.emit_python(trace, "test_output.py")
gen.emit_c_struct(trace, "test_vectors.h")
```

---

## 12. Open Issues

### 12.1 Pre_solve Exec Blocks and Inferred Action Order (HIGH)

`pre_solve` exec blocks may assign values to fields that later appear in
constraints.  For inferred actions, the PSS LRM requires `pre_solve` to
execute in scheduling order (LRM §17, opening paragraph).  However, the
inferred action's existence is not known until Phase 2 completes, and
`pre_solve` cannot run until Phase 3 begins.

This creates a bootstrapping tension: if `pre_solve` of action A assigns a
value that constrains an inferred predecessor, the tool cannot know which
actions to infer until it runs `pre_solve`, but `pre_solve` cannot run
before the structure is fixed.

**Proposed resolution**: LRM §17 states that `pre_solve` constraints are
evaluated after the inference decision; assignments in `pre_solve` that
affect inference are only indirectly handled through constraint-feasibility
checking at the type level (Phase 1).  Full dynamic `pre_solve`–driven
inference is a corner case that may require an iterative structural/data
co-solve loop (Phase 2 ↔ Phase 3) for full compliance.

### 12.2 Select Branch Constraints (MEDIUM)

The LRM permits `select` branches to carry guard expressions and constraints
that influence branch selection.  In Phase 2, branch selection uses weighted
random sampling, but the guard constraints may reference rand fields that
are not yet solved.

**Proposed resolution**: Evaluate guard expressions symbolically (check type-
level feasibility only).  If a branch is feasible at the type level, it is
a candidate.  If constraint conflicts appear during Phase 3, backtrack to
Phase 2 and re-select.  An alternative is to include the branch-selection
variable in the joint data solve, with indicator constraints enabling the
selected branch's constraints.

### 12.3 Cross-Branch Data Constraints (MEDIUM)

LRM §16.4.8 allows constraints to reference fields of action handles in
sibling branches of a parallel block (e.g. `constraint a.addr + b.len < 0x1000`
where `a` and `b` are in different parallel branches).  These constraints
connect the two branches' subproblems, breaking the parallel-branch
independence assumption.

**Proposed resolution**: Detect cross-branch handle references during
Phase 1 elaboration.  Mark affected branch pairs as "coupled" and include
them in the same cross-action cluster for Phase 3.  For the joint solve,
build a merged constraint system spanning both branches' rand fields.

### 12.4 Replicate Count as a Complex Expression (LOW)

If the replication count references fields of outer actions that are not
yet solved in Phase 2, the count cannot be determined without some data
information.

**Proposed resolution**: Treat the count as a Phase 2 structural integer
bounded by declared limits (`max_reps`).  Solve the count variable standalone
(ignoring cross-action constraints) to get a concrete count, then expand
instances.  If Phase 3 later finds the count is inconsistent, backtrack.

### 12.5 randc Domain Exhaustion (MEDIUM)

If the number of action instances of a type with `randc` fields exceeds the
field's domain size, the AllDifferent constraint is trivially UNSAT.

**Proposed resolution**: Detect this condition in Phase 2 when assigning visit
indices.  If `n > domain_size`, report a clear error with the action type,
field name, domain, and instance count.  Do not attempt to solve.

### 12.6 Flow Object Constraint Inconsistency Diagnosis (MEDIUM)

When a flow-object constraint between producer and consumer is UNSAT, the
error must be reported with enough context to identify the conflicting
actions and constraints at the PSS source level.

**Proposed resolution**: When `FLOW_UNSAT` is detected, save the merged
constraint system and the conflicting bounds for both producer and consumer
constraints.  Extract the UNSAT core (native solver supports this) and map
variable IDs back to PSS field names and source locations.

### 12.7 Coverage-Guided Solving (LOW — Opportunity, Not Issue)

The design currently treats coverage goals as a post-generation check.  A
coverage-guided solver would bias the data solve toward uncovered regions.
This requires coupling the data solver with the coverage model, which is not
yet designed.

### 12.8 Large Flow Constraint Chains (MEDIUM)

When many actions share a single pool and the same flow object instance is
passed through a long chain (producer → consumer1 → consumer2 → ...), each
consumer adds constraints to the accumulated constraint set.  The accumulated
system can grow large (O(n · fields) constraints), potentially exceeding the
native solver's buffer.

**Proposed resolution**: Add a configurable `max_flow_chain_depth` limit.
Beyond the limit, truncate the accumulated constraints and report a warning.
This is architecturally the same as the LRM's inferencing depth limit.

---

## 13. Overlooked Opportunities

### 13.1 Template-Based Per-Action-Type Solve

The native solver already caches a compiled `SolveProblem` per action type.
This can be extended: at Phase 1 elaboration time, compile one `SolveProblem`
per action type incorporating all static constraints.  Phase 3 then only
needs to create a fresh `SolveCtx`, inject flow-object constants (as equality
constraints, which compile in microseconds), and call `solver_solve`.

This amortizes the type-level compilation cost completely.  For a scenario
with 100 instances of 5 action types, compile cost is paid 5 times instead
of 100.

### 13.2 Incremental Constraint Propagation Between Waves

As each temporal wave is solved, its values can be propagated as unit clauses
(singleton domains) into the constraint systems of subsequent waves.  This is
equivalent to partial evaluation of the constraint systems.

For sequential chains, this means each action's constraint system is partially
evaluated using the predecessor's solved values, potentially reducing domain
sizes dramatically before the solver is invoked.  In the extreme case, if the
predecessor's values fully determine all cross-action constraints, the
subsequent CSP may be trivially solvable (singleton domains for all affected
variables).

### 13.3 Precomputed Solution Tables for Small Domains

For action types where all rand fields have small domains (e.g., 4-bit enum
fields), the complete set of valid solutions can be precomputed at Phase 1
(elaboration time) and stored as a static table.  Phase 3 then samples from
this table with a simple random index, with no solver invocation at all.

Threshold: if the product of all rand field domains is ≤ 1024, enumerate all
solutions and cache the valid set.  This is always faster than CSP search
for small domains.

### 13.4 Parallel Cluster Solve

As noted in §6.4, independent action clusters can be solved in parallel.
For Python, use `concurrent.futures.ProcessPoolExecutor` (not
`ThreadPoolExecutor`, to avoid GIL contention on the native solver's ctypes
calls).  Each worker process receives its cluster's constraint systems and
returns solved values.

### 13.5 UNSAT Core as Debugging Aid

When the global solve fails after all backtracking levels are exhausted, the
native solver's CDCL engine can extract a minimal UNSAT core: the smallest
subset of constraints that are jointly unsatisfiable.  Mapping this core back
to PSS source locations produces actionable error messages:

```
ERROR: Scenario is UNSAT. Conflicting constraints:
  - dma_xfer.src_addr aligned(64) [dma.pss:12]
  - pipeline.buf.base + offset == src_addr [pipeline.pss:45]
  - offset in [0..32] [pipeline.pss:47]
  No assignment to src_addr satisfies all three constraints.
```

This is far more useful than "UNSAT — try a different seed."

### 13.6 Soft Constraint and Coverage Hint Integration

PSS coverage groups (§18) express which values are interesting, not which
are required.  Treating coverage bins as **soft constraints** (preferably
satisfied, but not required) allows the data solver to bias toward uncovered
regions without breaking hard constraints.

Implementation: add coverage bin membership as weighted objectives in a
pseudo-Boolean optimization layer on top of the CDCL solver.  This requires
the native solver to support objective functions, which is not yet designed.

### 13.7 Structural Solve Caching

For PSS models with repetitive structure (e.g., a `repeat(N) { do xfer_a; }`
loop), all N action instances have the same type and the same static
constraint pattern.  The structural solve for all N instances is identical
except for index-specific randc ordering.

Cache the structural solve result (the subgraph pattern) and instantiate it
N times with only randc order varied.  This can reduce Phase 2 time for
large loops from O(N) to O(1) + O(N · randc assignment).

---

## 14. Summary

The single-solve static generation scheme is the correct approach for directed
and directed-random tests targeting environments without a runtime solver.  Its
main engineering challenges are:

1. **Partitioning correctly** to exploit independence and avoid intractable
   joint solves.
2. **Flow-object constraint propagation** with backward UNSAT reporting.
3. **randc AllDifferent** across multiple instances.
4. **Pre_solve bootstrapping** for inferred actions.

With the native solver and effective partitioning, the scheme is practical for
scenarios up to ~1000 actions in seconds.  With the pure Python solver, it is
practical for ~50 actions.  The key efficiency gains come from the per-class
solve template cache, temporal wave partitioning, and (optionally) parallel
cluster solve.
