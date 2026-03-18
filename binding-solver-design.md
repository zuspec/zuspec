# Design: Binding Constraint Solver for PSS Resource Assignment

Date: 2026-03-17
Status: Proposed -- for review

---

## 1. Problem Statement

PSS models require solving *binding constraints* in addition to general
algebraic constraints.  The binding problem has three coupled dimensions:

1. **Component assignment**: Each action traversal selects one instance of the
   component type with which the action's type is associated (the `comp`
   field).

2. **Resource claim assignment**: Each `lock`/`share` field in each action must
   be assigned a resource instance (identified by `instance_id`) drawn from
   the pool that is bound to that field in the context of the assigned
   component instance.

3. **Uniqueness (lock semantics)**: Among all actions whose executions overlap
   in time and that claim resources from the *same pool*, no two `lock` claims
   may be assigned the same `instance_id`.  `share` claims may overlap with
   other `share` claims but not with any `lock` claim on the same instance.

These three dimensions are coupled: a different component assignment may
expose a different pool (or a different set of pools), changing the
feasible `instance_id` domains and the set of actions that compete for
uniqueness.  Additionally, algebraic constraints on resource fields (e.g.
`pad.role == OUT`, `pad.module_id == comp.module_id`) further restrict
which `instance_id` values are valid for each claim.

### 1.1 Why the Current Solver Is Insufficient

The existing native solver (`zuspec-solver`) handles integer variables with
domain propagation and backtracking search.  It has no representation for:

- Pools, component instances, or `instance_id` assignment.
- The global AllDifferent constraint across parallel lock claims.
- The interaction between component assignment and pool binding topology.

Encoding the binding problem as flat algebraic constraints is possible but
grossly inefficient:

- An AllDifferent constraint over N claims requires O(N^2) pairwise `!=`
  constraints.  Bounds propagation on pairwise `!=` is extremely weak --
  it cannot detect that K claims sharing K feasible values must each take a
  distinct value (Hall's theorem) until K-1 of them are already assigned.
- The combinatorial explosion makes backtracking search impractical for
  realistic problem sizes (the pad_configuration example has 26 claims
  from 60 pool instances, yielding 60^26 naive combinations).

### 1.2 Motivating Example: Pad Configuration

From `pad_configuration/`:

- 60 pads in a single pool (`padring`), each identified by `instance_id`
  in [0, 59].
- Up to 3 SPI masters (7 pad claims each) and 5 SPI slaves (4 pad claims
  each) -- a concrete scenario uses 2 masters + 3 slaves = 26 claims.
- All pad-selection actions execute in a `parallel` block, so every claim
  competes for uniqueness.
- Constraints partition pads by role (CLOCK pads at every 4th index starting
  from 3), module type (slaves restricted to [29..59], masters to [2..49]),
  and role capability (IN/OUT excluded from [0..9]).

After constraint propagation each claim's feasible set is a strict subset of
[0, 59].  The problem reduces to finding a system of distinct representatives
-- a bipartite matching problem with side constraints.

---

## 2. Problem Decomposition

The full binding problem decomposes naturally into three layers, solved
in a specific order with backtracking across layers when necessary.

```
Layer 3:  Algebraic constraints on resource fields
             (existing solver)
             ^
             | backtrack if UNSAT
             v
Layer 2:  Resource instance_id assignment
             (AllDifferent / bipartite matching)
             ^
             | backtrack if no matching exists
             v
Layer 1:  Component instance assignment
             (selection from finite set)
```

### Layer 1 -- Component Assignment

Each action `a` has a `comp` field that must resolve to one instance of
`a`'s component type.  The set of candidate instances is determined by
the component hierarchy and any `comp ==` constraints.  In many practical
models (including pad_configuration) this is fixed by `with` constraints
at traversal time, so there is nothing to solve.

When `comp` is not fully constrained, this is a finite-domain CSP over a
small set of discrete candidates.  A choice of `comp` determines which pools
are visible, so it must be resolved before Layer 2.

### Layer 2 -- Resource Instance Assignment (this design's focus)

Given a fixed component assignment, each resource claim `c_i` has:

- A **pool** `P_i` (determined by `comp` + bind topology).
- A **feasible set** `F_i` subset of `{0, ..., |P_i| - 1}` (determined by
  algebraic constraints on resource fields evaluated with `instance_id`
  as the free variable).
- A **claim mode**: `lock` or `share`.

The constraint is:

> Among all claims on pool P that overlap in execution time, if claims
> c_i and c_j both hold mode `lock`, then `instance_id(c_i) != instance_id(c_j)`.

This is precisely an **AllDifferent** constraint over the `instance_id`
variables of the lock claims within each (pool, time-overlap group).

Share claims are softer: a share claim's `instance_id` must differ from
every concurrent lock claim's `instance_id`, but may match other share
claims.  This is a partial AllDifferent (or a coloring constraint with
two colors: lock/share).

### Layer 3 -- Resource Field Constraints

Once `instance_id` values are assigned, the remaining random fields of
each resource instance (e.g., `role`, `module_id`, `priority`) must satisfy
the algebraic constraints coming from all actions that reference that
instance.  This is a standard algebraic CSP, handled by the existing
native solver.

---

## 3. Architecture

### 3.1 Overview

```
+---------------------------------------------------+
|                BindingSolver                       |
|                                                   |
|  +--------------+   +--------------------------+  |
|  | CompAssigner  |-->| ResourceAssigner         |  |
|  | (Layer 1)     |   | (Layer 2)                |  |
|  +--------------+   |                          |  |
|                      |  +--------------------+  |  |
|                      |  | DomainComputer     |  |  |
|                      |  | (feasible-set calc)|  |  |
|                      |  +--------------------+  |  |
|                      |  +--------------------+  |  |
|                      |  | AllDiffPropagator  |  |  |
|                      |  | (matching-based)   |  |  |
|                      |  +--------------------+  |  |
|                      |  +--------------------+  |  |
|                      |  | MatchingEngine     |  |  |
|                      |  | (Hopcroft-Karp)    |  |  |
|                      |  +--------------------+  |  |
|                      +--------------------------+  |
|                              |                     |
|                              v                     |
|                      +--------------------------+  |
|                      | AlgebraicSolver          |  |
|                      | (existing native solver) |  |
|                      | (Layer 3)                |  |
|                      +--------------------------+  |
+---------------------------------------------------+
```

### 3.2 Key Components

#### DomainComputer

Computes the feasible `instance_id` set for each claim.  For each claim
`c` with pool size `S`:

1. Start with `F = {0, 1, ..., S-1}`.
2. For each constraint on `c`'s resource fields that involves `instance_id`,
   evaluate the constraint with `instance_id` as the free variable and
   all other fields resolved to their forced values (or left as ranges).
3. Intersect the surviving values into `F`.

The output is a **domain** per claim, stored as a sorted array of integers
or as an interval list (whichever is more compact).

For the pad example, this step produces domains like:
- Slave CLOCK claim: `{31, 35, 39, 43, 47, 51, 55, 59}` (8 values)
- Master OUT claim: `{10, 11, 12, ..., 49} \ {11, 15, 19, ...}` (30 values)

**Implementation note**: When the resource type's constraints reference
`instance_id` through implications (e.g., `role == CLOCK -> instance_id in
{3,7,...}`), and the claim fixes `role`, we can evaluate the implication
statically.  This is a form of partial evaluation that avoids needing the
algebraic solver for domain computation in the common case.

#### AllDiffPropagator

Implements domain filtering for the AllDifferent constraint using the
classic Regin algorithm (1994):

1. Build a bipartite graph: left nodes = claims, right nodes = `instance_id`
   values.  An edge (c, v) exists iff v is in c's feasible set.
2. Find a **maximum matching** in this graph.  If the matching size < number
   of lock claims, the problem is UNSAT (no valid assignment exists).
3. Compute **strongly connected components (SCCs)** of the residual graph
   (the directed graph obtained by orienting matched edges right-to-left
   and unmatched edges left-to-right).
4. Remove edges that are not in the matching and whose endpoints are in
   different SCCs.  These edges cannot participate in any maximum matching,
   so the corresponding `instance_id` values are infeasible for those
   claims.  **This is the pruning step.**

This achieves **generalized arc consistency** (GAC) on the AllDifferent
constraint in O(N * sqrt(N) + E) time, where N = number of claims and
E = sum of domain sizes.

**Why Regin over simpler approaches:**

- **Pairwise != propagation** (O(N^2) constraints, bounds-only filtering):
  Cannot detect Hall violations until N-1 variables are fixed.  For the
  pad example with 26 claims, this would miss crucial pruning.
- **Bounds-consistent AllDifferent** (Lopez-Ortiz et al.): O(N log N) but
  only tightens interval bounds, not individual values.  Effective when
  domains are contiguous intervals, but pad constraints produce sparse
  domains (e.g., CLOCK pads at {3,7,11,...}).
- **Regin's matching-based algorithm**: Handles sparse domains natively.
  The matching check directly answers "can all claims be satisfied
  simultaneously?" and the SCC-based filtering prunes maximally.

For efficiency, the matching need not be recomputed from scratch on every
propagation round.  An incremental approach maintains the matching across
domain reductions:

- When a value is removed from a claim's domain, check if the removed edge
  was in the matching.  If not, the matching is still valid (just re-run
  SCC filtering).  If yes, attempt to find an augmenting path to repair the
  matching.  If no augmenting path exists, UNSAT.

#### MatchingEngine

Implements Hopcroft-Karp maximum bipartite matching:

- Time: O(E * sqrt(V)) where E = total edges, V = total nodes.
- For the pad example: V = 26 + 60 = 86, E ~ 26 * 20 (avg domain size) =
  520.  sqrt(86) ~ 9.  Total: ~4700 edge operations -- microseconds.

Also provides augmenting-path search for incremental matching repair.

**Randomized matching**: To produce diverse test scenarios, the matching
algorithm should not always produce the same assignment.  Two approaches:

1. Shuffle the adjacency lists before running Hopcroft-Karp.  This changes
   which augmenting paths are found first, producing different valid matchings
   across runs with different RNG seeds.
2. After finding any maximum matching, use random augmenting-cycle rotations
   to explore the space of all maximum matchings.

Approach (1) is simpler and sufficient for initial implementation.

#### CompAssigner (Layer 1)

Simple enumeration over candidate component instances.  For each action
whose `comp` is not fixed, iterate over candidates and attempt Layer 2
for each.  Use constraint propagation on `comp`-related constraints to
prune candidates before enumeration.

In most PSS models, `comp` is either fixed by `with` constraints or has
very few candidates (typically 1-5 component instances).  The cost of
enumeration is negligible.

#### AlgebraicSolver (Layer 3)

The existing native solver (SolveProblem + SolveCtx).  After `instance_id`
assignment, the remaining resource-field variables are passed to this
solver with their `instance_id` values fixed as constants.

For the pad example, once `instance_id` values are assigned, the `role`
and `module_id` fields are fully determined by the action's constraints
(e.g., `out_pad.role == OUT`).  Layer 3 simply verifies consistency -- no
search is needed.  In more complex models where resource fields interact
(e.g., `r1.priority > r2.priority`), the algebraic solver handles the
remaining freedom.

### 3.3 Share Semantics

Share claims introduce a weaker constraint: a share claim's `instance_id`
must not equal any concurrent lock claim's `instance_id`, but may equal
other share claims' `instance_id` values.

This is modeled as a **partial AllDifferent**:

- Partition claims into groups by pool.  Within each group, further
  partition into lock claims `L` and share claims `S`.
- The AllDifferent constraint applies to `L` only.
- Each share claim `s in S` has an additional constraint:
  `instance_id(s) not in {instance_id(l) : l in L}`.
- Multiple share claims may have equal `instance_id` values.

This can be solved by:

1. First assign `instance_id` values to lock claims using the AllDifferent
   solver.
2. Then assign share claims: each share claim picks from its feasible set
   minus the lock-assigned values.  Since share claims don't constrain
   each other, this is independent per claim and trivial.

If a share claim also constrains a resource field that interacts with a lock
claim's field on the same instance, the algebraic solver (Layer 3) handles
the interaction after assignment.

---

## 4. Detailed Algorithm

### 4.1 Entry Point: `binding_solve()`

```
binding_solve(model, activity_context, rng) -> BindingResult:

  1. EXTRACT the set of all actions in the current solve scope
     (parallel block or schedule block).

  2. For each action, COLLECT its resource claims (lock/share fields)
     and identify the associated pool via component assignment + bind
     topology.

  3. GROUP claims by (pool, overlap-group).  Actions that may execute
     concurrently are in the same overlap group.  For a parallel block,
     all branches are in one overlap group.

  4. For each overlap group G:
     a. COMPUTE feasible domains for each claim (DomainComputer).
     b. PARTITION claims into lock set L and share set S.
     c. BUILD bipartite graph for L.
     d. RUN AllDiffPropagator to filter domains.
     e. FIND a randomized maximum matching for L.
        - If no perfect matching: BACKTRACK to Layer 1 (try different
          comp assignment) or report UNSAT.
     f. ASSIGN share claims: for each s in S, pick a random value from
        F(s) \ {matched lock values on the same pool}.
     g. FIX instance_id values on all claims.

  5. INVOKE AlgebraicSolver on remaining resource-field variables with
     instance_id values fixed.
     - If UNSAT: BACKTRACK to step 4e (try a different matching)
       or 4a (try a different comp assignment).

  6. RETURN the full assignment.
```

### 4.2 Domain Computation Detail

For each claim `c` referencing resource type `R` from pool `P` of size `S`:

```
compute_domain(c, P, S) -> Set<int>:

  # Start with full pool range
  domain = {0, 1, ..., S-1}

  # Collect all constraints that reference c's resource fields
  constraints = collect_resource_constraints(c)

  for each constraint in constraints:
    if constraint references only (instance_id, fixed_fields):
      # Can evaluate statically
      domain = domain & eval_constraint(constraint, fixed_fields)
    else:
      # Constraint involves other random variables -- defer to Layer 3
      # but still try to extract instance_id implications
      implied = extract_instance_id_implications(constraint)
      if implied is not None:
        domain = domain & implied

  return domain
```

**Optimization**: Constraints of the form `field == value -> instance_id in
S` (common in PSS resource models) are detected at compile time and stored
as a precomputed mapping: `{(field, value) -> instance_id_set}`.  Domain
computation becomes a simple intersection of precomputed sets.

### 4.3 AllDifferent Filtering Detail

```
alldiff_filter(claims, domains) -> filtered_domains or UNSAT:

  1. Build bipartite graph G = (claims U values, edges).
  2. Find maximum matching M in G (Hopcroft-Karp).
  3. If |M| < |claims|: return UNSAT.
  4. Build residual digraph:
     - For matched edge (c, v): add arc v -> c
     - For unmatched edge (c, v): add arc c -> v
  5. Compute SCCs of the residual digraph (Tarjan's algorithm).
  6. For each unmatched edge (c, v):
     - If c and v are in different SCCs: remove v from domain(c).
  7. Return filtered domains.
```

### 4.4 Backtracking Strategy

When the matching engine or algebraic solver reports UNSAT, backtracking
occurs.  The order of backtracking decisions:

1. **Try a different matching** (within the same domains): Randomize edge
   ordering and re-run Hopcroft-Karp.  Useful when the algebraic solver
   fails for a specific `instance_id` assignment but the matching itself
   is feasible.

2. **Try a different component assignment** (Layer 1 backtrack): If all
   matchings for the current `comp` assignment are exhausted, try the next
   candidate `comp` value.

3. **Report UNSAT**: If no `comp` assignment yields a feasible binding.

The backtracking budget is bounded: at most `max_matching_retries`
different matchings per comp assignment (default: 10), and at most
`max_comp_retries` comp assignments (default: all candidates).

---

## 5. Integration with Existing Solver

### 5.1 API Surface

The binding solver is a new module that operates *above* the existing
algebraic solver, not inside it.  The call flow:

```
Activity evaluator
  +-> BindingSolver.solve(parallel_block)
        |-> DomainComputer.compute(claims)    [new]
        |-> AllDiffPropagator.filter(claims)  [new]
        |-> MatchingEngine.match(claims)      [new]
        +-> AlgebraicSolver.solve(residual)   [existing]
```

### 5.2 Data Flow

Input to `BindingSolver`:
- List of action traversals in the current scope (with `comp` constraints).
- For each traversal: its lock/share claims, the resource type, and the
  constraints on resource fields.
- Component hierarchy with pool declarations and bind directives.
- RNG seed.

Output:
- For each claim: assigned `instance_id`.
- For each resource instance referenced: values for all random fields.
- For each action: assigned `comp` instance.

### 5.3 Implementation Language

Layer 2 (the core of this design) should be implemented in C for
performance, following the same patterns as the existing solver:

- Arena allocation from a caller-supplied buffer.
- No heap allocation in the hot path.
- Python ctypes wrapper for the API.

New C files:
- `zsp_binding.h` / `zsp_binding.c` -- top-level binding solver.
- `zsp_matching.h` / `zsp_matching.c` -- Hopcroft-Karp + SCC.
- `zsp_alldiff.h` / `zsp_alldiff.c` -- AllDifferent propagator.

New Python files:
- `binding.py` -- Python wrapper and IR translation for binding problems.

### 5.4 Interaction with Algebraic Constraints

Some resource constraints mix `instance_id` with other random variables
in ways that prevent static domain computation.  Example:

```pss
resource R {
    rand int priority;
    constraint instance_id < 4 -> priority > 5;
}
action A {
    lock R r;
    constraint r.priority == some_other_rand_field;
}
```

Here, `instance_id` and `priority` and `some_other_rand_field` are all
coupled.  The domain computer cannot fully resolve `instance_id`'s
feasible set without knowing `some_other_rand_field`.

**Approach**: Compute a *relaxed* domain by ignoring constraints that
involve unresolved random variables.  The AllDifferent solver works with
these relaxed domains.  After matching, the algebraic solver verifies
and resolves the remaining constraints.  If UNSAT, backtrack to try a
different matching.

This is sound (never misses a valid solution) and complete (explores
all matchings if needed).  The relaxed domains are always supersets of
the true domains, so the matching step never rejects a feasible
assignment.

---

## 6. Complexity Analysis

### 6.1 Pad Configuration Example

- N = 26 claims, S = 60 pool instances.
- Average domain size after constraint propagation: ~20.
- E = 26 * 20 = 520 edges.

| Step | Algorithm | Time |
|------|-----------|------|
| Domain computation | 26 * (evaluate ~3 constraints) | ~microseconds |
| Build bipartite graph | O(E) = O(520) | ~microseconds |
| Maximum matching (Hopcroft-Karp) | O(E * sqrt(N)) = O(520 * 5) | ~microseconds |
| SCC computation (Tarjan) | O(N + E) = O(546) | ~microseconds |
| Domain filtering | O(E) = O(520) | ~microseconds |
| Random matching selection | O(E) | ~microseconds |
| Algebraic solver (verify) | O(1) -- fields fully determined | ~microseconds |
| **Total** | | **<100 microseconds** |

Compare with naive pairwise-!= encoding:
- N*(N-1)/2 = 325 pairwise constraints, each on a domain of ~20 values.
- Backtracking search would need to explore a tree of depth 26 with
  branching factor ~20.  Worst case: millions of nodes.

### 6.2 Scaling

The matching-based approach scales to:
- Hundreds of claims with thousands of pool instances (e.g., memory pages).
- The bottleneck shifts to domain computation (evaluating constraints per
  claim) rather than matching.  Precomputed domain tables eliminate this.

---

## 7. Implementation Plan

### Phase 1: Core Matching Engine (C)

1. Implement Hopcroft-Karp in `zsp_matching.c`.
2. Implement Tarjan's SCC in the same file.
3. Unit tests via ctypes: small bipartite graphs, verify matching size
   and SCC correctness.

### Phase 2: AllDifferent Propagator (C)

1. Implement Regin-style filtering in `zsp_alldiff.c`.
2. Integrate with the matching engine.
3. Tests: AllDifferent on known CSPs (N-queens row assignment, Sudoku rows).

### Phase 3: Domain Computer (Python + C)

1. Implement constraint evaluation for `instance_id` domain computation.
2. Handle the common patterns: `field == value -> instance_id in set`,
   `instance_id in range`.
3. Compile the domain tables into C-friendly format.

### Phase 4: Binding Solver Integration

1. Wire DomainComputer + AllDiffPropagator + MatchingEngine into
   `BindingSolver`.
2. Add backtracking between matching and algebraic solver.
3. Integration test: pad_configuration example end-to-end.

### Phase 5: Component Assignment

1. Implement `CompAssigner` for the case where `comp` is not fixed.
2. Add backtracking from Layer 2 to Layer 1.
3. Test with models that have multiple component instances.

---

## 8. Open Issues

### 8.1 Scheduling Overlap Groups

The AllDifferent constraint applies to claims whose actions execute
concurrently.  Determining which actions overlap requires analyzing the
activity scheduling graph:

- `parallel` block: all branches overlap.
- `schedule` block: any pair of branches *may* overlap (tool decides).
- Sequential: no overlap; resources can be reused.

For `schedule` blocks, the solver must consider the worst case (all
branches overlap) or jointly solve the scheduling and resource assignment.
Joint solving is significantly more complex.  The initial implementation
should handle `parallel` blocks (where overlap is guaranteed) and treat
`schedule` blocks conservatively (assume full overlap).

**Open question**: Should `schedule` block resource assignment be
optimistic (try to find a non-overlapping schedule that reduces resource
pressure) or conservative?  Optimistic requires co-solving scheduling
with resource assignment.

### 8.2 Replicate with Variable Bounds

The pad_configuration uses `replicate(i: num_of_slaves)` where
`num_of_slaves` is a random variable.  The number of claims is not
known until `num_of_slaves` is resolved.

This creates a chicken-and-egg problem: the algebraic solver determines
`num_of_slaves`, but the binding solver needs to know the claim count
to set up the matching problem.

**Proposed approach**: Solve `num_of_slaves` (and similar control-flow
variables) first using the algebraic solver, then invoke the binding
solver with the concrete claim count.  This works because `num_of_slaves`
is typically constrained by algebraic constraints alone (e.g.,
`num_of_slaves * 4 + num_of_masters * 7 <= 60`), so it can be resolved
independently.

**Risk**: If `num_of_slaves` interacts with resource-field constraints
in a circular way, this decomposition fails.  We haven't seen such
patterns in practice, but the architecture should support falling back
to joint solving if needed.

### 8.3 Resource Fields with Inter-Claim Constraints

Example: `constraint r1.priority + r2.priority <= 10` where `r1` and
`r2` are separate lock claims.  Here the resource fields interact
across claims, not just within a single claim.

The current Layer 3 design treats each resource instance independently
after `instance_id` assignment.  Inter-claim resource-field constraints
need to be collected and solved as a single algebraic problem.

**Proposed approach**: After `instance_id` assignment, build a single
constraint system containing all resource-field variables from all
claims, with their inter-claim constraints.  Pass this to the existing
algebraic solver.  This handles the general case correctly, though it
increases the algebraic problem size.

### 8.4 Multiple Pools in One Overlap Group

An action may claim resources from multiple pools (e.g., `lock R1 a;
lock R2 b;`).  Each pool has its own AllDifferent constraint, but the
pools are independent -- a claim on pool R1 does not conflict with a
claim on pool R2.

The solver should run separate AllDifferent instances per pool, not one
global AllDifferent.  This is straightforward but must be explicit in
the implementation: group claims by pool before invoking the matching
engine.

### 8.5 Randomization Quality

The matching algorithm produces *a* valid assignment, but for test
generation we want *uniformly random* valid assignments (or at least
diverse ones).  A simple Hopcroft-Karp with shuffled adjacency lists
produces different matchings but does not guarantee uniformity.

For the initial implementation, shuffled Hopcroft-Karp provides adequate
diversity.  If uniform sampling is needed, a Markov-chain approach
(random walk on the space of maximum matchings via augmenting cycles)
can be added later.

### 8.6 Hierarchical Pool Binding

PSS allows pools to be bound hierarchically: a pool in a parent component
may be bound to multiple child components.  Actions in different child
components then compete for the same pool.  The solver must resolve the
pool identity from the binding topology before invoking the matching
engine.

This is a static analysis step (pool resolution) that should be done
once during model elaboration, not during solving.  The binding solver
receives the resolved pool identity per claim as input.

---

## 9. Overlooked Opportunities

### 9.1 AllDifferent as a First-Class Propagator in the C Solver

The existing solver has a `UniqueConstraint` in the Python IR that raises
`TranslationError` ("not yet supported by the native back-end").  Adding
a native AllDifferent propagator would benefit general constraint solving
beyond just resource binding.  Use cases:

- `unique` constraints in PSS (Clause 16.1.7).
- Array-element uniqueness in struct randomization.

The matching engine developed for binding could be reused as a general
AllDifferent propagator within the existing solver framework.

### 9.2 Domain Caching Across Solves

In many PSS flows, the same model is solved repeatedly (e.g., generating
many test scenarios).  The pool sizes, bind topology, and resource-field
constraint structure don't change between solves.  The domain computation
(feasible `instance_id` sets per claim) is deterministic and can be
cached.  Only the matching step (which uses a fresh RNG seed) needs to
run per solve.

The existing `_CLASS_CACHE` pattern in `backend.py` could be extended
to cache compiled binding problems.

### 9.3 Incremental Matching for Backtracking

When the algebraic solver rejects a matching (Layer 3 UNSAT), instead of
restarting matching from scratch, the failing `instance_id` assignment
could be fed back as a nogood, removing the corresponding edge from the
bipartite graph and incrementally repairing the matching.  This avoids
re-exploring matchings that are known to fail.

### 9.4 Partitioning Independent Binding Subproblems

The existing `Partitioner` (union-find on constraint variable sets) could
be extended to binding problems: claims on different pools with no
cross-constraints are independent subproblems.  Solving them separately
reduces the matching problem size.

### 9.5 Integration with Schedule-Block Ordering

For `schedule` blocks, the solver could jointly optimize resource
assignment and action ordering to minimize resource pressure.  This is a
scheduling+assignment co-optimization problem.  A greedy approach: order
actions to maximize resource reuse (schedule resource-heavy actions
sequentially rather than concurrently).  This extends the current work
but could significantly reduce pool size requirements.

### 9.6 Bounds-Consistent AllDifferent for Large Contiguous Domains

When resource pools are large and domains are contiguous intervals (e.g.,
`instance_id in [0, 999]`), the Regin algorithm's O(E) cost (where E
can be thousands per claim) becomes expensive.  The bounds-consistent
AllDifferent of Lopez-Ortiz et al. runs in O(N log N) regardless of
domain width.  Using bounds consistency as a fast pre-filter before
Regin (only on sparse-domain claims) is a practical hybrid.

---

## 10. Summary

The binding problem in PSS is fundamentally a constrained assignment
problem, not a general algebraic CSP.  Treating it as such -- using
bipartite matching and AllDifferent propagation -- yields orders-of-
magnitude improvement over naive constraint encoding.

The architecture layers cleanly over the existing algebraic solver:
the binding solver resolves structural assignment decisions (comp,
instance_id) and delegates remaining algebraic freedom to the proven
native solver.  The decomposition exploits the problem's natural
structure while remaining sound and complete.

For the pad_configuration example, this approach solves in microseconds
what naive encoding would take seconds or minutes.  The design scales
to larger industrial models with hundreds of resource claims.
