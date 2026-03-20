# PSS Inference Design for Incremental Execution

## 1. Overview

The PSS LRM describes inference as a mechanism by which a tool completes a **partially-specified activity** by deducing additional action instances, flow-object bindings, and resource assignments that are required to make the scenario legal.  The LRM's conceptual model is a single unified solve over the entire scenario; however, the incremental-execution designs (see `pss-python-execution-design.md` and `pss-to-c-execution-design.md`) deliberately decompose that single solve into a sequence of smaller per-action solves.  This document analyses the types of inference PSS requires, categorises them by complexity and timing, and proposes a layered inference architecture that supports both the pure-Python runtime (targeting standard workstations) and the C/native runtime (targeting resource-constrained embedded systems).

---

## 2. What PSS Inference Means

### 2.1 LRM Definition

From LRM §5.3.2:

> "A PSS model is evaluated starting with the top-level root action… Additional actions may be inferred as necessary to support the data flow and binding requirements of all actions explicitly traversed in the activity, as well as those previously inferred."

Three normative rules constrain inference:

1. **Necessity**: An implementation shall not infer an action or object binding that is not required, either directly or indirectly, to make the activity specification legal.
2. **Completeness**: Inference chains continue until no unbound flow-object references remain or the inferencing limit is exceeded (error if exceeded).
3. **Constraint consistency**: Inferred actions or flow objects that produce constraint contradictions are excluded from the legal scenario; at least one valid solution must exist.

### 2.2 Inferencing Candidate List (ICL) Algorithm (LRM Annex E)

For each unbound flow-object reference:
1. Identify the object pool(s) of the appropriate type that the reference may be bound to.
2. Find all explicitly-traversed actions already in the activity that could legally satisfy the reference (matching type, consistent data constraints, correct scheduling relationship).
3. If no explicitly-traversed action qualifies, add an *anonymous instance* of every action type bound to the same pool to the ICL.
4. If the ICL is empty, generate an error.
5. Recurse: for each element added to the ICL, apply step 2 until all flow-object references are bound or the depth limit is reached.

### 2.3 Incremental Execution vs. Single-Solve Tension

The LRM presents inference as a single unified search over the combined activity graph.  Incremental execution processes one action at a time.  The key question this document addresses is: **which parts of inference must be resolved before execution begins, which can be resolved just-in-time during execution, and which require a persistent cross-action solver?**

---

## 3. Taxonomy of Inference Types

### 3.1 Structural Inference — *"What actions exist and how are they ordered?"*

Structural inference determines **which action instances exist** in the scenario and their **scheduling relationships** relative to each other.

**Sub-types:**

| Sub-type | Description | LRM Reference |
|---|---|---|
| **Buffer supply inference** | Infer a sequential predecessor to supply an unbound buffer input | §5.3.2, §17.1 |
| **State supply inference** | Infer a sequential predecessor to supply an unbound state input | §13.3, §17.1 |
| **Stream partner inference** | Infer a parallel partner for an unbound stream in/out | §5.3.2, §17.1 |
| **Type-conversion inference** | Infer an intermediate action to convert incompatible flow types | §5.3.2 |
| **Multi-level chain inference** | Transitively infer further actions when inferred actions themselves have unbound inputs | §17.1, Annex E |
| **Constraint-driven inference** | Data constraints on actions rule out existing ICL candidates, forcing inference of additional instances | §17.3 |

**Complexity characterisation**: Structural inference is fundamentally a **constraint satisfaction / backtracking search** over the type graph.  Its complexity is NP-hard in the general case (similar to planning with typed preconditions/effects).  For typical PSS models with bounded pool sizes and shallow inference chains, the search space is small.

### 3.2 Binding Inference — *"Which object instance does a field refer to?"*

Binding inference resolves **which pool instance** a flow-object reference or resource claim is assigned to.

**Sub-types:**

| Sub-type | Description | LRM Reference |
|---|---|---|
| **Buffer/state pool binding** | Assign a flow-object reference to a specific pool instance | §15, §17.2 |
| **Resource instance selection** | Choose which resource instance (lock/share) an action claims | §14, §16.4.4 |
| **Component assignment** | Choose which component instance an action executes in | §8.4 |
| **Cross-component binding** | Infer binding across component boundaries via default pool scope | §17.2 |

**Complexity characterisation**: Binding inference requires satisfying constraints from all actions that share a pool instance.  Resource instance selection combined with AllDifferent across parallel branches (head-action coordination) creates a **bipartite matching / constraint propagation** problem.

### 3.3 Data Inference — *"What values do rand fields take?"*

Data inference selects **field values** that satisfy all applicable constraints.

**Sub-types:**

| Sub-type | Description | LRM Reference |
|---|---|---|
| **Single-action randomization** | Solve rand fields of one action in isolation | §16.4.1 |
| **Flow-object data constraints** | Combine constraints from producer + consumer actions onto a shared flow object | §5.4, §16.4.3 |
| **Resource field constraints** | Combine constraints from all actions sharing a resource object | §16.4.4 |
| **Dynamic/inline constraints** | `with`-block constraints added at traversal time | §16.4.6 |
| **Cross-action sequential constraints** | Constraints spanning multiple actions in a sequential chain | §16.4.10 |
| **randc** | Random-cyclic fields that must not repeat until exhausted | §16.4.2 |

**Complexity characterisation**: Single-action randomization is a **finite-domain CSP** over the rand fields of one action.  Cross-action constraints require a **joint multi-variable CSP**.  Flow-object constraints with many producing/consuming actions can grow to medium-sized CSPs.

---

## 4. Inference in Incremental Execution — Timing Model

Incremental execution imposes a strict timing discipline: actions are instantiated, solved, and executed one at a time.  Inference must be mapped onto three execution phases.

### 4.1 Phase E: Elaboration / Compile-Time

Performed once before any execution begins (or at code-generation time for the C target).

**What can be resolved here:**

- **Pool binding tables**: For each `(component, action_type, field_name)` triple, determine which pool instance applies (LRM §15.3 precedence).  Result: static lookup table.
- **ICL construction per flow-object slot**: For each unbound flow-object slot in each action type, pre-compute the set of candidate action types that could satisfy it (type-compatible, same-pool).  Result: static ICL table.
- **Component subtree reachability**: Pre-compute which component instances are reachable for each action type.
- **Constraint-feasibility pruning**: Detect statically-contradictory data constraints on flow-object slots (LRM §17.3 Example 168) and eliminate infeasible pairs from ICLs.
- **Abstract action type sets**: For each abstract action field, enumerate concrete subtypes.

**Output**: A set of static tables and graphs that parametrise the runtime inference engine.

### 4.2 Phase S: Scenario-Entry / Structural Solve

Performed once per top-level action traversal, before any action executes.

**What must be resolved here:**

- **Structural decisions**: Which ICL element(s) to select for each unbound flow-object slot.
- **Inference chain expansion**: Recursively apply ICL selection until the scenario is structurally complete.
- **Ordering insertion**: Determine whether inferred predecessors execute sequentially before (buffer/state) or in parallel with (stream) the action that triggered their inference.
- **Constraint-driven structural backtracking**: If a selected ICL element later creates a data-constraint contradiction, backtrack and choose a different element.

**Complexity**: This is the most complex phase.  In the worst case it is a backtracking search.  In practice, PSS models tend to have shallow inference chains (depth 1–3) and small ICLs (2–5 candidate types).  The structural solve can be implemented as a depth-first search with constraint propagation.

For the C target, the structural solve runs on the **solve platform** (host/workstation), not on the embedded target.  The solved scenario structure is encoded into the generated execution sequence.

For the Python target, the structural solve runs at scenario-entry time using a pure-Python search.

### 4.3 Phase A: Action-Execution / Data Solve

Performed once per action instance, just before the action's `pre_solve`/`post_solve`/body execution.

**What must be resolved here:**

- **Per-action rand field randomization**: Call the constraint solver for this action's fields.
- **Flow-object data fields**: Resolve constraints from the producer action (already executed) combined with constraints from the consumer action (current action).
- **Resource instance selection**: Choose which pool instance to acquire; for head actions in parallel blocks, apply AllDifferent.
- **Dynamic/inline constraint injection**: Inject `with`-block constraints before the solve.
- **randc cycling**: Advance the randc state machine for each randc field.

**Complexity**: Mostly small CSPs (one action at a time).  Flow-object constraint combination may need to carry constraint fragments from the producer into the consumer's solve context.

---

## 5. Complexity Categories and Solver Requirements

### Category 1: Trivial — No Solver Required

| Case | Example | Resolution |
|---|---|---|
| Non-rand fields | `int a = 5;` | Direct evaluation |
| Fully-determined rand fields | `rand int<8> x; constraint x == 3;` | Constant propagation |
| Elaboration-time pool binding | Static bind directives | Lookup table |
| Pre-computed component assignment | Fixed component context | Table lookup |

**Target**: Both Python and C runtimes handle this with pure computation.

### Category 2: Simple — Pure Python Solver Sufficient

| Case | Example | Notes |
|---|---|---|
| Single-action rand fields, bounded integers | `rand int<32> addr;` with range constraint | Standard CP with bounds propagation |
| Single resource instance selection from small pool | Pool of 2–4 items | Random permutation + constraint check |
| randc cycling over small domain | `randc bit[4] opcode;` | Cyclic permutation tracking |
| Single flow-object field, one producer, one consumer | Buffer with additive constraints from writer + reader | Two-phase constraint merge |
| `with`-block scalar constraints | `action.val == 5` added inline | Direct constraint injection |

**Solver technique**: Forward-checking with arc consistency (AC-3) over finite integer domains.  The existing pure-Python solver (`solver/api.py`) handles this tier.

**Embedded suitability**: This category is the target for the C embedded runtime.  With generated per-action solve functions (as described in `pss-to-c-execution-design.md`), many of these reduces to simple integer arithmetic or a short bitvector scan.

### Category 3: Moderate — Pure Python Solver, but Potentially Slow

| Case | Example | Notes |
|---|---|---|
| Multi-field action with complex inter-field constraints | Address + length + end alignment constraints | Medium CSP, solver look-ahead required |
| Flow-object with N producers, M consumers | Shared buffer used by 3–5 actions | Must propagate intersection of all constraint sets |
| Resource claim with shared mode | Multiple actions sharing one resource, combined constraints | Constraint merging across action instances |
| Cross-action sequential constraints (depth 2) | `a.out.val + b.in.val < 100` | Forward constraint propagation |
| Abstract action type selection | Random choice among 5 concrete subtypes | Weighted random + per-type feasibility check |

**Solver technique**: Full CSP with backtracking search.  For flow-object constraint merging, maintain an accumulated constraint set that grows as producers/consumers are solved.

**Embedded suitability**: Possible on embedded targets if solve functions are compiled and the constraint system size is bounded.  The C runtime's compiled `solve_action_X()` approach handles this tier well when constraint sizes are statically bounded.

### Category 4: Heavy — Native Solver Strongly Preferred

| Case | Example | Notes |
|---|---|---|
| Head-action AllDifferent for parallel branches | N parallel branches each claiming a distinct resource instance | Bipartite matching (Hopcroft-Karp for large N) |
| Cross-branch data constraints | `branch1.action.addr + branch2.action.len == total` | Joint multi-action CSP |
| Large flow-object constraint systems | Buffer used by 10+ actions | Large CSP, needs efficient propagation |
| randc across multiple fields of a struct | Multiple randc fields with inter-field constraints | Combinatorial exhaustion tracking |
| Compound resource constraints | Multiple resources with inter-resource constraints (e.g., `r1.addr < r2.addr`) | Multi-variable CSP over resource fields |

**Solver technique**: Full CP solver with arc consistency, forward checking, and backtracking.  For bipartite matching, Hopcroft-Karp or Regin's AllDifferent propagator.  The native zuspec-solver (`SolveProblem` / `SolveCtx`) is required here.

**Embedded suitability**: For the C embedded target, head-action matching is compiled as a static precomputed feasible-set lookup (for 2–4 branches) or inline Hopcroft-Karp (larger N) as described in `pss-to-c-execution-design.md`.  Cross-branch data constraints are the hardest case and may require joint solve functions.

### Category 5: Complex — Requires Inference Engine (Solve-Platform Only)

| Case | Example | Notes |
|---|---|---|
| Structural inference chain (depth > 1) | Infer load_data before xfer_data before send_data | Backtracking search over action type graph |
| Constraint-driven ICL pruning | Data constraints eliminate all but one ICL candidate | Constraint propagation over type-level constraints |
| Inferencing limit recovery | Tool must infer terminating action at depth limit | Special-case handling |
| Multi-component cross-boundary inference | Default pool scope allows inference across component subtrees | Reachability + compatibility analysis |

**Solver technique**: Depth-first search with constraint propagation over the ICL graph.  This is essentially a typed planning problem.  Feasibility can be improved by pre-computing ICL tables and constraint compatibility at elaboration time.

**Embedded suitability**: **Not supported on embedded target.**  Structural inference is a solve-platform concern.  The embedded execution trace is already fully structurally determined by the time it runs on target.  The Python runtime may optionally support structural inference for host-side scenario generation.

---

## 6. Solve Technique Summary

| Technique | Applicable Categories | Notes |
|---|---|---|
| Constant propagation / direct evaluation | 1 | Eliminates solver calls entirely |
| Bounds propagation (AC-3) | 2 | Standard forward-checking; pure Python is fine |
| Random permutation + constraint check | 2 | Resource instance selection from small pools |
| CSP with backtracking | 3 | Used for multi-field actions; Python solver adequate |
| Accumulated constraint merging | 3 | Carry constraint fragments from producer to consumer |
| Bipartite matching (Hopcroft-Karp / Regin AllDifferent) | 4 | Head-action uniqueness; native solver preferred |
| Joint multi-action CSP | 4 | Cross-action/cross-branch data constraints |
| ICL graph search with type-level constraint propagation | 5 | Structural inference; solve-platform only |
| Precomputed feasible sets (ROM-resident) | 4 (C target) | Head-action matching compiled into generated C |

---

## 7. Architecture

### 7.1 Layered Inference Engine

```
┌───────────────────────────────────────────────────────────────┐
│                  Solve Platform (host)                        │
│                                                               │
│  ┌─────────────────────────────────────────────────────────┐  │
│  │  Phase E: Elaboration Engine                            │  │
│  │  • Pool binding table construction                     │  │
│  │  • ICL construction per flow-object slot               │  │
│  │  • Type-level constraint feasibility analysis          │  │
│  │  • Component subtree reachability                      │  │
│  └───────────────────────┬─────────────────────────────────┘  │
│                          │  static tables                      │
│  ┌───────────────────────▼─────────────────────────────────┐  │
│  │  Phase S: Structural Solver                             │  │
│  │  • ICL depth-first search with backtracking            │  │
│  │  • Constraint-driven candidate pruning                 │  │
│  │  • Inferred action ordering insertion                  │  │
│  │  • Output: fully-structured activity graph             │  │
│  └───────────────────────┬─────────────────────────────────┘  │
│                          │  structured activity               │
└──────────────────────────┼────────────────────────────────────┘
                           │
       ┌───────────────────┼────────────────────┐
       │  Python target    │                    │  C target
       ▼                   │                    ▼
┌──────────────────┐       │       ┌────────────────────────────┐
│ Phase A: Python  │       │       │ C Code Generator           │
│ Per-Action Solver│       │       │ • Compile solve_action_X() │
│ • Pure Python    │       │       │ • Precompute feasible sets  │
│   randomize()    │       │       │ • Emit ROM-resident tables  │
│ • Flow constraint│       │       └──────────────┬─────────────┘
│   accumulator    │       │                      │
│ • randc state    │       │                      ▼
│ • BindingSolver  │       │       ┌────────────────────────────┐
│   (AllDiff)      │       │       │ Embedded Target Runtime    │
└──────────────────┘       │       │ • Generated C solve funcs  │
                           │       │ • Canonical lock ordering  │
                           │       │ • Head-action force-lock   │
                           │       └────────────────────────────┘
```

### 7.2 Flow-Object Constraint Accumulator

A critical data structure not present in the current designs is a **constraint accumulator** for flow objects.  When a producer action is solved, its constraints on the flow-object data fields are stored.  When the consumer action is solved, those stored constraints are injected into the consumer's solve context.

```
FlowObjectConstraintStore:
  key:   (pool_id, instance_id)
  value: list[ConstraintExpr]   # accumulated from all producers so far

on producer action solve:
  store.add(pool_id, instance_id, producer.flow_out.constraints)

on consumer action solve (Phase A):
  inject store.get(pool_id, instance_id) into solver context
  solve consumer rand fields including flow input fields
```

For the C target, the accumulated constraints from the producer's `solve_action_X()` are passed as a parameter block to the consumer's `solve_action_Y()`.

### 7.3 Structural Solve Output Representation

The Phase S structural solver must output a representation that the Phase A execution engine can traverse.  Two options:

**Option A: Extended Activity Graph** — Augment the original activity IR with inferred action nodes, inferred ordering edges, and resolved binding assignments.  The Phase A engine traverses this augmented graph.

**Option B: Execution Plan** — Emit a flat or tree-structured execution plan (similar to a trace but forward-looking) that lists actions in execution order, with binding assignments pre-resolved.  The Phase A engine follows the plan.

Option B is better suited to the C target (where the plan can be encoded at code-generation time) and for resource-constrained execution.  Option A is more flexible for host-side Python execution where the model can be re-traversed.

---

## 8. Python Runtime Support Matrix

| Inference Type | Category | Python Support | Notes |
|---|---|---|---|
| Non-rand field evaluation | 1 | ✅ Full | Direct computation |
| Single-action rand fields | 2 | ✅ Full | Existing `randomize()` |
| Resource instance selection (small pool) | 2 | ✅ Full | Existing `ListClaimPool` |
| randc cycling | 2 | ✅ Full | `RandcManager` |
| Multi-field constraint solving | 3 | ✅ Full | Existing CSP engine |
| Flow-object constraint accumulation | 3 | ⚠️ Needs impl | `FlowObjectConstraintStore` |
| Head-action AllDifferent | 4 | ✅ Full | Existing `BindingSolver` |
| Cross-action sequential constraints | 4 | ⚠️ Needs impl | Forward constraint propagation |
| Cross-branch data constraints | 4 | ❌ Not yet | Joint multi-action solve |
| Structural buffer/state inference | 5 | ⚠️ Needs impl | ICL search engine |
| Structural stream inference | 5 | ⚠️ Needs impl | Parallel partner search |
| Multi-level inference chain | 5 | ⚠️ Needs impl | Recursive ICL expansion |
| Constraint-driven inference | 5 | ⚠️ Needs impl | Type-level constraint check |

### 8.1 Recommended Phasing for Python

**Phase P1** (Foundation): Flow-object constraint accumulation; enables producer→consumer constraint propagation.

**Phase P2** (Structural): Single-level buffer/state/stream structural inference; ICL construction; handles the common case.

**Phase P3** (Advanced): Multi-level inference chains; constraint-driven ICL pruning; cross-action sequential constraints.

**Phase P4** (Full): Cross-branch data constraints (joint solve); compound resource constraints; full LRM compliance.

---

## 9. C/Embedded Runtime Support Matrix

| Inference Type | Category | C Embedded Support | Notes |
|---|---|---|---|
| Non-rand field evaluation | 1 | ✅ Full | Emitted as direct C code |
| Single-action rand fields | 2 | ✅ Full | Generated `solve_action_X()` |
| Resource instance selection | 2 | ✅ Full | Try-lock loop; canonical ordering |
| randc cycling | 2 | ✅ Full | Per-action cyclic permutation buffer |
| Multi-field constraint solving | 3 | ✅ Full | Compiled into native solver call |
| Flow-object constraint passing | 3 | ⚠️ Needs design | Parameter block from producer to consumer |
| Head-action AllDifferent (≤4 branches) | 4 | ✅ Full | Precomputed feasible sets |
| Head-action AllDifferent (>4 branches) | 4 | ✅ Full | Hopcroft-Karp, compile-time |
| Cross-action sequential constraints | 4 | ⚠️ Needs impl | Forward constraint propagation in codegen |
| Cross-branch data constraints | 4 | ❌ Unsupported | Too expensive for embedded; solve-platform only |
| Structural inference | 5 | ✅ (host only) | Resolved at code-generation time; not on target |

### 9.1 Embedded Constraints Summary

On embedded targets (no OS, no heap, limited stack), the following constraints apply:

- **Structural inference is always pre-resolved**: The activity structure, including all inferred action instances and their ordering, is determined on the solve platform and encoded in the generated C.
- **Data field solving is bounded**: Each `solve_action_X()` function operates on a fixed-size constraint system; no dynamic growth.
- **Flow-object constraint passing** uses a statically-sized parameter struct emitted per flow-object type.
- **Cross-branch data constraints are prohibited** on the embedded target and must be restructured as intra-action constraints before code generation.

---

## 10. Key Design Decisions

### 10.1 Separation of Structural and Data Inference

The most important design decision is to **separate structural inference (Phase S) from data inference (Phase A)**.  Structural inference — choosing which action instances exist and how they are ordered — must complete before execution begins so that the execution engine can allocate resources, set up join groups, and prepare solve contexts.  Data inference — choosing field values — can proceed incrementally, one action at a time.

### 10.2 Flow-Object Constraints Are Producer-to-Consumer

A flow object's data constraints from its producing action must be available when the consuming action is solved.  The producer is always executed before the consumer (for buffer/state objects) or in parallel (stream objects).  For buffer/state, the constraint accumulator is written by the producer and read by the consumer.  For stream objects, both producer and consumer must be solved jointly (they share a solve context).

### 10.3 Structural Inference Scope Limits

To keep the search tractable, the following limits should be applied by default:

- **Maximum ICL depth**: 5 levels (configurable).
- **Maximum inferred action instances per slot**: 1 anonymous instance selected randomly from the ICL (unless constraints demand otherwise).
- **Constraint-driven ICL pruning is type-level only**: Full data-value constraint checking is deferred to Phase A; type-level checks (are the constraints structurally compatible?) are performed in Phase S.

### 10.4 randc Across Traversals

`randc` fields maintain their cycling state across calls to `run()`.  The `RandcManager` must be persistent at the scope of the component that owns the action type, not the action instance.

### 10.5 Solver Selection Policy

| Criterion | Pure Python | Native Solver |
|---|---|---|
| Constraint count | ≤ 16 variables | > 16 variables |
| AllDifferent | ≤ 4 elements | > 4 elements |
| Cross-action constraints | No | Yes |
| Embedded target | Always | Never |
| Solve platform, simple model | Preferred | Fallback |
| Solve platform, complex model | Fallback | Preferred |

---

## 11. Open Questions

(Superseded by §14 — see updated questions after §13.)

---

---

## 12. Schedule Block Ordering: Relationship to Inference

### 13.1 The Core Parallel

The user's observation is precise: **schedule block ordering and inference are two instances of the same underlying constraint-graph problem**, applied at different phases and to different sets of actions.

| Aspect | Inference | Schedule block ordering |
|---|---|---|
| **Action set** | Discovers which actions exist | Actions are already explicitly listed |
| **What is solved** | Structural: which actions to add, where to place them | Ordering: what execution order to impose |
| **Constraint source** | Unbound flow-object slots on listed actions | Explicit `bind` statements between listed actions |
| **Buffer rule** | Infer a sequential predecessor to supply the input | The listed producer must execute before the listed consumer |
| **Stream rule** | Infer a parallel partner for an unbound stream | The listed producer and consumer must execute in parallel |
| **Resource rule** | Infer ordering to avoid resource conflicts | Impose ordering when pool is too small for simultaneous claims |
| **Failure mode** | No valid ICL candidate exists | Constraint graph is infeasible (cycle or sequential/concurrent conflict) |

Both require the same core infrastructure: a **dependency graph over flow-object bindings** that is analysed for validity and then used to drive execution.

### 13.2 LRM-Specified Ordering Rules for Schedule Blocks

#### 13.2.1 Buffer ordering (LRM §5.1.1)

> "A buffer defines a strict scheduling dependency between the producer and the consumer that requires the producing action to complete its execution—and, thus, complete writing the buffer object—before execution of the consuming action may begin to read the buffer."

Rule: for every explicit bind `producer.out → consumer.in` where the flow object is a buffer, add a **sequential edge** `producer → consumer` to the schedule block's dependency graph.

Multiple consumers may read the same buffer; no ordering is imposed among them.

#### 13.2.2 Stream ordering (LRM §5.1.2)

> "The semantics of the stream flow object require that the producing and consuming actions execute in parallel (i.e., both activities shall begin execution when the same preceding actions complete)."

Rule: for every explicit bind `producer.out_stream → consumer.in_stream`, add a **concurrent edge** `{producer ↔ consumer}` — they must start at the same time and execute concurrently.

#### 13.2.3 State ordering (LRM §13.3)

> "Execution of an action that outputs a state object shall complete at any time before the execution of any inputting action begins."
> "Execution of an action that outputs a state object to a pool shall not be concurrent with the execution of any other action that either outputs or inputs a state object from that pool."

Rules:
- Writer → reader: sequential edge, same as buffer.
- Writer → writer (same pool): mutual exclusion — exactly one must precede the other (the schedule block picks which).
- Reader → writer (same pool): the writer must not start until all concurrent readers have completed.

This introduces a class of constraints that is **not purely a DAG**: two writers to the same state pool have a mutual-exclusion relationship that must be resolved to a sequential ordering, but the direction is unconstrained (either order is valid). The schedule block's solver must pick one.

#### 13.2.4 Resource-contention ordering (LRM §8639–8660)

> "If both L6 and L8 in the example above contend for the same single resource, they must be scheduled sequentially in order to avoid a resource conflict."

Rule: if two actions both lock (not share) the same resource instance, and the pool has insufficient instances to satisfy both simultaneously, a sequential edge must be added between them. Direction is unconstrained — either order is valid.

#### 13.2.5 Explicit scheduling constraints (LRM §16.2)

`constraint sequence(a, b)` and `constraint parallel(a, b, ...)` can explicitly add sequential or concurrent edges to the schedule block's graph. These have the same semantics as the implicit edges derived from flow objects.

#### 13.2.6 Conflict in parallel blocks (LRM §8330–8340)

A key **illegality rule**: a buffer (or state) binding between two actions that are both in a `parallel` block is **illegal** — because the buffer rule requires sequential ordering, but parallel requires no sequential dependencies across branches. The LRM is explicit:

> "According to buffer object exchange rules, the inputting action shall be scheduled after the outputting action. But this cannot satisfy the requirement of parallel scheduling... Thus, in the presence of a separate scheduling dependency between b and c, this activity shall be illegal."

This means buffer/state bindings between explicitly parallel actions must be detected and reported as errors during Phase E elaboration.

---

### 13.3 The Mixed Constraint Graph

A schedule block's constraint graph contains two classes of edges:

```
Sequential edge (A → B):   A must complete before B starts
                            Sources: buffer bind, state bind, resource contention,
                                     constraint sequence(A,B)

Concurrent edge (A ↔ B):   A and B must start at the same time and run in parallel
                            Sources: stream bind, constraint parallel(A,B)
```

This mixed graph is more complex than a simple DAG. Three types of infeasibility can arise:

1. **Cycle in sequential edges**: A → B → C → A — impossible to satisfy.
2. **Sequential/concurrent conflict**: A →(sequential) B, and A ↔ B (concurrent) — A must complete before B starts, but they must also start simultaneously.
3. **Transitive sequential/concurrent conflict**: A →(sequential) C →(sequential) B, and A ↔ B — A is a transitive predecessor of B, contradicting concurrency.

---

### 13.4 Static Analysis Algorithm

The following algorithm is performed during **Phase E (Elaboration)** for each schedule block.

**Input**: a set of action instances `{a₁, …, aₙ}` with explicit bind statements and scheduling constraints.

**Step 1: Build the sequential sub-graph `G_seq`**

```
for each bind p.out → c.in  where flow type is buffer or state:
    G_seq.add_edge(p, c)
for each constraint sequence(a, b):
    G_seq.add_edge(a, b)
for each pair (a, b) locking same resource, pool size < 2:
    G_seq.add_undirected_mutex_pair(a, b)   # direction TBD at solve time
```

**Step 2: Check for cycles**

Run DFS cycle detection on `G_seq`. If a cycle is found, report an error — the schedule block has contradictory sequential requirements.

**Step 3: Build the concurrent set `S_con`**

```
for each bind p.out_stream → c.in_stream:
    S_con.add_pair(p, c)
for each constraint parallel(a, b, ...):
    S_con.add_group({a, b, ...})
```

**Step 4: Detect sequential/concurrent conflicts**

Compute the transitive closure of `G_seq` (reachability). For each concurrent pair `(A, B)` in `S_con`:
```
if reachable(A, B) or reachable(B, A):
    error: "Concurrent constraint ({A}, {B}) conflicts with sequential dependency"
```

**Complexity**: Transitive closure is O(V·(V+E)) with DFS from each node. For schedule blocks with V ≤ 64 actions, bitset compression makes this O(V²/64).

**Step 5: Form execution units (concurrent groups)**

Actions linked by concurrent edges must start together. Use **union-find** to merge all actions connected (directly or transitively) by concurrent edges into **execution units**:

```
uf = UnionFind(actions)
for each concurrent pair (A, B) in S_con:
    uf.union(A, B)
units = uf.get_components()
```

Each unit is either a singleton action (no concurrent constraints) or a concurrent group (stream-linked actions that all start simultaneously).

**Step 6: Validate inter-unit sequential edges**

Project sequential edges onto the unit graph:
```
G_units = DAG of execution units
for each sequential edge (A → B) in G_seq:
    unit_A = uf.find(A)
    unit_B = uf.find(B)
    if unit_A != unit_B:
        G_units.add_edge(unit_A, unit_B)
    else:
        error: "Sequential edge within concurrent group {unit_A}"
```

**Step 7: Topological level assignment**

Assign levels to execution units (Kahn's algorithm on `G_units`):
```
level[unit] = 0 if in_degree == 0 else 1 + max(level[pred] for pred in predecessors)
```

Actions in units at the same level may run concurrently. Execution proceeds level by level.

**Output**: a **staged execution plan** — an ordered list of stages, where each stage is a set of execution units that may start once the previous stage completes.

---

### 13.5 Mutex Pairs: Underspecified Sequential Ordering

Resource contention between two actions that lock the same single-instance resource introduces a **mutex pair** — a sequential ordering requirement where the direction is not yet determined. This is analogous to inference choosing between two ICL candidates.

Two approaches:

**Option A — Resolve at elaboration time** (Phase E): Pick a direction for each mutex pair randomly (or by heuristic, e.g., alphabetical). This commits the execution order at compile/elaboration time.

**Option B — Resolve at runtime** (Phase A): Keep the mutex pair unresolved; the first action to acquire the resource proceeds, and the second blocks. This is the behaviour implemented by the `zsp_resource_pool_t` try-lock in the C runtime and `ListClaimPool` in the Python runtime. The execution order emerges from non-deterministic scheduling and resource acquisition races.

Option B is the natural fit for incremental execution: resource contention is handled organically by the resource pool blocking mechanism, without needing the schedule block analyser to resolve it statically.

However, Option B means the schedule block analyser must **exclude resource-contention edges** from the sequential graph when computing levels — it cannot assign deterministic levels to mutex-pair actions. Instead, those actions are treated as unordered siblings (potentially at the same level) and the runtime resolves the actual order.

---

### 13.6 Dynamic (Runtime) Coordination Mechanisms

Once the Phase E analyser has produced a staged execution plan, the runtime executes it. The following mechanisms are needed.

#### 13.6.1 Ready-queue with in-degree counters

For sequential dependencies (buffer/state/resource):

```python
# Initialise
in_degree = {unit: len(G_units.predecessors(unit)) for unit in units}
ready = deque(unit for unit in units if in_degree[unit] == 0)

# Dispatch
while ready or running:
    if ready:
        unit = ready.popleft()
        spawn(execute_unit(unit))

# On unit completion
def on_unit_complete(unit):
    for successor in G_units.successors(unit):
        in_degree[successor] -= 1
        if in_degree[successor] == 0:
            ready.append(successor)
```

#### 13.6.2 Concurrent group launcher

For stream-linked concurrent groups, all members must be spawned simultaneously:

```python
async def execute_unit(unit):
    if len(unit.actions) == 1:
        await execute_action(unit.actions[0])
    else:
        # Concurrent group: spawn all members together
        await asyncio.gather(*[execute_action(a) for a in unit.actions])
```

The asyncio `gather()` call provides the "synchronized start" semantics the LRM requires for streams (all coroutines are scheduled before any yields back to the event loop).

For the C runtime, all members of a concurrent group are spawned via `zsp_timebase_thread_create()` in a single scheduler step before yielding, achieving the same synchronized start.

#### 13.6.3 State pool write-exclusion fence

State writes require mutual exclusion with all other accesses to the same pool. This is not handled by the in-degree counter alone; it requires a **per-pool read-write fence**:

```python
class StatePoolFence:
    def __init__(self):
        self.readers: int = 0       # active reader count
        self.writer: bool = False   # writer active
        self.waiters: deque = deque()

    async def acquire_read(self):
        while self.writer:
            await self.wait()
        self.readers += 1

    async def acquire_write(self):
        while self.writer or self.readers > 0:
            await self.wait()
        self.writer = True

    def release(self):
        # decrement reader or clear writer, signal waiters
        ...
```

This is a readers-writer lock. For the C embedded runtime, the same pattern is implemented with waiter lists in `zsp_resource_pool_t`, as state pools are already modelled as resource pools.

---

### 13.7 Interaction with Inferred Actions

When inference adds actions to a schedule block (Phase S), those inferred actions must be integrated into the constraint graph **before** the Phase E analysis runs. The process is:

1. Phase S adds inferred action instances to the schedule block's action set.
2. Phase S derives binding edges for each inferred action (by definition, each inferred action is bound to at least one other action — that is why it was inferred).
3. Phase E re-runs the constraint graph analysis over the extended set.

This creates a feedback loop: Phase S inference and Phase E analysis are interleaved.

**Revised execution flow for a schedule block:**

```
loop:
    Phase E: analyse current action set → detect conflicts, compute stages
    Phase S: for each unbound flow-object slot in any action:
                 select ICL candidate and add to action set with binding
    if no new actions were added: break
end loop
emit staged execution plan
```

The loop terminates because each iteration either adds at least one new action (making progress) or finds no unbound slots (termination condition). Depth limits prevent infinite loops on recursive types.

---

### 13.8 Algorithm Summary

| Step | When | Algorithm | Complexity |
|---|---|---|---|
| Build sequential sub-graph | Phase E | Collect buffer/state/resource bind edges | O(B) where B = bindings |
| Cycle detection | Phase E | DFS with colour marking | O(V+E) |
| Build concurrent set | Phase E | Collect stream bind edges | O(S) where S = stream bindings |
| Sequential/concurrent conflict | Phase E | Transitive closure + stream edge check | O(V²/64) with bitsets |
| Concurrent group formation | Phase E | Union-find on stream edges | O(S · α(V)) ≈ O(S) |
| Intra-group sequential check | Phase E | Project sequential edges onto unit graph | O(E) |
| Level assignment (stages) | Phase E | Kahn's topological sort on unit DAG | O(V+E) |
| Mutex pair direction | Phase A | Resource try-lock race (Option B) | O(1) per attempt |
| Sequential dependency dispatch | Phase A | Ready-queue + in-degree counter | O(V+E) total |
| Concurrent group execution | Phase A | asyncio.gather() / multi-thread spawn | O(G) per group |
| State pool exclusion | Phase A | Readers-writer lock per pool | O(1) amortised |
| Inferred action integration | Phase S loop | ICL search + re-run Phase E | O(D · V²) depth × graph |

---

### 13.9 Shared Infrastructure with Inference

Because schedule block ordering and inference share the same underlying constraint graph, they should share implementation:

| Component | Used by inference | Used by schedule ordering |
|---|---|---|
| `FlowObjectBindingGraph` — directed graph of producer→consumer edges | ✅ ICL candidate search | ✅ Sequential edge construction |
| `ConcurrentPairSet` — set of must-be-concurrent action pairs | ✅ Stream partner inference | ✅ Concurrent group formation |
| `TransitiveClosure` — bitset reachability over sequential graph | ✅ Constraint-driven ICL pruning | ✅ Conflict detection |
| `UnionFind` — component grouping | (implicit in ICL expansion) | ✅ Concurrent group formation |
| `KahnTopologicalSort` — level assignment | ✅ Inference chain ordering | ✅ Stage assignment |
| `FlowObjectConstraintStore` — carry constraints producer→consumer | ✅ Data field inference | ✅ Data field inference (same mechanism) |
| `StatePoolFence` — readers-writer lock per state pool | ✅ State pool access ordering | ✅ State pool access ordering |

The recommended implementation strategy is a single `SchedulingGraph` class that supports both use cases, parametrised by whether actions are explicit (schedule block) or inferred (inference).

---

## 13. Open Questions (Updated)

1. **Stream joint solve**: Stream producer and consumer are in the same concurrent group; their flow-object fields must be solved jointly. Does the current `BindingSolver.solve_heads()` mechanism extend naturally to stream joint solving, or is a separate primitive needed?

2. **Constraint-driven inference depth**: If a model has recursive action types (A infers B which infers A), the ICL search can loop. A cycle-detection mechanism is required in the Phase S structural solver.

3. **Anonymous instance ordering**: When the Phase S solver selects an anonymous ICL instance, is the chosen ordering (sequential before / parallel with) always deterministic from the flow-object type, or can it be randomized? The LRM allows randomisation (§17.1); this should be a configuration option.

4. **Target-side structural inference**: Some embedded models may want to defer which action to infer until runtime. A controlled exception via explicit `select` or `choose` directives might be needed.

5. **Solver reuse across incremental steps**: For the Python target, is it beneficial to maintain a persistent `SolveCtx` across action solves and add constraints incrementally, or is a fresh context per action cleaner?

6. **Mutex pair resolution policy**: Option B (runtime resource-race) for mutex pairs is natural but non-deterministic. Should there be a `deterministic_schedule` mode that resolves all mutex pairs at Phase E, producing a reproducible execution order?

7. **Phase S and Phase E interleaving for schedule blocks with deep inference chains**: The feedback loop between inference and schedule analysis (§12.7) may cause O(D²) analyser invocations in pathological cases. A single-pass variant that processes ICL candidates in topological order and integrates them incrementally into the constraint graph would be more efficient.

8. **State pool write-exclusion and schedule stages**: A state pool write action within a schedule block forces all other writers and readers in the same pool to be in a different stage (or to hold the fence). This can significantly restrict parallelism. Should the stage assignment algorithm hoist state writers to dedicated stages?

---

## 14. References

- PSS LRM §5.1.1–5.1.3 — Buffer, Stream, and State flow object semantics
- PSS LRM §5.3.2 — Data Flow Inference Overview
- PSS LRM §6.3.2–6.3.4 — Sequential, Parallel, and Concurrent scheduling definitions
- PSS LRM §12.3.5 — Schedule statement semantics
- PSS LRM §13.3 — State Objects
- PSS LRM §14 — Resource Objects
- PSS LRM §15 — Object Pools and Binding
- PSS LRM §16.2 — Scheduling constraints (`constraint sequence` / `constraint parallel`)
- PSS LRM §16.4.1–16.4.12 — Randomization and Constraint Solving
- PSS LRM §17.1–17.3 — Action Inference
- PSS LRM Annex E — Solution Space Processing and ICL Algorithm
- `pss-python-execution-design.md` — Pure-Python incremental execution design
- `pss-to-c-execution-design.md` — C/embedded frame-chain execution design

- PSS LRM §5.3.2 — Data Flow Inference Overview
- PSS LRM §13.3 — State Objects
- PSS LRM §14 — Resource Objects
- PSS LRM §15 — Object Pools and Binding
- PSS LRM §16.4.1–16.4.12 — Randomization and Constraint Solving
- PSS LRM §17.1–17.3 — Action Inference
- PSS LRM Annex E — Solution Space Processing and ICL Algorithm
- `pss-python-execution-design.md` — Pure-Python incremental execution design
- `pss-to-c-execution-design.md` — C/embedded frame-chain execution design
