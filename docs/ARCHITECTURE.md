# ACC — Architecture decisions

37 numbered records. Many of them document **bugs found by running the system,
not by reading it** — each one is now locked by a regression test.

## Diagrams

- `diagrams/architecture.mmd` — reference architecture
- `diagrams/hero_sequence.mmd` — hero scenario sequence

Render with `mmdc -i docs/diagrams/architecture.mmd -o architecture.svg`, or
paste into <https://mermaid.live>.

---

## Index

| # | Decision | Found by |
|---|---|---|
| 001 | Mission state is the source of truth | Design |
| 002 | The Gateway pipeline is single and non-bypassable | Design |
| 003 | Recovery is itself governed | Design |
| 004 | The idempotency key excludes the attempt number | Design |
| 005 | Three agent modes, one with no model at all | Design |
| 006 | Dual persistence and dual event bus | Design |
| 007 | The autonomy boundary is a product feature, not public data | **Live testing** |
| 008 | The task claim is atomic, not optimistic | **Race reproduction** |
| 009 | An agent that cannot start is a mission failure | **Live testing** |
| 010 | Mission risk is a high-water mark | **Live testing** |
| 011 | One source of truth for configuration | **User's machine** |
| 012 | Tests are hermetic against `.env` | **Hostile `.env`** |
| 013 | CORS: wildcards do not exist in `allow_origins` | **Cloud-mode probe** |
| 014 | Auto-instrumentation is probed, not assumed | **User's machine** |
| 015 | Dev tooling depends on no shell | **User's machine** |
| 016 | One source of truth for the API key | **User's machine** |
| 017 | Configuration must say where it comes from | **User's machine** |
| 018 | A mission always has a lever or an explicit end | **Live testing** |
| 019 | A diagnostic that wrongly reassures is harmful | **Live testing** |
| 020 | An action with no visible effect is perceived as a bug | **User report** |
| 021 | Indistinguishable missions prove nothing | **User report** |
| 022 | Absence of data is not a perfect score | **Live testing** |
| 023 | The UI must not extend a finished activity | **Live testing** |
| 024 | Idempotency protects ACTIONS, never OBSERVATIONS | **Live testing** |
| 025 | A decision modal must reset on every request | **User report** |
| 026 | Do not re-ask the same question when nothing changed | **Live testing** |
| 027 | You authorise an action, not an abstention | **Live testing** |
| 028 | Reporting a failure is not being in failure | **Log review** |
| 029 | Handing off is not recovering | **Live testing** |
| 030 | A finished mission leaves nothing "in progress" | **Live testing** |
| 031 | Never record an audit event that did not happen | **Live testing** |
| 032 | A demo script is code, not prose | **Script audit** |
| 033 | A checkpoint label is an assertion, not a tag | **Log review** |
| 034 | A setting that does nothing is worse than none | **Cost audit** |
| 035 | Cost guardrails are tested, not documented | Design |
| 036 | Model choice follows the thesis, not raw power | **Rules review** |
| 037 | A test double that imports what it replaces doubles nothing | **User's machine** |

---

## ADR-001 — Mission state is the source of truth

**Context.** An agent holding state in memory loses everything when the
container restarts. Cloud Run can recycle an instance at any moment.

**Decision.** Every consequential decision is persisted before being published.
Model memory is a working cache; it is never the state.

**Consequence.** `MODEL MEMORY != MISSION STATE`. An agent *proposes* an
observation; only the Mission Engine makes it durable via
`MemoryService.write`.

---

## ADR-002 — The Gateway pipeline is single and non-bypassable

**Decision.** `IDENTITY → CAPABILITY → POLICY → APPROVAL → IDEMPOTENCY → TOOL →
MODEL ARMOR → AUDIT`. No other path to an enterprise system exists in the code.

**Verification.** `tests/integration/test_gateway.py` covers each barrier
separately: missing capability, incomplete identity, suspended agent, threshold
exceeded, ceiling exceeded, idempotent replay, poisoned content.

---

## ADR-003 — Recovery is itself governed

**Context.** The classic trap: a recovery component that bypasses policy
"because it is an emergency". That is exactly the path an attacker would aim at.

**Decision.** The Failure Twin's `RecoveryPlan` goes back through the Policy
Engine under the `recovery.apply` capability. A HIGH-risk plan requires human
approval.

**Consequence.** A security or authorisation failure never triggers free
recovery: the only exits are `ESCALATE` or `ABORT`
(`FailureClass.requires_safe_hold`).

---

## ADR-004 — The idempotency key excludes the attempt number

**Decision.** `mission_id + task_id + action`. Deliberately **without**
`attempt`.

**Rationale.** If the attempt entered the key, a retry after interruption would
produce a new key and therefore a second purchase — the "why a resumable agent
might order two laptops" trap.

**Verification.** `test_idempotency_prevents_double_purchase`, plus the hero
scenario's final assertion: exactly one `PO-` on the enterprise side.

---

## ADR-005 — Three agent modes, one with no model at all

**Decision.** `deterministic` runs the business logic with zero Gemini calls,
but **always through the Gateway**.

**Rationale.** The demo must be replayable ten times out of ten in front of
judges. An exhausted quota or a flaky network must not break the governance
demonstration, which is the heart of the product.

---

## ADR-006 — Dual persistence and dual event bus

**Decision.** `InMemoryStore` / `FirestoreStore` and `inproc` / `pubsub`,
selected by configuration behind a single interface.

**Rationale.** The same code runs in tests (one second, zero dependencies) and
on Cloud Run. `EventService.dispatch()` is the common entry point for the local
worker and the Pub/Sub push.

---

## ADR-007 — The autonomy boundary is a product feature, not public data

**Decision.** `GET /api/v1/policy` exposes autonomous capabilities, those
requiring approval, those blocked, and the thresholds — **to the authenticated
operator**.

**Rationale.** An enterprise buyer must be able to answer "what can this agent
do without me?" without reading the code. A hidden rule is not a guarantee.

**Later correction.** The route lived in the unprotected `health` router — by
convenience, not by decision. On a public Cloud Run URL it revealed that
"purchase ≤ 5 000 $ is autonomous": exactly what you need to size an action
that stays under the threshold. It is now protected like the rest of
`/api/v1`. In the same move, `/healthz` — which must stay open to Cloud Run
probes — no longer details the configuration in cloud mode, and carries a
stable `service` field for identification.

---

## ADR-008 — The task claim is atomic, not optimistic

**Context.** Pub/Sub guarantees *at least once* delivery. Two concurrent pushes
of the same event both read the same `PENDING` task.

**Observed symptom.** With the in-memory store, no duplicates — objects are
shared, so one coroutine's mutation is instantly visible to the others. With
Firestore semantics (network latency plus deserialisation into fresh objects),
the same task ran **three times**.

**Decision.** `Store.claim_task()`: atomic `PENDING → RUNNING` transition, under
a lock in memory and inside a transaction in Firestore. The Mission Engine
claims the task before any execution; a failed claim is a non-event, not an
error.

**Testing lesson.** A concurrency test written against the in-memory store
validates a property production does not have.
`tests/integration/test_concurrency.py` therefore reproduces Firestore
semantics explicitly.

---

## ADR-009 — An agent that cannot start is a mission failure

**Context.** `require_executable()` raises `AgentUnavailable` for a suspended
agent. That exception propagated up to the event handler, where it was
swallowed: mission frozen at 50 %, task locked in `RUNNING` forever, no trace,
no recovery.

**Decision.** The Mission Engine catches any `ACCError` around agent launch and
routes it to `_on_task_failure` as class `AUTHORIZATION` — which triggers a safe
hold with human escalation.

**Testing lesson.** The initial assertion (`status != COMPLETED`) was satisfied
by a frozen mission. A safe-hold test must require an observable transition, a
released task and a traced escalation.

---

## ADR-010 — Mission risk is a high-water mark

**Context.** The Risk Agent rates the fallback supplier `MEDIUM`. That value
overwrote the mission risk raised to `HIGH` by the outage: a disrupted mission
silently dropped back, disabling alerts.

**Decision.** Supplier risk and mission risk are two different things. The
former goes into `context.extra`; the latter only ever rises until the mission
resolves.

---

## ADR-011 — One source of truth for configuration

**Context.** Route dependencies (`require_api_key`, `require_demo_mode`) read
`get_settings()` — cached global environment — while every service read the
container's settings. The application had **two sources of configuration**.

**Symptom.** On a machine with no `.env`, the suite passed. On a machine with
`ACC_API_KEY` in `.env`, four API tests failed with 401. The same commit gave
two results depending on the workstation.

**Decision.** Routes read `c.settings`, like everything else. Key comparison
uses `secrets.compare_digest` (constant time).

**Trap in the fix.** Simply making the tests pass could have disabled
authentication unnoticed. Four regression tests lock the behaviour: missing key
→ 401, wrong key → 401, right key → 200, `/healthz` stays open to probes.

---

## ADR-012 — Tests are hermetic against `.env`

**Context.** Even after ADR-011, `Settings(**overrides)` still read `.env` for
any field not overridden. A `.env` containing
`POLICY_PURCHASE_AUTONOMOUS_MAX=100000` broke 11 scenario tests: the autonomy
threshold under test was no longer the product's.

**Decision.** `make_settings()` builds `Settings(_env_file=None, …)`, and every
test goes through that helper. `scripts/run_hero_scenario.py` does the same: the
demo must unfold identically on any workstation.

**Verification.** The suite passes in three conditions: no `.env`, a realistic
`.env`, and a deliberately hostile one.

---

## ADR-013 — CORS: wildcards do not exist in `allow_origins`

**Context.** The cloud configuration listed `"https://acc-web-*.run.app"`.
Starlette never treats that string as a pattern: it is compared for **strict
equality**. The deployed frontend would have been entirely blocked by CORS.

**Why it stayed invisible.** Locally, `allow_origins=["*"]` masks the problem.
And `curl` ignores CORS: the backend answered perfectly from the command line
while being unreachable from a browser.

**Decision.** Exact origins go through `ACC_CORS_ORIGINS`; Cloud Run URLs —
whose subdomain is generated at deploy time — go through `allow_origin_regex`.
The regex covers both formats in circulation.

**Locked.** Tests verify that a foreign origin, a malicious suffix
(`...run.app.evil.com`) and an unencrypted `http://` are all rejected.

---

## ADR-014 — Auto-instrumentation is probed, not assumed

**Context.** FastAPI ≥ 0.141 wraps included routers in `_IncludedRouter` objects
with no `.path` attribute. Older versions of
`opentelemetry-instrumentation-fastapi` assume it and raise `AttributeError`
**on every request**: the API becomes unusable.

**Missed signal.** During an earlier inspection, `app.routes` showed only 5
entries instead of the expected 35. I concluded "FastAPI wraps routers" and
moved on. Those wrapper objects were exactly the cause of the crash.

**Decision.** At startup, ACC calls the actually installed `_get_route_details`
with a synthetic scope. If it raises, HTTP instrumentation is disabled with an
explicit message; mission tracing — which carries the product value — stays on.

**Why not a version pin.** A bound in `requirements.txt` protects a fresh
install, not an existing environment. The probe tests what is actually loaded.

---

## ADR-015 — Dev tooling depends on no shell

**Context.** The Makefile used `VAR=value command` to pass
`ACC_ENTERPRISE_BASE_URL`. That is POSIX syntax. On Windows, make delegates to
`cmd.exe`, which answers: "'ACC_ENTERPRISE_BASE_URL' is not recognized". `make
run` and `make web` were unusable.

**Decision.** Every target goes through `scripts/dev.py`. Python is already
required by the project and behaves identically on all three systems:
`sys.executable` respects the active venv, `shutil.which` resolves `npm.cmd`.

**Locked.** `tests/unit/test_dev_tooling.py` inspects the Makefile and rejects
any variable prefix, line continuation or direct npm call.

**A test mistake worth recording.** The first guard also rejected `&&`. That was
wrong: `cmd.exe` supports it. An inaccurate test pushes you to work around the
rule rather than fix a real defect — it was corrected, not disabled.

---

## ADR-016 — One source of truth for the API key

**Context.** `ACC_API_KEY` (backend, `.env`) and `NEXT_PUBLIC_ACC_API_KEY`
(frontend, `apps/web/.env.local`) had to be kept in sync by hand. Any divergence
produced a 401 on **every** route, with no clue: the backend answered, the
frontend was rejected.

**Decision.** `scripts/dev.py` reads the key as the backend sees it and
propagates it to the npm process. An explicitly provided value is never
overwritten.

**Defence in depth.** Startup logs `api_key_enforced` with the remedy, and
`make doctor` turns the 401 into a concrete instruction — once, not once per
route.

**What was NOT done.** Disabling authentication locally to "simplify". A
configured key must be enforced: four regression tests lock that.

---

## ADR-017 — Configuration must say where it comes from

**Context.** A user saw `#ACC_API_KEY=` commented out in their `.env` and still
got a 401 on every route. Cause: an environment variable forgotten in the shell,
which takes precedence over the file. The message "invalid or missing API key"
was accurate and completely useless.

**Decision.** `api_key_source()` distinguishes "environment", ".env" and "none".
Startup and `make doctor` name the source and give the removal command for
PowerShell, cmd and bash.

**General rule.** When a value can come from several places with a precedence
order, a diagnostic reporting the effect without the origin forces guesswork.

**Side effect fixed.** A whitespace-only value protected the API with an
irreproducible key. Secrets are now normalised: `"   "` means absent.

---

## ADR-018 — A mission always has a lever or an explicit end

**Context observed in use.** The enterprise systems were unreachable. The
Failure Twin chose ESCALATE, the operator approved — and the mission stayed
frozen in `WAITING_APPROVAL` with `pending_approval_id = None`: approval
consumed, recovery `COMPLETED`, no action possible.

**Cause.** `apply_after_approval` replayed the strategy as-is. ESCALATE means
"ask a human"; replaying it AFTER the human decided put the mission back to
waiting for an approval that no longer existed.

**Three fixes, local to structural:**

1. An approved escalation is **resolved**, not replayed: it yields
   `RETRY_TASK`. The human authorised continuation.
2. `_apply_directive` now refuses to enter `WAITING_APPROVAL` without an
   `approval_id`. That state cannot be unblocked, so failing explicitly is
   better. **This guard makes the whole class of defect impossible**, not just
   this instance.
3. An attempt budget bounds the loop: past `max_attempts` the mission fails with
   `stage="recovery_exhausted"` and a readable message.

**Verification.** A permanently dead dependency converges in 3 cycles to
`FAILED / recovery_exhausted`. Tests reject any non-terminal state with no
pending approval.

**What this says about the product.** A silently frozen mission is worse than a
failed one: the operator believes it is progressing. "The mission survives"
cannot mean "the mission never ends".

---

## ADR-019 — A diagnostic that wrongly reassures is harmful

**Context.** `make doctor` reported "no blocking problem detected" while the
enterprise systems were down — the exact reason missions were failing. The
missing mock was classed as a mere warning.

**Decision.** Severity is contextual: if the control plane is running, missing
enterprise systems are **blocking**, because no mission can complete. The exit
code follows (1 on a blocking problem), which makes the diagnostic usable in CI.

**Technical corollary.** `subprocess.run(..., text=True)` decoded netstat output
with the locale: on Windows, cp1252 fails on unmapped bytes and the diagnostic
crashed before diagnosing anything. Decoding is now explicit and tolerant.

---

## ADR-020 — An action with no visible effect is perceived as a bug

**Context.** A user reported that "New mission just redisplays the page". The
logs proved otherwise: four missions created, four purchase orders issued. The
code was correct.

**The real defect.** A nominal mission completes in ~15 ms. The new one was
therefore visually identical to the previous one — same objective, same
supplier, same amount, COMPLETED 100 %. Only the id changed, in small grey text.
And the UI offered no way to see the four existing missions, although
`GET /missions` was already exposed.

**Fixes.** Mission switcher; explicit creation acknowledgement that also says a
failure must be injected to see anything; and clearing previous state on mission
change — a real defect: the previous mission's data stayed on screen during the
reload.

**Lesson.** A bug report can be accurate in its observation and wrong in its
diagnosis. "The button does nothing" was false; "I cannot see what the button
does" was true.

---

## ADR-021 — Indistinguishable missions prove nothing

**Context.** "You cannot tell missions apart by their details." Correct: the
frontend called `createMission()` with no arguments, although the API already
accepted objective, volume, deadline and priority. Every mission was a clone,
and the list showed only an id and a timestamp.

**What the fix revealed.** Making volume configurable produces three distinct
narratives **with no failure injected at all**:

- 1 200 u → 4 800 $: below the autonomous threshold, the mission completes alone
- 1 500 u → 6 000 $: above it, human authority becomes necessary
- 2 000 u: SUP-A capacity exceeded, the Failure Twin takes over

The authority boundary can therefore be demonstrated by a simple volume change.
That lever existed in the engine from day one; the UI made it unreachable.

**Lesson.** A capability that is not exposed does not exist for the user.

---

## ADR-022 — Absence of data is not a perfect score

**Context.** The dashboard showed "Mission continuity 100 %" next to a FAILED
mission. The percentage helper returned 100 on a zero denominator:

```python
return round(num / den * 100, 1) if den else 100.0   # wrong
```

No mission had been *disrupted*, so the continuity rate had no sample — and the
system presented it as a clean sweep.

**Why it matters here.** Mission continuity is the product's north star metric.
A judge asking "why 100 % when a mission failed?" would have received no
defensible answer. A metric that flatters by construction measures nothing.

**Decision.** `pct()` returns `None` on a zero denominator. The UI shows "n/a"
and states the sample size. A second indicator — mission success rate — covers
the case where no disruption occurred.

---

## ADR-023 — The UI must not extend a finished activity

**Context.** On a FAILED mission, the fleet panel still showed "Procurement
Agent: BUSY". `active_agent_id` keeps the last agent invoked; the UI inferred an
ongoing execution.

**Decision.** A terminal status (COMPLETED, FAILED, ABORTED) neutralises the
"busy" display: no agent works on a closed mission.

**General rule.** On a control plane, an activity indicator that outlives the
activity is worse than no indicator: it makes you wait for an event that will
never come.

---

## ADR-024 — Idempotency protects ACTIONS, never OBSERVATIONS

**Context.** The idempotency key was applied to every capability, reads
included. Usage logs showed, on each retry:

```
idempotent_replay  MIS-1002-TASK-5-supplier.status
audit  supplier.status  result=REPLAYED
```

**Consequence, reproduced in test.** An operator fixes the real world — supplier
capacity goes from 1500 to 3000 — then approves the retry. The agent replays the
cached answer saying 1500 and fails again. The mission can NEVER complete, no
matter how many approvals.

That directly contradicts the product promise: a retry exists precisely to
**re-observe the world**.

**Decision.** `CONSEQUENTIAL_CAPABILITIES` limits idempotency to actions that
mutate the enterprise — today `purchase.execute`. Reads still traverse the
Gateway (identity, capability, policy, audit) but are never served from a cache.

**What must not break.** Double-purchase protection. A dedicated test verifies
that a repeated `purchase.execute` still produces a single purchase order.

**General rule.** Idempotency answers "has this action already been executed?",
not "is this information already known?". Confusing the two turns a safety
mechanism into a source of blindness.

---

## ADR-025 — A decision modal must reset on every request

**Context.** After clicking "Approve", the screen froze. Cause: `busy` was reset
only in the error branch. On success it stayed set — buttons disabled, permanent
"…".

**Why tests missed it.** The modal normally unmounts after a decision. But one
decision often creates another: an approved escalation produces a new request.
The modal stayed mounted with the previous decision's state, and the operator
lost every means to act.

**Decision.** Reset in a `finally`, plus a full reset (state, comment, error) on
every `approval_id` change.

---

## ADR-026 — Do not re-ask the same question when nothing changed

**Context observed in use.** An operator approved **three identical
escalations** before the mission failed. Each time: same diagnosis ("capacity
1500/1501"), same plan, same approval request. The world had not moved between
attempts, so every retry was doomed identically.

**Cause.** The Failure Twin received the list of previous recoveries but **not
their diagnosis**. It could not observe that the state was unchanged, and
proposed the same plan indefinitely.

**Decision.**

1. Recovery context now carries the diagnosis, the failed component and whether
   the attempt was approved.
2. If the diagnosis matches an **already approved** escalation, the Failure Twin
   selects `ABORT` with an explicit reason: nothing changed, a new attempt would
   fail identically.
3. A repeated approval request now carries its rank in its evidence ("attempt 2
   on this mission"): without it, the second request is indistinguishable from
   the first.

**What must not break.** The legitimate case: an operator who ACTUALLY fixes the
environment before approving. A test verifies that capacity raised from 1500 to
3000 still lets the mission complete — the abort only fires on a strictly
unchanged state.

**Named terminal stages.** `situation_unchanged`, `recovery_exhausted`,
`recovery_failed`, `safe_hold`: a mute "failed" teaches the operator nothing
about what to fix.

**Lesson.** A system that endlessly re-asks the same authorisation creates the
illusion of progress. Knowing how to say "I can do nothing more, and here is
why" is part of resilience, just as much as recovering.

---

## ADR-027 — You authorise an action, not an abstention

**Context observed in use.** The Failure Twin decides `ABORT` (unchanged
situation, nothing can be attempted). The plan went through `recovery.apply`
with CRITICAL impact, hence `APPROVAL_REQUIRED`. The operator saw an "Action
requiring approval" modal and clicked "Approve" — **with no way to tell they
were authorising the end of their mission**.

**Two defects in one.**

1. Logic: ACC requires authorisation to act. An abort executes no enterprise
   action; demanding authority to abstain is backwards.
2. Interface: the "Approve" label here meant "abandon". A button whose effect
   contradicts its label is a trap.

**Decision.** Dedicated `recovery.abort` capability, rule `RECOVERY-032` →
ALLOW. The decision is still **evaluated and traced** by the Policy Engine:
governance is intact, only the superfluous authorisation disappears.
`recovery.apply` still requires human authority on high-risk plans — a test
locks that explicitly, since it was the risk of this fix.

**Distinct status.** `RecoveryStatus.ABORTED` replaces `FAILED` for a deliberate
abort. The recovery worked; the situation is the dead end. Showing "FAILED" on a
correct decision would make the Failure Twin look broken in the trace and
degrade the recovery success rate.

---

## ADR-028 — Reporting a failure is not being in failure

**Context observed in use.** On every supplier outage, the logs showed:

```
agent_status_changed  supply-agent  BUSY
agent_status_changed  supply-agent  DEGRADED
agent_status_changed  supply-agent  AVAILABLE
```

The Supply Agent was marked DEGRADED although it had **done its job perfectly**:
detect and report that the supplier could not deliver.

**Why this is serious.** It is the exact inverse of the product thesis. ACC
exists to separate "the agent failed" from "the mission failed". Here a
DEPENDENCY failure was charged to the AGENT. In fleet health, a supplier down
for a week would have shown the whole fleet as degraded, and the operator would
have inspected the agents instead of the dependency.

**Decision.** `_indicts_the_agent()` explicitly exonerates classes that say
nothing about agent health: `DEPENDENCY`, `PERMANENT`, `AUTHORIZATION`,
`SECURITY`. Only `AGENT`, `TIMEOUT`, `TRANSIENT` and `UNKNOWN` degrade. A
parametrised test covers all eight classes.

---

## ADR-029 — Handing off is not recovering

**Context.** The successful-recovery counter included escalations. A failed
mission could therefore display "Recovery 1/2": ACC had "succeeded" at a
recovery that consisted of asking for help.

**Decision.** `recovery_success` excludes `ESCALATE` and `ABORT`. An escalation
is a transfer of authority; an abort is an observation. Neither restores the
mission, and counting them would inflate the rate with exactly the cases where
ACC declined to act alone.

---

## ADR-030 — A finished mission leaves nothing "in progress"

**Context observed in use.** After a rejected approval, the trace showed
"Failure Twin — IN_PROGRESS" on a FAILED mission, and the metrics bar showed
"Recovery time —" although a recovery had taken place.

**Cause.** The rejection went straight to `_fail()`. The recovery waiting on
that decision was never closed: `status` stayed `IN_PROGRESS` and `completed_at`
stayed `None`, making the duration incomputable. `pending_approval_id` still
pointed at an already decided request.

**Decision.** `_close_pending_recovery()` closes the associated recovery
(`HELD`, timestamp, reason enriched with the human decision) and frees
`pending_approval_id`. The same treatment applies on expiry.

**Invariant locked by test.** On a terminal mission: no task in `RUNNING`, no
recovery in `IN_PROGRESS`, no pending approval, no residual
`pending_approval_id`.

---

## ADR-031 — Never record an audit event that did not happen

**Context.** The "Kill the runtime" control returned `200 OK` on an **already
finished** mission and published `runtime.interrupted` in its timeline. The
"Resume" control returned `409` — an error shown mid-demo.

**The first defect is the serious one.** ACC sells an audit trail that lets you
reconstruct what actually happened. Recording a runtime interruption that
occurred after the mission ended means recording a fiction. **A trace containing
invented facts proves nothing.**

**Decision.** `interrupt()` refuses a terminal mission, as `resume()` already
did. In the UI both buttons are disabled on a closed mission, with a "nothing
left to interrupt or resume" note — rather than an active button leading to an
error.

**What must not break.** The resume demonstration itself: a test verifies that a
live mission stays interruptible, that the event is published, and that resume
restores the pending approval.

---

## ADR-032 — A demo script is code, not prose

**Context.** The demo script had been written early, then a dozen fixes changed
the product's behaviour. Re-reading did not reveal it: you had to execute what
it prescribes.

**Three false claims, found by execution:**

1. **The choreography was impossible.** The script had you click "Fail SUP-A" at
   0:50, after launch. But a nominal mission completes in **0.3 seconds**: a
   failure injected afterwards has no effect. The demo as written would have
   shown nothing.
2. **"The three struck through in red"** — there are five options and **two**
   not permitted.
3. **"Click Hostile injection before approving"** — by then the supplier reads
   are done: **zero threats detected**. The script promised a moment that would
   not have happened.

**Decision.** The script is rewritten on verified facts, and its claims are
converted into tests: option counts, amounts, thresholds, UI labels, arming
order, variant behaviour. Quoted prices are compared to the actual state of the
simulated systems; the quoted threshold to the one the Policy Engine applies.

**Effect.** The script can no longer drift silently. Changing SUP-C's price or
renaming an indicator fails CI — instead of failing in front of the judges.

**Inverse test.** `test_injection_armed_mid_flight_produces_nothing` fails if the
late injection starts working: the message then asks to update the script, which
documents it as ineffective. A documented trap must stay a trap, or the
documentation lies the other way.

---

## ADR-033 — A checkpoint label is an assertion, not a tag

**Context.** On a nominal mission with **no failure at all**, the checkpoint list
showed:

```
CP-3   Supply analysis complete   <- it was the risk assessment
CP-4   Recovery plan selected     <- it was a PURCHASE plan
```

The `CHECKPOINT_AFTER_TASK` mapping had been copied from the blueprint example,
written for the hero scenario, and never revisited for the nominal path.

**Why it matters.** The operator reconstructs the mission from this list — that
is the checkpoint's purpose. A judge inspecting a successful mission would have
read "Recovery plan selected" and asked which recovery took place. There was
none.

This is the same fault as the `runtime.interrupted` event published on a finished
mission (ADR-031): **the audit trail asserted something false.**

**Decision.** Each task type produces a stage that describes it:
`risk_assessment`, `procurement_planned`, `awaiting_approval`. Waiting on a
PURCHASE approval is distinguished from waiting on a RECOVERY approval
(`recovery_awaiting_approval`).

**Locked.** A test compares the full label list of a nominal mission, and
rejects any mention of "recovery" when no recovery was recorded. Another
verifies no stage displays its raw technical key for lack of a label.

---

## ADR-034 — A setting that does nothing is worse than none

**Context.** `GEMINI_MODEL_REASONING=gemini-2.5-pro` appeared in `.env.example`
and in `Settings` from the start. It was **read nowhere**: all four agents ran
on the same Flash model.

**Two problems.**

1. The setting gave the illusion of a control that did not exist. Anyone trying
   to strengthen the Failure Twin would have changed the value and observed no
   effect.
2. Its default announced a "Pro" model — roughly 4× more expensive on input and
   output. A reader budgeting on that basis would have been off by an order of
   magnitude.

**Decision.** The setting is wired: the Failure Twin — which carries the hardest
reasoning — can run on a distinct model. Its default becomes **empty**, with an
explicit fallback to the standard model: the lever exists, and enabling it is a
conscious choice.

**Locked.** `test_reasoning_model_is_actually_wired` fails if the setting becomes
decorative again; `test_no_agent_uses_a_pro_model_by_default` fails if an
expensive model returns as a default.

---

## ADR-035 — Cost guardrails are tested, not documented

**Context.** With a fixed credit budget, the risk is not the demo cost —
measured at **~0.07 $ per mission** (7 model calls of ~700 input tokens, at
verified Vertex prices). The risk is forgotten resources and expensive defaults.

**Decision.** The properties that protect the budget are verified by CI, not
only written in a guide:

- no `min_instance_count > 0` (billing while idle)
- no service without an instance ceiling
- no hourly-billing resource (GKE, Cloud SQL, deployed Vertex endpoint)
- no "Pro" model by default
- bounded model call timeout, bounded attempt budget
- cost labels present, without which the invoice cannot be broken down

**Rationale.** A documented guardrail is lost at the first refactor. Adding a
`google_container_cluster` to the Terraform now fails CI, with the reason: that
resource type bills continuously.

---

## ADR-036 — Model choice follows the thesis, not raw power

**Context.** The default was `gemini-2.5-flash`. Two verified problems: the 2.5
models retire on **16 October 2026**, and the choice had never been reasoned —
it was the value written on day one.

**Measured cost per hero mission** (7 calls, ~700 input tokens, ~350 visible
output tokens), extrapolated to 1 000 missions:

| Model | 1 000 missions | Compliant |
|---|---|---|
| `gemini-3.6-flash` | ~68 $ | ✅ |
| `gemini-3.5-flash` | ~162 $ | ✅ |
| `gemini-3.1-flash-lite` | ~12 $ | ❌ below 3.5 |
| `gemini-3.1-pro` | ~245 $ | ❌ below 3.5 |

The gap comes from **thinking tokens** in 3.x models, billed as output.

**Decision: `gemini-3.6-flash`.**

An earlier revision chose `gemini-3.1-flash-lite` purely on cost. That was a
**disqualifying error**: the contest mandates "Gemini 3.5 or newer", and Stage
One is a pass/fail on requirements. Compliance overrides cost optimisation.
3.6 Flash is newer than 3.5 *and* cheaper, thanks to introductory pricing.

The remaining argument is not price but coherence: **ACC does not ask the model
to decide**. Policy, idempotency, authority and traceability live in the
platform; the model produces a structured finding that goes back through the
Mission Engine. A frontier model would add nothing to this architecture — and
that is precisely what the product claims. Choosing a light model is a
**demonstration of the thesis**, not a cost concession.

**Locked.** A test rejects any configuration pointing at a model below 3.5 or
with an announced retirement, and verifies no sampling parameter is hardwired —
those have been deprecated since 21 July 2026 and are the usual blocker when
switching models.

---

## ADR-037 — A test double that imports what it replaces doubles nothing

**Context.** Five ADK-path tests failed on a machine where the Google SDK was not
installed, with "ADK runtime unavailable" and an empty `runner.calls` — the fake
Runner was never reached.

**Cause.** `ACCAgent._invoke_runner` builds its message with
`from google.genai import types`. The double replaced the Runner and the
session, but **not that import**: without the SDK, the exception was caught by
the general guard, the agent fell back to failure, and the double isolated
nothing.

**Why I had not seen it.** The SDK was installed in my environment. The tests
passed — for the wrong reason. They did not validate what they claimed to
validate as soon as the SDK was missing.

**Decision.** The double now provides the `google.genai.types` surface itself
when it is absent. These tests are about OUR wrapper — prompt rendering,
sanitisation, parsing, timeout, fallback — and none of that belongs to the ADK.

**Durable protection.** A CI job runs the full suite **without** `google-adk` or
`google-genai`, on the lowest supported Python version. Fixing the symptom would
have prevented nothing: it was the absence of exercise that let the dependency
settle in.

**General rule.** A test that can only fail on certain machines is not a test,
it is a coincidence.
