# Design: Mapping PSS Activity Constructs to C Execution
# via Stackless Coroutines and Per-Step Solving

Date: 2026-03-17
Status: Proposed -- for review (rev 2: targets zuspec-be-sw runtime)

---

## 1. Overview and Design Philosophy

### 1.1 The Problem

The PSS LRM describes test scenario generation as a monolithic solve:
the entire activity tree -- all actions, their scheduling relationships,
resource assignments, data-flow bindings, and constraint systems -- is
resolved together before execution begins. This "single-solve" model
produces correct results but is fundamentally incompatible with
memory-constrained, high-speed embedded targets where:

- The full scenario graph may not fit in memory.
- Solve time grows combinatorially with the number of concurrent actions.
- The target has no OS, no heap, and limited stack depth.

### 1.2 The Approach

We decompose the monolithic solve into a sequence of small, independent
solve steps driven by the existing zuspec-be-sw stackless coroutine
scheduler (`zsp_timebase_t`). Each step corresponds to one action
traversal. The key insight:

**Parallel branches do not need to agree on resource assignments
upfront.** Instead:

1. **Head actions** (the initial action on each parallel branch) are
   solved together as a group, with distinct resource assignments
   guaranteed by the binding solver's AllDifferent constraint. This
   is the only cross-branch coordination point.

2. **Subsequent actions** on each branch are solved independently when
   their branch reaches them. Resource claims are acquired at runtime
   via the coroutine scheduler: if the desired resource instance is
   held by another branch, the coroutine yields and waits for release.

3. **Sequential segments** within a branch are solved one action at a
   time, in order, with no cross-action coordination beyond data-flow
   propagation.

This reduces the solve problem at any given moment to at most one
action's constraints plus a small resource-acquisition check, keeping
memory and compute costs bounded regardless of total scenario size.

### 1.3 Target Runtime

The target is the zuspec-be-sw C runtime (`packages/zuspec-be-sw/
src/zuspec/be/sw/share/`). Key components we build on:

- **`zsp_timebase_t`**: Time-aware cooperative scheduler with ready
  queue and min-heap event queue. Replaces the older `zsp_scheduler_t`.
- **Frame-chain coroutines**: Each coroutine is a `zsp_thread_t` with
  a linked list of `zsp_frame_t` frames. Each frame carries a task
  function pointer, an `idx` (resume point), and inline locals. The
  scheduler calls `frame->func(tb, thread, frame->idx, NULL)` to
  resume.
- **Stack-block allocator**: `zsp_stack_block_t` chains with free-list
  caching (4K/8K blocks) inside `zsp_timebase_t`.
- **`zsp_channel_t`**: TLM-style FIFO with blocking put/get -- a
  model for how resource-pool blocking should work.

### 1.4 Target Environment Assumptions

- **Language**: C (C11), no dynamic allocation in steady state.
- **Memory**: Statically allocated buffers sized at code-generation
  time. The `zsp_alloc_t` interface is pluggable (malloc-backed for
  host, static-pool for embedded).
- **Concurrency**: Single-threaded; concurrency is cooperative via
  the `zsp_timebase` scheduler. No RTOS, no pthreads.
- **Code generation**: A PSS-to-C compiler ("zuspec-codegen") emits
  all C source. No runtime interpretation of PSS IR.

---

## 2. Execution Model: Activities as Frame-Chain Coroutines

### 2.1 The Frame-Chain Model

The zuspec-be-sw runtime uses a frame-chain rather than a monolithic
switch-on-state coroutine. Each "stack frame" is a `zsp_frame_t`
allocated from the thread's stack-block allocator:

```c
typedef struct zsp_frame_s {
    zsp_task_func       func;   /* task function for this frame */
    struct zsp_frame_s  *prev;  /* caller's frame               */
    int32_t             idx;    /* resume point within func      */
} zsp_frame_t;

/* Locals are allocated immediately after the frame header */
#define zsp_frame_locals(frame, locals_t) \
    ((locals_t *)&((zsp_frame_wrap_t *)(frame))->locals)
```

A task function's signature:

```c
typedef struct zsp_frame_s *(*zsp_task_func)(
    zsp_timebase_t *tb,
    zsp_thread_t   *thread,
    int             idx,
    va_list        *args);
```

- `idx == 0` with non-NULL `args`: initial call (extract arguments,
  allocate frame, set up locals).
- `idx > 0` with NULL `args`: resume after yield/block.
- Returns the new `thread->leaf` frame, or NULL if the thread is done.

This model naturally supports nested calls (sub-activities call sub-task
functions, pushing frames onto the chain) and yields (set `idx` to the
resume point, set SUSPEND flag, return current frame).

### 2.2 Generated Task Function Pattern

Each compound action's activity maps to one task function. The function
uses a `switch(idx)` to dispatch to resume points:

```c
static zsp_frame_t *my_activity_task(
    zsp_timebase_t *tb,
    zsp_thread_t   *thread,
    int             idx,
    va_list        *args)
{
    zsp_frame_t *ret = thread->leaf;

    typedef struct {
        /* action fields, sub-action results, loop counters */
        my_action_fields_t  fields;
        int32_t             repeat_i;
    } locals_t;

    switch (idx) {
    case 0: {
        /* Initial: allocate frame, extract args */
        ret = zsp_timebase_alloc_frame(
            thread, sizeof(locals_t), &my_activity_task);
        locals_t *L = zsp_frame_locals(ret, locals_t);

        /* ... initialize locals ... */

        /* Solve first action */
        solve_action_A(&L->fields, tb);

        /* Yield to scheduler before executing body */
        ret->idx = 1;
        zsp_timebase_yield(thread);
        break;
    }
    case 1: {
        locals_t *L = zsp_frame_locals(ret, locals_t);

        /* Execute action A's body */
        exec_body_A(&L->fields);

        /* Solve next action */
        solve_action_B(&L->fields, tb);
        ret->idx = 2;
        zsp_timebase_yield(thread);
        break;
    }
    case 2: {
        locals_t *L = zsp_frame_locals(ret, locals_t);
        exec_body_B(&L->fields);

        /* Done -- return to parent */
        ret = zsp_timebase_return(thread, 0);
        break;
    }
    }
    return ret;
}
```

### 2.3 Nested Sub-Activity Calls

When a compound action traverses another compound action, the generated
code pushes a new frame by calling the sub-activity's task function:

```c
case 3: {
    locals_t *L = zsp_frame_locals(ret, locals_t);

    /* Call sub-activity (pushes new frame) */
    ret->idx = 4;  /* resume point after sub-activity returns */
    ret = zsp_timebase_call(thread, &sub_activity_task,
                            /* args... */);
    break;
}
case 4: {
    /* Sub-activity completed; thread->rval has its return value */
    locals_t *L = zsp_frame_locals(ret, locals_t);
    /* continue... */
}
```

`zsp_timebase_return` pops the sub-activity's frame and resumes the
caller's frame at its saved `idx`. This happens automatically via the
frame-chain's `prev` pointer.

### 2.4 Scheduler Integration

The scheduler (`zsp_timebase_t`) runs threads from its ready queue:

```c
int zsp_timebase_run(zsp_timebase_t *tb) {
    zsp_thread_t *thread = ready_queue_pop(tb);
    if (!thread) return 0;
    tb->active--;
    thread->leaf = thread->leaf->func(
        tb, thread, thread->leaf->idx, NULL);
    /* ... re-enqueue if suspended, cleanup if done ... */
}
```

**Yielding**: Set `SUSPEND` flag, `break` out of the switch. The
scheduler re-enqueues the thread.

**Blocking**: Set `BLOCKED` flag, add thread to a waiter list (resource
pool, channel, join group). The thread is NOT re-enqueued. When the
blocking condition clears, the signaler calls
`zsp_timebase_schedule(tb, thread)` to put it back in the ready queue.

**Timed wait**: `zsp_timebase_schedule_at(tb, thread, delay)` puts the
thread on the min-heap event queue; it wakes at `current_time + delay`.

---

## 3. New Runtime Primitives Required

The existing runtime provides coroutines, scheduling, channels, and
memory. It does NOT provide resource pools, join groups, or deadlock
detection. These must be added.

### 3.1 Resource Pool (`zsp_resource_pool_t`)

Models a PSS resource pool with lock/share semantics. Follows the same
try-acquire + waiter-list + notify pattern as `zsp_channel_t`.

```c
typedef struct zsp_resource_pool_s {
    uint32_t        pool_size;
    uint8_t        *lock_held;       /* [pool_size]: 0=free, 1=locked      */
    uint8_t        *share_count;     /* [pool_size]: number of sharers     */
    zsp_thread_t   *lock_waiters;    /* threads blocked waiting for lock   */
    zsp_thread_t   *share_waiters;   /* threads blocked waiting for share  */
    zsp_timebase_t *tb;              /* owning timebase                    */
} zsp_resource_pool_t;

void zsp_resource_pool_init(
    zsp_init_ctxt_t       *ctxt,
    zsp_resource_pool_t   *pool,
    uint32_t               pool_size);

/* Try to lock instance_id. Returns 0 on success, -1 if busy. */
int zsp_resource_try_lock(
    zsp_resource_pool_t *pool,
    int32_t              instance_id);

/* Force-lock (used for head actions where binding solver guarantees
   the instance is free). No waiter logic. */
void zsp_resource_force_lock(
    zsp_resource_pool_t *pool,
    int32_t              instance_id);

/* Unlock and wake one waiter (if any). */
void zsp_resource_unlock(
    zsp_resource_pool_t *pool,
    int32_t              instance_id);

/* Try to share instance_id. Returns 0 if not locked, -1 if locked. */
int zsp_resource_try_share(
    zsp_resource_pool_t *pool,
    int32_t              instance_id);

/* Release share and wake waiters if share_count reaches 0. */
void zsp_resource_unshare(
    zsp_resource_pool_t *pool,
    int32_t              instance_id);

/* Add thread to lock-waiter list (thread must already be BLOCKED). */
void zsp_resource_add_lock_waiter(
    zsp_resource_pool_t *pool,
    zsp_thread_t        *thread);
```

**Blocking lock acquisition as a task function** (follows the
`zsp_channel_put_task` pattern):

```c
zsp_frame_t *zsp_resource_lock_task(
    zsp_timebase_t *tb,
    zsp_thread_t   *thread,
    int             idx,
    va_list        *args)
{
    zsp_frame_t *ret = thread->leaf;

    typedef struct {
        zsp_resource_pool_t *pool;
        int32_t              instance_id;
    } locals_t;

    switch (idx) {
    case 0: {
        ret = zsp_timebase_alloc_frame(
            thread, sizeof(locals_t), &zsp_resource_lock_task);
        locals_t *L = zsp_frame_locals(ret, locals_t);
        if (args) {
            L->pool = va_arg(*args, zsp_resource_pool_t *);
            L->instance_id = va_arg(*args, int32_t);
        }
        if (zsp_resource_try_lock(L->pool, L->instance_id) == 0) {
            ret = zsp_timebase_return(thread, 0);
        } else {
            ret->idx = 1;
            zsp_resource_add_lock_waiter(L->pool, thread);
        }
        break;
    }
    case 1: {
        locals_t *L = zsp_frame_locals(ret, locals_t);
        if (zsp_resource_try_lock(L->pool, L->instance_id) == 0) {
            ret = zsp_timebase_return(thread, 0);
        } else {
            zsp_resource_add_lock_waiter(L->pool, thread);
        }
        break;
    }
    }
    return ret;
}
```

### 3.2 Join Group (`zsp_join_t`)

Supports parallel-block join semantics. A parent thread creates a join,
spawns N children, and blocks until the join condition is met.

```c
typedef enum {
    ZSP_JOIN_ALL,           /* Wait for all children (default parallel) */
    ZSP_JOIN_BRANCH,        /* Wait for specific labeled branches      */
    ZSP_JOIN_SELECT,        /* Wait for N randomly selected branches   */
    ZSP_JOIN_FIRST,         /* Runtime: wait for first N completions   */
    ZSP_JOIN_NONE           /* Don't wait (join at enclosing sequence) */
} zsp_join_kind_e;

typedef struct zsp_join_s {
    zsp_thread_t   *parent;         /* thread to wake on completion    */
    int32_t         remaining;      /* decremented on each child done  */
    zsp_join_kind_e kind;
    zsp_timebase_t *tb;
} zsp_join_t;

void zsp_join_init(
    zsp_join_t     *join,
    zsp_thread_t   *parent,
    int32_t         count,
    zsp_join_kind_e kind,
    zsp_timebase_t *tb);

/* Called by each child thread's exit_f when it completes.
   Decrements remaining; wakes parent when condition is met. */
void zsp_join_signal(zsp_join_t *join);
```

Child threads are initialized with `exit_f` pointing to a wrapper that
calls `zsp_join_signal`:

```c
static void join_child_exit(zsp_thread_t *thread) {
    zsp_join_t *join = (zsp_join_t *)thread->rval;  /* stashed in rval */
    zsp_join_signal(join);
}
```

`zsp_join_signal` implementation:

```c
void zsp_join_signal(zsp_join_t *join) {
    join->remaining--;
    if (join->remaining <= 0) {
        /* Wake parent */
        zsp_timebase_schedule(join->tb, join->parent);
    }
}
```

For `ZSP_JOIN_NONE`, the parent is not blocked after spawning. The join
group is attached to the enclosing sequence block, which blocks on it
before proceeding.

For `ZSP_JOIN_FIRST(N)`, `remaining` is initialized to `count - N + 1`
... actually simpler: initialize to N (the number needed), and each
child signals. The first N completions wake the parent.

### 3.3 Deadlock Detection

Add a check to the scheduler run loop. When `ready_head == NULL` and
`event_count == 0` but `active > 0`, all threads are blocked on
non-timed events (resources, joins, channels). This is a deadlock.

```c
/* In the main run loop (caller's responsibility): */
while (zsp_timebase_has_pending(tb) || tb->active > 0) {
    while (tb->ready_head) {
        zsp_timebase_run(tb);
    }
    if (tb->event_count > 0) {
        zsp_timebase_advance(tb);
    } else if (tb->active > 0) {
        /* DEADLOCK: threads blocked, no timed events */
        zsp_runtime_panic(tb, ZSP_PANIC_DEADLOCK);
    } else {
        break;  /* Clean completion */
    }
}
```

---

## 4. Activity Construct Mapping

Each PSS activity construct maps to a pattern in the generated task
function. All code is emitted by the code generator targeting the
`zsp_timebase` API.

### 4.1 Sequential Block

Sequential statements become sequential `idx` cases within the task
function. Each action traversal is a yield point:

```c
case IDX_SEQ_A:
    L->fields_a = solve_action_A(tb);
    /* Acquire resources (may block -- see 5.2) */
    if (zsp_resource_try_lock(L->pool, L->fields_a.r_id) < 0) {
        ret->idx = IDX_SEQ_A_WAIT;
        zsp_resource_add_lock_waiter(L->pool, thread);
        break;  /* blocked */
    }
    /* fall through */
case IDX_SEQ_A_EXEC:
    exec_body_A(&L->fields_a);
    zsp_resource_unlock(L->pool, L->fields_a.r_id);
    ret->idx = IDX_SEQ_B;
    zsp_timebase_yield(thread);
    break;
```

### 4.2 Parallel Block

A parallel block spawns N child threads and blocks the parent on a
`zsp_join_t`:

```c
case IDX_PAR_SPAWN: {
    locals_t *L = zsp_frame_locals(ret, locals_t);

    /* Solve head-action resources across all branches (Section 5.1) */
    solve_parallel_heads(tb, &L->head_bindings);

    /* Initialize join */
    zsp_join_init(&L->join, thread, N_BRANCHES, ZSP_JOIN_ALL, tb);

    /* Spawn child threads */
    for (int i = 0; i < N_BRANCHES; i++) {
        zsp_thread_t *child = zsp_timebase_thread_create(
            tb, branch_task_fns[i], ZSP_THREAD_FLAGS_NONE,
            /* pass branch context and head bindings */
            &L->branch_ctx[i], &L->head_bindings);
        child->exit_f = &join_child_exit;
        child->rval = (uintptr_t)&L->join;
    }

    /* Block parent until join completes */
    ret->idx = IDX_PAR_JOIN;
    thread->flags |= ZSP_THREAD_FLAGS_BLOCKED;
    break;
}
case IDX_PAR_JOIN: {
    /* All joined branches complete; continue */
    locals_t *L = zsp_frame_locals(ret, locals_t);
    /* ... next statement ... */
}
```

**join_branch**: `remaining` is set to the count of labeled branches.
Only those branches' `exit_f` calls `zsp_join_signal`; other branches
use a no-op exit.

**join_none**: The parent is not blocked; `ret->idx = IDX_PAR_JOIN` is
set but the thread is NOT marked `BLOCKED`, so it continues
immediately. A separate join for the non-joined branches is attached to
the enclosing sequence block.

**join_first(N)**: `remaining` is initialized to N. First N child
completions wake the parent. Remaining children continue running and
are joined at the enclosing sequence boundary.

**join_select(N)**: At solve time, N branches are randomly selected.
Only those branches' exit functions signal the join. Remaining branches
signal a separate deferred join.

### 4.3 Schedule Block

Treated as a parallel block with runtime resource arbitration (same
spawn pattern as 4.2). The scheduler's round-robin dispatch plus
resource-pool blocking naturally produces a legal ordering without
explicit scheduling analysis.

### 4.4 Repeat (count)

```c
case IDX_REPEAT_INIT: {
    locals_t *L = zsp_frame_locals(ret, locals_t);
    L->repeat_i = 0;
    L->repeat_n = evaluate_count_expr(L);
    /* fall through */
}
case IDX_REPEAT_BODY: {
    locals_t *L = zsp_frame_locals(ret, locals_t);
    if (L->repeat_i >= L->repeat_n) {
        ret->idx = IDX_REPEAT_DONE;
        break;  /* falls through to next case immediately */
    }
    solve_and_exec_body(tb, thread, L);
    L->repeat_i++;
    ret->idx = IDX_REPEAT_BODY;
    zsp_timebase_yield(thread);
    break;
}
case IDX_REPEAT_DONE:
    /* ... */
```

### 4.5 Repeat-while

```c
case IDX_REPEAT_WHILE_BODY: {
    locals_t *L = zsp_frame_locals(ret, locals_t);
    solve_and_exec_body(tb, thread, L);
    if (evaluate_while_expr(L)) {
        ret->idx = IDX_REPEAT_WHILE_BODY;
        zsp_timebase_yield(thread);
    } else {
        ret->idx = IDX_NEXT;
    }
    break;
}
```

### 4.6 Foreach

```c
case IDX_FOREACH_INIT: {
    locals_t *L = zsp_frame_locals(ret, locals_t);
    L->foreach_i = 0;
    L->foreach_n = collection_size(L->collection);
}
case IDX_FOREACH_BODY: {
    locals_t *L = zsp_frame_locals(ret, locals_t);
    if (L->foreach_i >= L->foreach_n) {
        ret->idx = IDX_FOREACH_DONE;
        break;
    }
    L->iterator = &L->collection[L->foreach_i];
    solve_and_exec_iteration(tb, thread, L);
    L->foreach_i++;
    ret->idx = IDX_FOREACH_BODY;
    zsp_timebase_yield(thread);
    break;
}
```

### 4.7 Select

```c
case IDX_SELECT: {
    locals_t *L = zsp_frame_locals(ret, locals_t);
    int branch = solve_select_weighted(L, &tb_rng);
    switch (branch) {
    case 0: ret->idx = IDX_SELECT_BR_0; break;
    case 1: ret->idx = IDX_SELECT_BR_1; break;
    /* ... */
    }
    break;
}
```

### 4.8 If-Else / Match

```c
case IDX_IF: {
    locals_t *L = zsp_frame_locals(ret, locals_t);
    if (evaluate_condition(L))
        ret->idx = IDX_IF_TRUE;
    else
        ret->idx = IDX_IF_FALSE;
    break;
}
```

### 4.9 Replicate

When the bound is constant, the code generator expands in-place.
When the bound is a rand field, it generates a dynamic spawn loop
with a maximum-bounded array of child contexts:

```c
case IDX_REPLICATE: {
    locals_t *L = zsp_frame_locals(ret, locals_t);
    L->rep_n = solve_replicate_count(L);
    /* spawn L->rep_n children in enclosing context (par/sched/seq) */
    for (int i = 0; i < L->rep_n; i++) {
        init_replicated_branch(&L->rep[i], i);
        zsp_timebase_thread_create(tb, &replicated_task, ...);
    }
    break;
}
```

### 4.10 Atomic Block

No yields are emitted within the atomic block's sub-activity. All
actions execute sequentially in a single scheduler invocation (a single
call to `zsp_timebase_run` runs through all the idx cases without
yielding). Resource-acquisition blocks are still allowed (they block
the thread, but no other thread can interleave inferred actions since
action inference is resolved at code-generation time).

---

## 5. Resource Management

### 5.1 Head-Action Coordinated Solve

When a parallel block is entered, the runtime must guarantee that the
initial actions on all branches can execute concurrently without
resource conflicts.

**Algorithm**:

1. **Collect head claims**: For each branch, identify the first action's
   resource claims (lock/share fields, pool, constraint info).

2. **Invoke the binding solver**: Use the AllDifferent-based binding
   solver (from `zuspec-solver/binding-solver-design.md`) to assign
   `instance_id` values to all head-action lock claims simultaneously.

3. **Fix head assignments**: The solved `instance_id` values are stored
   in each branch's context. The head action calls
   `zsp_resource_force_lock` -- no waiter logic needed.

Generated code for head-action solve:

```c
static int solve_par_heads(
    zsp_timebase_t *tb,
    par_head_bindings_t *out,
    uint64_t seed)
{
    /* Precomputed feasible sets (static const, in ROM) */
    static const int16_t br0_domain[] = {0, 1, 2, 3};
    static const int16_t br1_domain[] = {0, 1, 2, 3};

    /* AllDifferent assignment */
    return alldiff_assign_2(
        br0_domain, 4, br1_domain, 4,
        &out->branch[0].r_id,
        &out->branch[1].r_id,
        seed);
}
```

For 2-4 branch parallel blocks (common case), the matching can be
inlined as direct combinatorial logic.

### 5.2 Runtime Resource Acquisition (Tail Actions)

After the head action, subsequent actions on each branch acquire
resources at runtime. The generated code follows the try-lock + block
pattern:

```c
case IDX_TAIL_ACQUIRE: {
    locals_t *L = zsp_frame_locals(ret, locals_t);

    /* Solve constraints to get feasible instance_id set */
    L->feasible = solve_resource_domain(L);

    /* Try each feasible instance in canonical order */
    L->chosen_id = -1;
    for (int i = 0; i < L->feasible_count; i++) {
        if (zsp_resource_try_lock(L->pool, L->feasible[i]) == 0) {
            L->chosen_id = L->feasible[i];
            break;
        }
    }

    if (L->chosen_id < 0) {
        /* All busy -- block until any instance is released */
        ret->idx = IDX_TAIL_ACQUIRE;  /* retry on wakeup */
        zsp_resource_add_lock_waiter(L->pool, thread);
        break;  /* thread is now BLOCKED */
    }

    /* Acquired. Continue to execution. */
    ret->idx = IDX_TAIL_EXEC;
    break;
}
```

### 5.3 Deadlock Prevention via Lock Ordering

The code generator imposes a canonical acquisition order on all
resource claims within each action:

1. Sort claims by (pool_id ascending, then instance_id ascending).
2. Emit acquisition code in that sorted order.

Since all actions acquire in the same global order, circular-wait is
impossible. This is the standard resource-ordering technique. The cost
is negligible: all claims must be acquired before the action executes
regardless of order.

### 5.4 Resource Lifetime and Release

A resource lock is held for the duration of the action's execution
(including its entire sub-activity). Release happens when the action's
frame is popped:

```c
case IDX_ACTION_DONE: {
    locals_t *L = zsp_frame_locals(ret, locals_t);
    zsp_resource_unlock(L->pool, L->r_id);
    ret = zsp_timebase_return(thread, 0);
    break;
}
```

`zsp_resource_unlock` checks for waiters and calls
`zsp_timebase_schedule` to wake one blocked thread.

Share claims use reference counting: `share_count[id]++` on acquire,
`share_count[id]--` on release. A lock can only be acquired when
`share_count[id] == 0`.

---

## 6. Constraint Solving Integration

### 6.1 Per-Action Solve

Each action traversal triggers a constraint solve for that action's
rand fields, using the existing `zuspec-solver` C API (`SolveProblem`
+ `SolveCtx`).

**Compile-time constraint specialization**: The code generator emits
a specialized C solve function per action type. No IR interpretation
at runtime:

```c
static SolveResult solve_dma_transfer(
    solve_buf_t *buf, uint64_t seed,
    dma_transfer_fields_t *out)
{
    SolveProblem *sp = solve_problem_init(buf->data, buf->size);

    problem_add_var(sp, 0, 32, 0, 0, 0xFFFFFFFF);   /* src_addr */
    problem_add_var(sp, 1, 32, 0, 0, 0xFFFFFFFF);   /* dst_addr */
    problem_add_var(sp, 2, 16, 0, 1, 4096);          /* length   */

    /* constraint: src_addr[1:0] == 0 */
    ExprRef v0 = expr_var(sp, 0);
    ExprRef mask = expr_const(sp, 3, 0);
    problem_add_constraint(sp,
        expr_binary(sp, BIN_EQ,
            expr_binary(sp, BIN_BAND, v0, mask),
            expr_const(sp, 0, 0)));

    SolveCtx *ctx = solver_create(buf->ctx_data, buf->ctx_size,
                                   buf->block_alloc);
    solver_compile(ctx, sp);
    SolveResult rc = solver_solve(ctx, &(SolveOpts){.seed = seed});

    if (rc == SOLVE_OK) {
        out->src_addr = solver_get_value(ctx, 0);
        out->dst_addr = solver_get_value(ctx, 1);
        out->length   = solver_get_value(ctx, 2);
    }
    solver_destroy(ctx);
    return rc;
}
```

### 6.2 Solver Buffer Reuse

A fixed-size buffer is allocated per thread (via `zsp_timebase_alloca`)
or statically per-coroutine. The buffer is reused across solve calls
within the same thread via `solve_problem_reset`.

### 6.3 Solver-Free Fast Path

The code generator detects actions where constraints fully determine
field values (or only unconstrained fields exist) and emits a direct
computation instead of invoking the solver.

### 6.4 Cross-Action Constraints

- **Forward references**: Deferred until the referenced action is
  solved. The constraint becomes a constant bound.
- **Backward references**: The referenced action's solved values are
  used as constants in the current solve.

### 6.5 Pre_solve / Post_solve Exec Blocks

1. Pre_solve runs before the solve function.
2. Solve runs.
3. Post_solve runs after solve, may read solved values.

For parallel head actions, all pre_solve blocks run sequentially
(branch 0, 1, ...) before the coordinated head-action solve.

---

## 7. Data Flow Objects

### 7.1 Buffers

Buffer flow objects create scheduling dependencies. In the coroutine
model:

- Same sequential block: ordering is inherent (earlier `idx` case).
- Different branches of a schedule block: the producer signals a
  buffer-ready event, the consumer blocks on it (same pattern as
  `zsp_channel_t`).

```c
typedef struct {
    uint8_t         valid;
    zsp_thread_t   *waiter;      /* consumer blocked until valid */
    zsp_timebase_t *tb;
    /* user-defined fields (generated per buffer type) */
    mem_segment_s   seg;
} zsp_buffer_instance_t;
```

### 7.2 Streams

Producer and consumer are spawned as parallel branches. Data exchange
uses a shared struct with channel-style blocking.

### 7.3 States

Single-instance pools with `current`/`previous`/`initial` fields:

```c
typedef struct {
    power_state_s   current;
    power_state_s   previous;
    uint8_t         initial;   /* 1 until first write */
} zsp_state_pool_t;
```

---

## 8. Component and Pool Binding

### 8.1 Static Elaboration

Component hierarchy and pool bindings are resolved at code-generation
time. The code generator emits:

- A `zsp_component_t`-derived struct per component instance.
- Static `zsp_resource_pool_t` instances for each resource pool.
- For each action type, the mapping from resource claim fields to
  their bound pool is resolved through bind directives.

```c
/* Generated */
static zsp_resource_pool_t dma0_channels;
static zsp_resource_pool_t dma1_channels;
static zsp_resource_pool_t cpu_cores;

void init_component_tree(zsp_init_ctxt_t *ctxt) {
    zsp_resource_pool_init(ctxt, &dma0_channels, 2);
    zsp_resource_pool_init(ctxt, &dma1_channels, 2);
    zsp_resource_pool_init(ctxt, &cpu_cores, 4);
}
```

### 8.2 Component Assignment

When `comp` is fixed by `with` constraints (common case), the code
generator binds it statically. Otherwise, the solver includes `comp`
as a small finite-domain variable.

---

## 9. Code Generation Architecture

### 9.1 Generated Artifacts

| File | Contents |
|------|----------|
| `zsp_gen_types.h` | Struct definitions for PSS data types, resources, buffers, states |
| `zsp_gen_components.h/c` | Component tree, pool declarations, static init |
| `zsp_gen_activities.h/c` | Task functions for all compound action activities |
| `zsp_gen_solvers.h/c` | Per-action-type constraint solve functions |
| `zsp_gen_domains.h` | Static const feasible-set tables for binding solver |
| `zsp_gen_main.c` | Timebase setup, root action dispatch |

### 9.2 Runtime Library (linked, not generated)

All existing `zsp_*.c` files from `zuspec-be-sw/share/rt/`, plus:

| New Module | Contents |
|------------|----------|
| `zsp_resource.c` | Resource pool lock/share/release (Section 3.1) |
| `zsp_join.c` | Join group for parallel blocks (Section 3.2) |
| `zsp_rt_matching.c` | Hopcroft-Karp matching for head-action binding |
| `zsp_rt_alldiff.c` | AllDifferent propagator |

### 9.3 Memory Layout

```
[Component tree + pools]  -- static + init-time allocation via zsp_alloc_t
[Thread array]            -- static, max_concurrent_threads entries
[Solver buffer]           -- per-thread, sized to max constraint system
[Stack-block free lists]  -- managed by zsp_timebase_t (4K/8K caches)
```

`max_concurrent_threads` is computed at code-generation time from the
activity graph's maximum parallel/schedule width.

---

## 10. Worked Example: Parallel DMA Transfer

### 10.1 PSS Model

```pss
resource channel_s { rand bit[3:0] priority; }

component dma_c {
    pool[2] channel_s channels;
    bind channels *;

    action transfer {
        lock channel_s chan;
        rand bit[31:0] src_addr, dst_addr;
        rand bit[15:0] length;
        constraint length in [1..4096];
        constraint src_addr[1:0] == 0;
        constraint dst_addr[1:0] == 0;
    }
}

component pss_top {
    dma_c dma;
    action par_xfer {
        activity {
            parallel {
                do dma_c::transfer;
                do dma_c::transfer;
            }
        }
    }
}
```

### 10.2 Generated Code

```c
/* --- Branch task function --- */
static zsp_frame_t *par_xfer_branch_task(
    zsp_timebase_t *tb,
    zsp_thread_t   *thread,
    int             idx,
    va_list        *args)
{
    zsp_frame_t *ret = thread->leaf;

    typedef struct {
        zsp_resource_pool_t *pool;
        int32_t              chan_id;     /* pre-assigned by head solve */
        dma_transfer_fields_t fields;
        solve_buf_t          solve_buf;
    } locals_t;

    switch (idx) {
    case 0: {
        ret = zsp_timebase_alloc_frame(
            thread, sizeof(locals_t), &par_xfer_branch_task);
        locals_t *L = zsp_frame_locals(ret, locals_t);
        if (args) {
            L->pool    = va_arg(*args, zsp_resource_pool_t *);
            L->chan_id = va_arg(*args, int32_t);
        }

        /* Head action: resource pre-assigned, force-lock */
        zsp_resource_force_lock(L->pool, L->chan_id);

        /* Solve remaining fields */
        solve_dma_transfer(&L->solve_buf, tb_rng_next(tb), &L->fields);

        ret->idx = 1;
        zsp_timebase_yield(thread);
        break;
    }
    case 1: {
        locals_t *L = zsp_frame_locals(ret, locals_t);

        /* Execute body */
        dma_transfer_exec_body(&L->fields);

        /* Release resource */
        zsp_resource_unlock(L->pool, L->chan_id);

        /* Done */
        ret = zsp_timebase_return(thread, 0);
        break;
    }
    }
    return ret;
}

/* --- Parent activity task function --- */
static zsp_frame_t *par_xfer_task(
    zsp_timebase_t *tb,
    zsp_thread_t   *thread,
    int             idx,
    va_list        *args)
{
    zsp_frame_t *ret = thread->leaf;

    typedef struct {
        zsp_join_t join;
        int32_t    head_ids[2];
    } locals_t;

    switch (idx) {
    case 0: {
        ret = zsp_timebase_alloc_frame(
            thread, sizeof(locals_t), &par_xfer_task);
        locals_t *L = zsp_frame_locals(ret, locals_t);

        /* Head-action binding: 2 claims, pool size 2 */
        uint64_t seed = tb_rng_next(tb);
        L->head_ids[0] = seed & 1;
        L->head_ids[1] = 1 - L->head_ids[0];

        /* Init join (wait for both) */
        zsp_join_init(&L->join, thread, 2, ZSP_JOIN_ALL, tb);

        /* Spawn branches */
        for (int i = 0; i < 2; i++) {
            zsp_thread_t *child = zsp_timebase_thread_create(
                tb, &par_xfer_branch_task, ZSP_THREAD_FLAGS_NONE,
                &dma_channels_pool, L->head_ids[i]);
            child->exit_f = &join_child_exit;
            child->rval = (uintptr_t)&L->join;
        }

        /* Block until join completes */
        ret->idx = 1;
        thread->flags |= ZSP_THREAD_FLAGS_BLOCKED;
        break;
    }
    case 1: {
        /* Both branches done */
        ret = zsp_timebase_return(thread, 0);
        break;
    }
    }
    return ret;
}
```

### 10.3 Execution Trace

```
timebase_run: pop par_xfer_task (idx=0)
  -> head solve: branch[0].chan=1, branch[1].chan=0
  -> join_init(remaining=2)
  -> thread_create branch[0], thread_create branch[1]
  -> par_xfer BLOCKED on join

timebase_run: pop branch[0] (idx=0)
  -> force_lock(channels, id=1)
  -> solve_dma_transfer: src=0x2000, dst=0x3000, len=256
  -> SUSPEND (yield)

timebase_run: pop branch[1] (idx=0)
  -> force_lock(channels, id=0)
  -> solve_dma_transfer: src=0x4000, dst=0x5000, len=128
  -> SUSPEND (yield)

timebase_run: pop branch[0] (idx=1)
  -> exec_body
  -> unlock(channels, id=1)
  -> return -> exit_f -> join_signal(remaining=1)

timebase_run: pop branch[1] (idx=1)
  -> exec_body
  -> unlock(channels, id=0)
  -> return -> exit_f -> join_signal(remaining=0)
     -> schedule(par_xfer_task)

timebase_run: pop par_xfer_task (idx=1)
  -> return -> DONE
```

---

## 11. Correctness Argument

### 11.1 Resource Safety

No two concurrent actions hold a lock on the same resource instance.
- Head actions: AllDifferent guarantees distinct `instance_id`.
- Tail actions: `zsp_resource_try_lock` checks `lock_held[id]` and
  `share_count[id]` before granting.
- Between head and tail: sequential within a branch.

### 11.2 Deadlock Freedom

Canonical lock ordering (pool_id, then instance_id) prevents
circular wait. The scheduler detects the degenerate case (all
threads blocked, no events) and panics.

### 11.3 Constraint Completeness

Per-step solving produces the same solution space as monolithic
solving when cross-action constraints only reference actions within
the same sequential chain. Cross-branch resource-field constraints
are handled by the head-action binding solver for head actions, and
by retry-on-wakeup for tail actions.

---

## 12. Required Runtime Bug Fixes

Issues found during review of the existing runtime that should be
addressed before or during implementation:

### 12.1 Active Count Double-Counting (zsp_timebase.c)

`zsp_timebase_schedule` always increments `active`. When
`zsp_resource_unlock` or `zsp_channel_notify_*` calls
`zsp_timebase_schedule` to wake a blocked thread, `active` is
incremented, but it was not decremented when the thread blocked
(blocking just sets the flag and does not add to the ready queue).
This means `active` inflates over time.

**Fix**: Do not increment `active` in `zsp_timebase_schedule`. Instead,
increment only in `zsp_timebase_thread_create`/`thread_init` (when a
thread is first born), and decrement only when a thread truly completes
(leaf == NULL). Blocking/waking should not change the count.

### 12.2 fprintf in zsp_thread_return (zsp_thread.c:280)

Unconditional `fprintf(stdout, "[return] Freeing block...")` in
production code. Should be removed or guarded with `#ifdef ZSP_DEBUG`.

### 12.3 va_arg Promotion Mismatch (zsp_thread.c:343)

`va_arg(*args, uint8_t)` and `va_arg(*args, uint16_t)` are undefined
behavior. The timebase version handles this correctly. Once
`zsp_thread.h` is retired, this is moot.

### 12.4 zsp_memory.c Mixed Allocator

Paged-mode pages use `malloc()` directly instead of going through
`ctxt->alloc`. Should use the allocator consistently.

### 12.5 Retire zsp_thread.h/zsp_thread.c

The old scheduler (`zsp_scheduler_t`) and old `zsp_thread_t` (with the
sched/next union) are superseded by `zsp_timebase`. They share struct
names (`zsp_frame_s`, `zsp_frame_wrap_s`) that will cause redefinition
errors if both are included. `zsp_thread.h` should be retired; any code
still referencing it should be migrated to `zsp_timebase.h`.

---

## 13. Open Issues

### 13.1 Variable-Bound Replicate in Parallel Context

When `replicate(count)` appears inside a parallel block and `count`
is a rand field, the number of branches is unknown until `count` is
solved. The code generator must allocate the child thread array to the
maximum possible `count` (from domain analysis) or use
`zsp_timebase_alloca` for dynamic sizing.

### 13.2 Flow-Object Inference at Runtime

Our model assumes full elaboration at code-generation time. The code
generator needs a complete PSS scenario elaboration engine.

### 13.3 Schedule Block Optimality

Runtime arbitration may produce less-concurrent execution than
solve-time scheduling. Acceptable for correctness; a heuristic
ordering emitted at code-generation time could improve throughput.

### 13.4 Compound Action Resource Holding

Locks held for the duration of a compound action's sub-activity can
starve other branches. This is correct per the LRM but may cause
liveness issues in deep activity trees.

### 13.5 Cross-Branch Pre_solve Dependencies

If action A's pre_solve on branch 1 writes a shared component field
that action B's constraint on branch 2 reads, there is a race. The
code generator should detect this and serialize pre_solve execution.

### 13.6 Solver Limitations

The existing zuspec-solver has known gaps: `BIN_SUB` unhandled in
compile, const-var operand order falls through. These must be fixed
before generated solve functions can rely on the native solver for
all constraint patterns.

### 13.7 Tail Action with No Feasible Instance

When all feasible instances are permanently held (long compound
action on another branch), the blocked thread waits indefinitely.
A configurable timeout should be added to resource acquisition.

### 13.8 Stack Block Sizing

The current runtime uses fixed 4K/8K stack blocks. Activity task
functions with large `locals_t` structs may exceed a single block.
The code generator should compute the maximum locals size and emit
a compile-time assertion if it exceeds the block size, or request a
larger block via a new `zsp_timebase_alloc_frame_large`.

---

## 14. Overlooked Opportunities

### 14.1 Coroutine Pooling with Priority Scheduling

Replace round-robin with a priority queue favoring coroutines that
hold fewer resources or are closer to completion.

### 14.2 Constraint Template Sharing

Multiple traversals of the same action type share constraint
structure. Emit one parameterized solve function, not N copies.

### 14.3 Two-Level Matching for Nested Parallel Blocks

Inner parallel blocks exclude resources already held by the outer
branch from the inner solve's AllDifferent domains.

### 14.4 Trace-Driven Replay

Binary trace records solve seeds and resource assignments. Replay
with identical seeds reproduces failures deterministically.

### 14.5 Incremental SolveCtx for Repeat Loops

Preserve compiled propagators across iterations; only reset domains
and trail. Requires a `solver_reset` API addition.

### 14.6 Unified AllDifferent Propagator in Native Solver

Add AllDifferent as a first-class propagator, reusing the matching
engine. Benefits `unique` constraints (PSS 16.1.9) beyond just
resource binding.

### 14.7 Executor-Aware Thread Grouping

Map PSS executors (LRM 24.6) to per-executor ready queues within the
timebase. The PSS `yield` statement maps to `zsp_timebase_yield`,
which returns to the scheduler and runs another thread on the same
executor group.

### 14.8 Stack Block Free-List Per Thread

Currently the free-list cache is global in `zsp_timebase_t`. For
embedded targets with tight memory, per-thread free-lists with a
maximum cache depth would bound peak memory usage.

---

## 15. Implementation Roadmap

### Phase 1: Runtime Additions
- `zsp_resource_pool_t` (lock/share/release, waiter lists)
- `zsp_join_t` (parallel join groups)
- Deadlock detection in scheduler loop
- Fix active-count double-counting
- Retire `zsp_thread.h`/`zsp_thread.c`

### Phase 2: Code Generator Core
- Activity-graph IR for seq/par/schedule/repeat/etc.
- Activity-to-C emitter (task functions targeting zsp_timebase API)
- Per-action solve function emitter (SolveProblem construction)

### Phase 3: Binding Solver Integration
- Head-action coordinated solve using AllDifferent/matching
- Precomputed feasible-set table generation
- Small-instance matching inlining (2-4 branches)

### Phase 4: Data Flow Objects
- Buffer/stream/state pool management using event pattern
- Event-based synchronization for cross-branch buffer dependencies

### Phase 5: Solver Optimizations
- Solver-free fast path for fully determined actions
- Incremental SolveCtx for repeat loops
- Constraint template sharing

### Phase 6: Tracing and Coverage
- Binary trace emitter
- Replay mode
- Post-processing coverage collector

---

## 16. Summary

The design decomposes PSS's monolithic solve-then-execute model into
a stream of small per-action solves orchestrated by the existing
zuspec-be-sw `zsp_timebase` coroutine scheduler. The critical
coordination point -- resource assignment for parallel-branch head
actions -- uses the AllDifferent binding solver. All subsequent
resource acquisition is deferred to runtime with cooperative blocking.
Canonical lock ordering guarantees deadlock freedom.

The design targets the actual runtime's frame-chain coroutine model:
each activity compiles to a `zsp_task_func` with `idx`-based dispatch,
frames allocated from cached stack blocks, and blocking via the
existing SUSPEND/BLOCKED flag mechanism. Three new primitives are
required: `zsp_resource_pool_t`, `zsp_join_t`, and deadlock detection.

Key design decisions:
- **Per-step solving** (not monolithic): Bounds memory, enables
  streaming execution, matches embedded constraints.
- **Frame-chain coroutines** (not flat switch-on-enum): Matches the
  existing runtime, supports nested sub-activities naturally.
- **Head-action coordinated solve** (not fully runtime): Guarantees
  parallel blocks start conflict-free.
- **Canonical lock ordering** (not wait-for-graph): Zero runtime
  overhead, provably correct.
- **Schedule = parallel + runtime arbitration** (not solve-time
  scheduling): Sidesteps co-optimization, always produces a legal
  ordering.
