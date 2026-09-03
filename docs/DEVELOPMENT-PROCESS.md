# Development Process

How this demo gets built: a spec-driven pipeline designed so the implementation
phase can run as autonomously as possible.

**Core idea:** autonomy is bought at spec time, not at implementation time.
Every ambiguity left in the spec becomes a decision an unsupervised agent makes
for you — confidently, and possibly for an hour. This process front-loads
human attention so the build phase can run unattended.

---

## The four stages

| Stage | Skill / command | Artifact | Human involvement |
|-------|-----------------|----------|-------------------|
| 1. Design | `superpowers:brainstorming` | `docs/superpowers/specs/YYYY-MM-DD-<topic>-design.md` | **High** — answer questions one at a time, approve each design section, review the written spec |
| 2. Plan | `superpowers:writing-plans` | `docs/superpowers/plans/YYYY-MM-DD-<feature>.md` | **Medium** — review the task breakdown once |
| 3. Build | `superpowers:subagent-driven-development` | Code + commits | **Low** — runs task-by-task without check-ins |
| 4. Verify | `/code-review`, `superpowers:requesting-code-review` | Findings, then fixes | **Medium** — adjudicate findings |

The handoff between stages is what makes this work. The plan is written for
"an engineer with zero context and questionable taste," decomposed into
bite-sized steps:

```
write the failing test → run it, confirm it fails → implement the minimum →
run tests, confirm they pass → commit
```

That is precisely the shape an agent can execute without supervision.

---

## Stage 1 — Design

Run `superpowers:brainstorming`. It classifies the work (spike / bounded /
architectural); a new demo is **architectural**, so it takes the full path:

1. Explore project context
2. Clarifying questions, one at a time
3. 2–3 approaches with trade-offs and a recommendation
4. Design presented in sections, approved section by section
5. Spec written to `docs/superpowers/specs/` and committed
6. Spec self-review (placeholders, contradictions, ambiguity, scope)
7. **You** review the spec before anything proceeds

**Hard gate:** no code, no scaffolding, no implementation skill until you
approve. This holds regardless of how simple a task looks.

### What the spec must settle

The spec is the binding authority during autonomous execution — when an agent
hits a conflict, it consults the spec, makes a ruling, logs it, and keeps
going. So the spec must be decisive about:

- **The demo story** — which Temporal capability this proves (saga with
  compensation, long-running human-in-the-loop, AI agent, teaching the
  primitives). Everything else follows from this.
- **The domain** — onboarding of what, and which activities are realistic
- **Workflow boundaries** — one workflow or parent/child, and why
- **Failure behavior** — what retries, what compensates, what escalates
- **The human-in-the-loop surface** — signals vs. updates, and the timeout policy
- **Audience and format** — live demo, self-serve repo, or workshop
- **SDK scope** — Python-only, or an SDK-agnostic contract (see below)

### On multi-SDK

Sibling demos (`canonical-ai-demo`, `money-transfer-demo`,
`temporal-order-management-demo`) all grew into multi-SDK repos. If that is
plausible here, write a `CONTRACT.md` — an SDK-agnostic spec of the workflow
IDs, task queue, signal/query/update names, and payload shapes.

That contract is also what makes *parallel* autonomous work possible: separate
agents can implement the Go, Java, and TypeScript workers simultaneously,
each verified against the same contract.

---

## Stage 2 — Plan

Run `superpowers:writing-plans` against the approved spec. It produces a task
list where each task is the smallest unit that carries its own test cycle and
is worth a fresh reviewer's gate.

**Task 1 should be the test harness, not a feature.** It is the gate every
later task depends on. See below.

---

## Stage 3 — Build (the autonomous part)

### Options

| Tool | What it does | Best for |
|------|--------------|----------|
| **`superpowers:subagent-driven-development`** | Fresh subagent per plan task, spec+quality review after each, broad review at the end. Does not stop to ask "should I continue?" — it makes rulings and logs them. | **The default.** Highest quality per unattended hour. |
| **`/ralph-loop "<prompt>" --completion-promise "DONE" --max-iterations 50`** | A Stop hook blocks session exit and re-feeds the same prompt until the completion phrase appears. | Grind-until-green work with a hard, machine-checkable finish line. Requires a real test suite or it loops on vibes. |
| **`/loop <interval> <prompt>`** | Re-runs a prompt on a schedule. | Polling external state — a CI run, a long worker soak test. Not a build driver. |
| **`/schedule`** | Cron'd cloud agents. | Overnight or recurring runs. |

`subagent-driven-development` executes a *known plan*; `ralph-loop` iterates
toward a *measurable goal*. For work driven by a written plan, use the first.

### What stops an autonomous run

Only four things — everything else gets decided and logged as a ruling:

1. An irreversible or destructive operation
2. A security-sensitive action
3. A side effect outside the worktree that norms say you ask about first
   (a merge, a push to a shared branch, a publish)
4. A plan so broken that every path forward is a guess

---

## Stage 4 — Verify

- `/code-review` — correctness bugs plus reuse/simplification findings.
  `--fix` applies them; `--comment` posts them inline on a PR.
- `superpowers:requesting-code-review` — full review before merging
- `superpowers:finishing-a-development-branch` — decide how the work integrates

---

## The four things that actually buy autonomy

### 1. An executable verification gate

The single most important prerequisite. An unattended agent needs a command
that objectively says pass/fail. For a Temporal demo that means, from day one:

- **Time-skipping tests** — `WorkflowEnvironment.start_time_skipping()` so a
  seven-day onboarding SLA timer tests in milliseconds
- **Replay tests** against saved histories — the highest-value gate for
  autonomous work, because it catches the failure mode agents cause most: an
  innocent-looking edit to workflow code that breaks determinism
- **Activity unit tests** via `ActivityEnvironment`

Without these, an autonomous loop will happily produce a workflow that calls
`requests.get()` inside `workflows/` and never notice.

### 2. A spec precise enough to settle arguments

See Stage 1. Ambiguity is where unattended runs go wrong.

### 3. A `CLAUDE.md` at the repo root

Agents read it every session. It should carry:

- Run and test commands (`uv run ...`, worker start, dev server start)
- The task queue name and workflow IDs
- The determinism rule: no I/O, no clocks, no randomness in `workflows/`;
  everything non-deterministic goes in an activity
- Project layout and where new activities/workflows belong

### 4. Worktree isolation

`superpowers:using-git-worktrees` — so an unattended run cannot disturb a
working tree you care about.

---

## Reference material

Temporal SDK samples are cloned locally and can be added to a session with
`/add-dir`:

| SDK | Path |
|-----|------|
| Python | `~/src/python/samples-python` |
| Go | `~/src/go/samples-go` |
| TypeScript | `~/src/typescript/samples-typescript` |
| Java | `~/src/java/samples-java` |

Most relevant Python samples for this demo: `message_passing` (signals,
queries, updates), `updatable_timer` (durable SLA timers), `polling`,
`schedules`, and `replay` (the determinism gate).

The `temporal:temporal-developer` skill provides SDK guidance, determinism
rules, patterns, and troubleshooting references.

---

## Current status

- [x] Repo created
- [ ] **Stage 1 — Design.** Blocked on the demo story question: which Temporal
      capability should this prove?
- [ ] Stage 2 — Plan
- [ ] Stage 3 — Build
- [ ] Stage 4 — Verify
