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
| 038 | Deployment must not require a shell the user does not have | **User's machine** |
| 039 | Check credentials before spending money, not after | **User's machine** |
| 040 | An error message can name the wrong cause | **First real deployment** |
| 041 | Report every prerequisite at once, not one per attempt | **First real deployment** |
| 042 | A tool must satisfy its own ordering constraints | **First real deployment** |
| 043 | A manual prerequisite is a prerequisite that gets skipped | **First real deployment** |
| 044 | A protection nobody can remove is a permanent bill | **First real deployment** |
| 045 | A build-time value cannot describe a runtime address | **First real deployment** |
| 046 | A local timeout is not a cold-start timeout | **First deployed diagnostic** |
| 047 | A verdict must weigh the evidence | **First deployed diagnostic** |
| 048 | An empty string is not a missing value | **Deployed Mission Control** |
| 049 | `:latest` is invisible to a diff | **First successful deployment** |
| 050 | A setting the container never receives is not a setting | **Deployed frontend** |
| 051 | A test that rebuilds the wiring tests its own copy | **Deployed frontend** |
| 052 | A probe cannot vouch for a version it never runs | **Cloud Run logs** |
| 053 | Accent-free French defeats an accent check | **Deployed 401 body** |
| 054 | A key inside a public bundle is not a secret | **Deployed 401** |
| 055 | Pub/Sub push cannot send a custom header | **Frozen mission** |
| 056 | EventSource cannot send a header either | **Silent polling** |
| 057 | Two Cloud Run services are not on the same network | **HTTP 404 on every tool** |
| 058 | A capability the registry does not declare is a runtime denial | **CAPABILITY_DENIED in hybrid** |
| 059 | A reset that resets nothing is worse than no reset | **Stale approval on open** |
| 060 | Fixing one client leaves the other one broken | **500 on every demo control** |
| 061 | An action is identified by what it does, not by who attempts it | **Two purchase orders** |
| 062 | A registry no deployment can update is the wrong kind of durable | **Stale CAPABILITY_DENIED** |
| 063 | A Reset button that removes the Reset button | **Deployed empty state** |
| 064 | Do not hand a model a precedence rule to apply | **Three recoveries, same supplier** |
| 065 | An interface must not assert what it does not know | **Operator question** |
| 066 | Mutating the caller's object is not persisting | **Recovery loop in deterministic** |
| 067 | A detector that cries wolf gets disabled | **False positive on \"injected\"** |
| 068 | A decision window with no exit forces a decision | **Operator question** |
| 069 | A breaker must protect, not imprison | **Reset blocked by its own repair** |

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


---

## ADR-038 — Deployment must not require a shell the user does not have

**Context.** The operator runs PowerShell on Windows. The deployment guide
opened with `export PROJECT_ID=...`, which PowerShell answers with "the term
'export' is not recognized". Every deployment script — `deploy.sh`,
`costs.sh`, `teardown.sh` — was bash-only.

**The worse defect, found while porting.** `deploy.sh` built two images and
never built Mission Control, then called `terraform apply` **without**
`image_web`. That variable is declared with no default: the very first
deployment would have stalled on an interactive prompt, or failed outright.
Nobody had ever run the script, so nobody had seen it.

**A second portability defect in the same file.** The build config was piped
through `--config=/dev/stdin`. That path does not exist on Windows and behaves
erratically under Git Bash because of path translation. The Python version
writes a real temporary file — more portable *and* more robust.

**Decision.** `deploy.py`, `costs.py` and `teardown.py` replace the three shell
scripts, following the pattern that already fixed the Makefile (ADR-015).
`make deploy`, `make plan`, `make costs` and `make teardown` run natively in
PowerShell. The guide gives PowerShell and bash side by side, and every script
also accepts `--project-id` so no environment variable is required at all.

**Locked.** Tests verify that no bash-only deployment script remains, that
`deploy.py` builds **every** image Terraform declares, that each referenced
Dockerfile exists, and that no POSIX-only path appears in executable code. The
last test was checked by deliberately reintroducing `/dev/stdin`: it fails.

**Lesson.** A script nobody has run is not tooling, it is a hypothesis. Two
independent blockers were sitting in forty lines that had never been executed.


---

## ADR-039 — Check credentials before spending money, not after

**Context.** Running `gcloud config set project`, the operator saw:

```
WARNING: Your active project does not match the quota project in your local
Application Default Credentials file.
```

Investigating it exposed a gap in the deployment guide: it only ran
`gcloud auth login`. That authenticates the **CLI**. The Terraform Google
provider and the Vertex AI SDK both read **Application Default Credentials**, a
separate file created by `gcloud auth application-default login`.

**Why this was going to hurt.** Without ADC, `terraform apply` fails — but only
*after* Cloud Build has built and pushed three images. That is the most
expensive possible moment to discover a missing credential: time spent, build
minutes billed, and a failure that looks like an infrastructure problem rather
than an authentication one.

The quota project mismatch is subtler still: it does **not** block Terraform.
It produces `403 PERMISSION_DENIED` on Vertex AI — during the demo, after
everything looked fine.

**Decision.** `deploy.py` runs a preflight before touching anything expensive:
ADC present, quota project matching. A mismatch stops the deployment with the
exact command to fix it. Both cases were verified by simulating the gcloud CLI.

**Locked.** A test asserts that the preflight call appears **before** the image
build loop in the source. Ordering is the whole point: a check that runs after
the cost has been paid is not a check.

**Lesson.** Every warning on a never-executed path is worth investigating. This
one was purely informational, and it revealed a missing prerequisite that would
have stopped the first deployment.


---

## ADR-040 — An error message can name the wrong cause

**Context.** The first real `make deploy` failed on:

```
PERMISSION_DENIED: Permission 'iam.serviceAccounts.get' denied on resource
(or it may not exist)
```

That reads as a permissions problem. The operator was the project Owner, so it
looked like an IAM policy issue — a long and fruitless investigation.

**Actual cause.** Cloud Build changed its default build identity. On projects
where the API is enabled after that change, builds run as the **Compute Engine
default service account**. That account is created only when
`compute.googleapis.com` is enabled — and ACC's API list did not include it,
because ACC runs no virtual machine.

The parenthesis in the message — *"or it may not exist"* — was the real signal,
and the easiest part to skip past.

**Decision.** `compute.googleapis.com` joins the enablement list, with a
comment explaining why a project with no VM needs the Compute API. More
importantly, `deploy.py` verifies **before any build** that the API is enabled
and that the build service account actually exists, and names the fix.

**Verification.** The three outcomes were checked against a simulated gcloud
CLI: API missing, API enabled but service account not yet created, everything
in place.

**Lesson.** A cloud error names the permission that was checked, not the reason
the check failed. When the account is Owner and the message still says
"denied", the resource probably does not exist.


---

## ADR-041 — Report every prerequisite at once, not one per attempt

**Context.** The first deployment produced a chain of failures, each visible
only once the previous one was fixed:

1. `export` is not a PowerShell command
2. No Application Default Credentials (the CLI login does not create them)
3. `compute.googleapis.com` disabled -> the build identity does not exist
4. That identity holds **no role** -> it cannot read the uploaded source

Four round trips. Each one required a full `make deploy`, an upload, and a
failure — with build minutes billed on the way.

**Root cause of the pattern.** Google reports the first blocking condition it
meets. Nothing is wrong with that, but a deployment tool can do better: it
knows every prerequisite in advance.

**Decision.** `deploy.py` collects **all** the problems it can see before
failing, and prints the exact fix for each. The credentials check, the API
check, the service-account-existence check and the role check all run before a
single image is built.

**A bug in the check itself, worth recording.** The role check first read
`if roles and not (roles & sufficient)`. An **empty** set is precisely the
failing case — recent projects grant no role at all to default service
accounts — and that condition silently let it through. Fixed by distinguishing
"the command failed" from "the command succeeded and returned nothing". A test
locks the distinction.

**Two IAM gaps found by the same audit**, neither of which had ever been
exercised:

- The Pub/Sub **service agent** lacked `roles/iam.serviceAccountTokenCreator`
  on the push invoker. The subscription would have been created, and every push
  silently rejected — missions frozen in CREATED with no application error.
- The Mission Control service account could not write logs: a service that
  cannot log is invisible exactly when it fails.

**Follow-up.** Reporting every problem at once still left the operator running
`gcloud services enable` by hand between attempts. `--enable-apis` now enables
what is missing, waits 90 s for the service accounts to be provisioned — that
delay is the point, since retrying immediately fails on a different message —
then re-runs the whole check.

**Lesson.** A prerequisite chain discovered one link at a time is a tool that
knows less than it could. Everything checkable before spending money should be
checked before spending money, and everything fixable without risk should be
offered as a fix rather than as an instruction.


---

## ADR-042 — A tool must satisfy its own ordering constraints

**Context.** After four prerequisite fixes, the images finally built — and the
push failed:

```
name unknown: Repository "acc" not found
ERROR: failed to push because we ran out of retries.
```

**Cause, entirely internal.** Terraform owns the Artifact Registry repository.
`deploy.py` built and pushed the images **before** running `terraform apply`.
The repository therefore did not exist at push time. Cloud Build retried ten
times, billing a full build each round, then gave up.

**Same class as the missing `image_web` (ADR-038):** an ordering constraint the
tool itself violated, invisible because nobody had ever run it end to end.

**Decision.** A targeted `terraform apply
-target=google_artifact_registry_repository.acc` creates the repository before
any build. Terraform stays the single source of truth — the later full apply is
a no-op for that resource, so nothing is created outside its control.

**Locked.** A test asserts that `ensure_registry` is called before
`build_image`, and that the targeted apply supplies **every** variable Terraform
declares without a default — a missing one would turn an automated apply into
an interactive prompt. Verified by deleting the call: the test fails.

**Lesson.** Terraform can only guarantee ordering for what it manages. As soon
as a step happens outside the graph — a build, a push — the ordering becomes the
script's responsibility, and nothing checks it but a real run.


---

## ADR-043 — A manual prerequisite is a prerequisite that gets skipped

**Context.** All three images built and pushed, Terraform ran, and Cloud Run
refused every revision:

```
Secret projects/.../secrets/acc-api-key/versions/latest was not found
Secret projects/.../secrets/acc-pubsub-push-token/versions/latest was not found
```

**Cause.** Terraform created the secret **containers** and no **version**. A
secret with no version has no `latest`. The values were documented as a manual
step — `openssl rand -hex 32 | gcloud secrets create ...` — in section 9 of the
guide.

Two reasons that step never happened: an operator working through a chain of
errors follows the errors, not the guide; and `openssl` is not available in a
default PowerShell.

**Decision.** Terraform generates both values with `random_password` and
creates the versions. The deployment becomes self-contained: no manual step, no
external tool, nothing to skip. Values never appear in the repository, in an
image, in a prompt, or in an output — `terraform output acc_api_key_command`
prints the command to read the key, not the key.

**A second, subtler ordering bug in the same fix.** Declaring the versions is
not sufficient. Cloud Run references the secret through `secret_id`, so
Terraform infers a dependency on the **secret**, never on its **version** — the
service could still be created first. An explicit `depends_on` on the versions
was required.

**And a bug I introduced while fixing it.** The insertion added a second
`depends_on` to a resource that already had one — an argument Terraform
rejects outright. A test now walks every resource block and refuses a duplicate.

**Lesson.** Every step a human must remember is a step that eventually gets
missed. If a tool can do it safely, the tool should do it.


---

## ADR-044 — A protection nobody can remove is a permanent bill

**Context.** After the secret fix, Terraform planned to replace the API service
left in a failed state, and stopped:

```
Error: cannot destroy service without setting deletion_protection=false
```

**Cause.** Provider v6 defaults `google_cloud_run_v2_service` to
`deletion_protection = true`. None of the three services set it.

**The wider consequence, which the error did not mention.** The same default
blocks `terraform destroy` — so `make teardown` could **never** have brought
billing back to zero. The script existed, was documented, and would have failed
on the first service. On a hackathon budget, a teardown that cannot run is the
one failure that keeps costing after everything else is over.

**Decision.** The three Cloud Run services set `deletion_protection = false`.
For a demo environment that is the right posture: a service must be replaceable
after a failed revision, and the infrastructure must be removable on demand.

**What stays protected, deliberately.** Firestore keeps
`DELETE_PROTECTION_ENABLED` — it holds mission state, and an accidental
`destroy` would erase it. `teardown.py` lifts that protection explicitly before
destroying, and a test asserts it does so **before** calling destroy, not after.

**Audit rather than a one-off fix.** The whole configuration was swept for
anything that could block a teardown: `prevent_destroy` (absent),
`disable_on_destroy` on API activation (already `false`, so a destroy does not
cascade into disabling APIs), and every other resource type. Four tests lock
the result.

**Follow-up — the deadlock the flag alone does not break.** Setting
`deletion_protection = false` is not enough once a service is already tainted
by a failed apply. Terraform plans to REPLACE it; the replacement is blocked by
the old protection; and the new flag can only take effect through the very
apply that the destroy is blocking. `--repair` untaints the service so the next
apply updates it in place, pushing a healthy revision instead of replacing a
broken one.

`terraform untaint` exits non-zero when nothing was tainted, which is a normal
outcome here — a test asserts the repair does not treat a clean resource as a
failure.

**And untainting alone is still not enough.** Once the secrets existed, the
apply stopped trying to destroy the service and updated it instead — only to
report the SAME dead revision, created before the secrets. A Cloud Run revision
that failed to start never retries; updating in place cannot escape it.
`--repair` therefore also detects a service whose `Ready` condition is not
`True`, deletes it and removes it from state, so the next apply recreates it
cleanly. Healthy services are left untouched, and an absent service is not
treated as broken.

**Lesson.** A protection is only defensible if something can lift it. Otherwise
it is not a safeguard, it is a leak that nobody can close. And a flag that
fixes a future apply does nothing for a state already stuck: recovery tooling
has to exist for the state you are actually in.


---

## ADR-045 — A build-time value cannot describe a runtime address

**Context.** The deployment finally succeeded:

```
acc_api_url  https://acc-api-jycspetv4a-ew.a.run.app
acc_web_url  https://acc-web-jycspetv4a-ew.a.run.app
```

Mission Control would nonetheless have called `http://127.0.0.1:8080` from the
judges' browsers.

**Cause.** `NEXT_PUBLIC_*` is inlined by Next.js **at build time**. Terraform
passed `NEXT_PUBLIC_ACC_API` as a Cloud Run runtime environment variable, which
has no effect: the value was already compiled into the bundle. And it could not
have been baked in either — the API URL does not exist until `terraform apply`
completes, long after the image is built.

The variable was set, in the right place, with the right value, and did
nothing.

**Decision, in two layers.**

1. **Runtime derivation.** Both services share the same Cloud Run URL suffix
   within a project and region, so the frontend derives the control plane from
   its own origin: `acc-web-…` becomes `acc-api-…`. This works on the very
   first deployment, with no rebuild.
2. **Explicit value on the next build.** `deploy.py` reads `acc_api_url` from
   the previous apply and passes it as a `--build-arg`. An explicit value
   always beats a derivation, and from the second deployment onward the
   derivation is never used.

**Verified, not assumed.** A test intercepts the generated Cloud Build config
and asserts the `--build-arg` really reaches the docker step — the message
printed by the script proves nothing about what is sent.

**And the CORS regex was checked against the real URL.** The deployed frontend
being blocked by CORS would have produced a blank page in front of the judges;
a test now pins both Cloud Run URL formats, and rejects a lookalike suffix.

**Lesson.** Configuration that is frozen at build time cannot describe anything
created after the build. Either the value is discovered at runtime, or the
build has to happen twice.


---

## ADR-046 — A local timeout is not a cold-start timeout

**Context.** Run against the deployed instance, the diagnostic reported two
blocking problems:

```
[FAIL] Cloud Run answered 404 with its own HTML page
[FAIL] /api/v1/policy -> 0   (the read operation timed out)
[OK]   /api/v1/agents -> 200
[OK]   /api/v1/metrics -> 200
[OK]   /api/v1/missions -> 200
```

Three routes out of four answered correctly. The service reported
`Ready=True`, and its startup probe targets `/healthz` — so `/healthz`
demonstrably worked inside the container.

**Cause.** The service scales to zero. The first request pays for the boot:
Cloud Run answers the caller itself until an instance is ready, and the client
gave up after 4 seconds — a figure chosen for a local uvicorn, not for a cold
container.

The diagnostic then declared "this is NOT ACC". The service was fine. It was
asleep.

**Decision.** Remote checks use a 25-second timeout and retry the first call up
to three times, saying so on screen. Only a service that still answers with
Cloud Run's own page after three attempts is reported as a real problem, and
the remedy then points at `status.url` and `status.conditions` rather than at
the application.

**Two ways this diagnostic was wrong at once.** It also ran local checks — port
80, `apps/web/.env.local`, the local enterprise mock — against a Cloud Run URL,
producing three failures that said nothing about the deployment and buried the
one line that mattered.

**Lesson.** A check inherits the assumptions of the environment it was written
for. Timeouts, ports and local files are all such assumptions, and none of them
survives a move to a serverless target.


---

## ADR-047 — A verdict must weigh the evidence

**Context.** Against the deployed instance, the diagnostic reported:

```
[FAIL] Cloud Run still answers with its own HTML page after 3 tries
[OK]   /api/v1/policy   -> 200
[OK]   /api/v1/agents   -> 200
[OK]   /api/v1/metrics  -> 200
[OK]   /api/v1/missions -> 200

1 blocking problem(s)
```

Four checks out of five passed. The service was serving. The verdict said the
deployment was broken.

**Why that is worse than a missing check.** An operator two days from a
deadline reads "1 blocking problem" and stops. A diagnostic that condemns a
working system trains its reader to ignore it — and the next time it is right,
nobody listens.

**Decision.** The failing probe becomes a warning, and the verdict is drawn
**after** the API routes have been tested:

- probe fails, routes answer -> "The service IS serving: 4/4 routes answered."
  The oddity is noted, not promoted to a blocker.
- probe fails, no route answers -> genuinely blocking, with the commands to
  inspect `status.url` and `status.conditions`.

A test asserts both outcomes, including that a dead service is still condemned:
weighing evidence must not become excusing everything.

**A supporting fact the tool should have used.** The Cloud Run startup probe
targets that same `/healthz`, and the service reports `Ready=True`. The
container therefore answers it. That single observation contradicted the
verdict, and it was already on screen.

**Lesson.** A check produces a fact. A verdict is an interpretation of all the
facts. Conflating the two turns one anomalous probe into a false emergency.


---

## ADR-048 — An empty string is not a missing value

**Context.** The deployed Mission Control rendered, then queried **its own
origin**:

```
GET https://acc-web-....a.run.app/api/v1/agents   404
GET https://acc-web-....a.run.app/api/v1/policy   404
```

Not the control plane. Not `127.0.0.1` either. Relative URLs.

**Cause.** `Dockerfile.web` declares:

```dockerfile
ARG NEXT_PUBLIC_ACC_API
ENV NEXT_PUBLIC_ACC_API=${NEXT_PUBLIC_ACC_API}
```

With no `--build-arg`, the argument is empty and the environment variable
becomes the **empty string** — not undefined. The client then did:

```ts
process.env.NEXT_PUBLIC_ACC_API ?? "http://127.0.0.1:8080"
```

`??` only catches `null` and `undefined`. The empty string won, every request
became relative, and the frontend interrogated itself.

The fallback was correct, the variable was correct, the Dockerfile was correct.
The operator that joined them was wrong by one character class.

**Decision.** `resolveApiBase()` uses truthiness, so an empty string falls
through to the runtime derivation (ADR-045). A test pins the resolver and
forbids `??` on that value, with the reason written next to it — this is
exactly the kind of line a later reader would "simplify" back.

**Why it survived to production.** Locally, `NEXT_PUBLIC_ACC_API` is either
absent (undefined, so `??` works) or genuinely set. The empty string only
appears when a Docker build receives no build argument — a path that exists
solely on the deployment.

**Lesson.** `??` and `||` are not interchangeable, and the difference only
shows up where a value is *supplied but blank*. Configuration pipelines produce
that state constantly: an unset build argument, an empty env var, a blank form
field.


---

## ADR-049 — `:latest` is invisible to a diff

**Context.** The first fully successful deployment. All three images built,
pushed and confirmed. Then:

```
Plan: 0 to add, 3 to change, 0 to destroy
~ scaling { min_instance_count = 0 -> null }
Apply complete! Resources: 0 added, 3 changed, 0 destroyed.
```

The only change was a no-op on a scaling block. **Not one service received its
new image.** The containers kept running the previous build — including the
Mission Control that queried its own origin, which this very deployment was
meant to fix.

**Cause.** Every image was tagged `:latest`, and Terraform was given that same
string. `image = ".../acc-web:latest"` before, `image = ".../acc-web:latest"`
after: no difference, no new revision. Cloud Run does not re-pull on its own.

The deployment "succeeded" three times in a row while shipping nothing.

**Decision.** Each build produces a per-deployment tag
(`:20260829-130452`) alongside `:latest`, and Terraform receives the unique
one. The diff becomes visible, the revision is created, the image actually
ships. `:latest` is still pushed — convenient for a manual pull, never the
deployed reference.

**Why it hid so well.** Every individual step reported success: the build, the
push, the apply. Only the *absence* of a revision change betrayed it, in a plan
summary that read like a normal no-op.

**Lesson.** A mutable tag makes a deployment idempotent in the worst sense:
repeatable, and repeatedly ineffective. If the deployment tool cannot see that
something changed, neither can the infrastructure.


---

## ADR-050 — A setting the container never receives is not a setting

**Context.** With the images finally rolled out, Mission Control reached the
right URL and the browser refused it:

```
Access to fetch at 'https://acc-api-....run.app/api/v1/missions'
from origin 'https://acc-web-....run.app' has been blocked by CORS policy:
No 'Access-Control-Allow-Origin' header is present.
```

**Cause.** `ACC_CORS_ORIGINS` and `ACC_CORS_ORIGIN_REGEX` were never passed to
the Cloud Run service. In cloud mode the control plane therefore allowed **no
origin at all**.

The regex itself was correct, and covered by a test since ADR-013. The test
checked the *value*. Nothing checked that the value ever reached the container.

**Why it survived every earlier check.** `curl` ignores CORS, so the API
answered perfectly from the command line and from `make doctor`. Only a browser
enforces it — and until this deployment, no browser had ever talked to the
deployed API.

**Decision.** Both variables are passed by Terraform, the allowed origin being
the web service URL, which is known only after the service exists.

**A dependency cycle created by the fix.** Reading the web service URL from
the API made it depend on `web`, while `web` still passed `NEXT_PUBLIC_ACC_API`
back from `api`. Terraform refused outright:

```
Error: Cycle: google_cloud_run_v2_service.api, google_cloud_run_v2_service.web
```

Two corrections, and the second matters more:

1. That runtime variable did nothing at all — Next.js inlines `NEXT_PUBLIC_*`
   at build time (ADR-045) — so removing it fixes a no-op.
2. **The API no longer references the web service at all.** The CORS regex
   already covers both Cloud Run URL formats, so the cross-reference bought
   nothing and cost a cycle. A configuration that cannot express the cycle is
   better than one that merely avoids it.

**A test that was too strict, and why that mattered.** The first guard banned
*every* cross-reference between services. But `api -> mock` is legitimate and
acyclic — the control plane genuinely needs the enterprise URL. Banning it
would have been simpler and wrong. The property is the absence of a *cycle*, of
any length, so it is now detected by traversal rather than pairwise. Verified
by reintroducing the cycle: the test names the path.

**Lesson.** Testing a configuration value proves it is right. It does not prove
it is *delivered*. Between the two lies every environment-variable bug ever
written.


---

## ADR-051 — A test that rebuilds the wiring tests its own copy

**Context.** After ADR-050 passed both CORS variables to Cloud Run, the browser
still refused every call. The variables were in the plan, in the container
environment, and correct.

**Cause.** `main.py` held a hardcoded constant:

```python
_CORS_ORIGIN_REGEX = (r"https://acc-web[-\w]*\.[-\w]*\.?run\.app" ...)
app.add_middleware(CORSMiddleware, allow_origin_regex=_CORS_ORIGIN_REGEX)
```

`ACC_CORS_ORIGIN_REGEX` and `ACC_CORS_ORIGINS` were read into `Settings`,
documented, passed by Terraform — and never used. The operator could set them,
see them applied, and change nothing.

**Why every CORS test stayed green.** `tests/.../build_app()` did not use the
application. It **rebuilt the middleware wiring itself**, from the settings it
was given:

```python
app.add_middleware(CORSMiddleware,
                   allow_origin_regex=settings.acc_cors_origin_regex, ...)
```

So the tests validated a faithful copy of what the code *should* do, while
production did something else. This is exactly the defect of ADR-037 — a double
that reimplements what it checks — in a different disguise, and it survived
several rounds of CORS work.

**Decision.** `cors_options(settings)` returns the middleware arguments, and is
the single source used by the application and by the tests. Three tests then
became meaningful: a custom regex must be honoured, an exact origin list must
be honoured, and the real Cloud Run origins must pass a full preflight through
the middleware.

**Verified by mutation.** Reintroducing the hardcoded constant now fails the
suite. Before the change, the same mutation passed.

**Lesson.** When a test constructs the object under test differently from
production, it measures the specification, not the implementation. The two only
agree until someone edits one of them.


---

## ADR-052 — A probe cannot vouch for a version it never runs

**Context.** Four rounds of CORS work, and the browser kept reporting the same
thing. The Cloud Run logs finally said what curl never could:

```
OPTIONS 500 https://acc-api-....run.app/api/v1/missions
ERROR: Exception in ASGI application
  File ".../opentelemetry/instrumentation/fastapi/__init__.py", line 495
    route = starlette_route.path
AttributeError: '_IncludedRouter' object has no attribute 'path'
```

**Cause.** `opentelemetry-instrumentation-fastapi` below 0.65b0 crashes on
FastAPI ≥ 0.141. Its middleware sits **before** the CORS one, so every request
became a 500 with no CORS headers. The browser reported a CORS failure whose
real cause was three layers down — and CORS was never broken at all.

**Why ADR-014's probe did not protect anything.** The probe called the
installed `_get_route_details` before enabling instrumentation. It ran in the
build environment, which had the **fixed** 0.65b0. Inside the container, pip
backtracked to **0.63b1** — constrained by `google-adk`'s pin on
`opentelemetry-api` — and the probe had certified a version that was never
deployed.

Worse, the probe's synthetic scope exercised `GET /healthz`, a path that
matches early. The crash happens on requests that must scan the whole route
table: OPTIONS, unknown paths. A narrow probe on a happy path.

**Decision.** The package is removed, and auto-instrumentation with it. What is
lost: automatic HTTP spans. What is kept: mission spans, `trace_id`
correlation, the audit trail — ACC's own code, dependent on no optional
package. For the demo and for the judging criteria, none of the value was in
that dependency.

**Locked.** Tests forbid re-enabling `FastAPIInstrumentor`, forbid the package
in `requirements.txt`, assert that **only** the CORS middleware is installed —
anything placed before it can swallow a preflight — and check that mission
tracing still works without it.

**Two lessons.**

A probe validates the environment it runs in. When the deployed environment
resolves dependencies differently — and a container always does — the probe
certifies something that does not exist there. Only a test *inside the
deployment artifact*, or removing the risk, actually protects.

And a browser error names the layer that noticed, not the layer that failed.
"CORS policy" was accurate and pointed four layers above the bug.


---

## ADR-053 — Accent-free French defeats an accent check

**Context.** With CORS finally working, the deployed API answered Mission
Control properly — in French:

```json
{"error": {"code": "UNAUTHORIZED",
           "message": "Cle d'API invalide ou absente"}}
```

Two guards had been in place since the English translation, and both missed it.

**Why.** The string contains **no accent**, so the accent-based detector saw
nothing. And `apps/api/routes/deps.py` was not in the list of files whose
strings are user-facing — a list I had written by hand, from memory.

A sweep of the whole backend then found **ten more**: alert messages, Model
Armor verdicts, circuit breaker errors, forbidden state transitions, and the
Failure Twin's own description in the fleet panel. All of them visible to a
judge.

**Decision.** The detector now also matches accent-free French phrases, and the
file list is extended. Both changes were driven by the miss, not by the design:
the original list was an assumption about which files speak to the user.

**Lesson.** A detector built from one signal — accents — measures that signal,
not the property. Every guard should be tested against an example it is
supposed to catch; this one never was, and it silently passed on the exact
class of string it existed for.

---

## ADR-054 — A key inside a public bundle is not a secret

**Context.** Once the message was readable, the substance remained: the
deployed frontend received `401 UNAUTHORIZED`. The control plane requires
`x-api-key`; Mission Control was never built with one.

**Decision.** `deploy.py` reads the generated key from Secret Manager and bakes
it into the web image, exactly as it does for the API URL — `NEXT_PUBLIC_*` is
inlined at build time, so a runtime variable cannot work (ADR-045).

**What this does and does not protect, stated where the code reads the key.**
Anyone who loads the page can read the key. That is inherent: a public
single-page application calling a public API cannot hold a secret. The key
stops casual scanning of the Cloud Run URL, nothing more, and it is regenerated
by `terraform destroy` + `apply`.

Pretending otherwise would be the real defect. The honest alternative — proxying
the API through the Next.js server so the key stays server-side — is a larger
change than this submission window allows, and is recorded here as the correct
next step rather than silently implied.


---

## ADR-055 — Pub/Sub push cannot send a custom header

**Context.** Mission Control worked, the mission was created (201), and then
nothing. `EXECUTING`, stage `planning`, 0 %, two events, no agent activity.

**Cause.** The push endpoint authenticated on an `x-pubsub-token` header:

```python
if expected and x_pubsub_token != expected:
    return Response(status_code=401)
```

**A Pub/Sub push subscription cannot send custom headers.** It carries an OIDC
token in `Authorization`, nothing else. So the header was always `None`, every
push was rejected with 401, the subscription retried until the messages
expired, and the mission stayed frozen — with no error anywhere in the
application, because the 401 *was* the intended behaviour of that line.

**Decision.** The shared token travels in the query string, which a push
subscription does carry. Authentication stays layered: Cloud Run verifies the
OIDC token before the request reaches the code, and the application checks the
shared secret. The header is still accepted, for a caller that can set one.

**Why local tests never caught it.** Locally `ACC_EVENT_BUS=inproc`: the worker
calls `dispatch()` directly and never crosses HTTP. The push endpoint only runs
in cloud mode — the one configuration no test exercised.

---

## ADR-056 — EventSource cannot send a header either

**Context.** With missions progressing, the live stream still answered 401 and
Mission Control displayed `polling`. The fallback worked, so nothing looked
broken — the demo had simply lost its real-time timeline.

**Cause.** `EventSource`, the browser API behind SSE, has **no API for request
headers**. It could not send `x-api-key`.

**Decision.** `require_api_key` also accepts an `api_key` query parameter, and
the frontend appends it to the stream URL. A query parameter is more exposed
than a header — it appears in URLs and access logs — and that is acceptable
here only because this key is already public by construction (ADR-054). The
reason is written next to the code, so the trade-off is not rediscovered as a
mistake.

**The same shape, twice in one deployment.** Pub/Sub cannot set a header;
EventSource cannot set a header. Both were authenticated by a header. A
mechanism must be checked against what the *caller* can actually send, not
against what feels most correct.


---

## ADR-057 — Two Cloud Run services are not on the same network

**Context.** Pub/Sub delivered, the stream was live, 94 events flowed — and
every enterprise call failed:

```
Tool failure suppliers: HTTP 404
Tool failure risk: HTTP 404
Circuit open on suppliers after repeated failures
```

The circuit breaker did its job, the Failure Twin escalated, the operator
approved five times. The governance worked perfectly around a dependency that
was never reachable.

**Two causes, stacked.**

1. **Ingress.** The enterprise mock was `INGRESS_TRAFFIC_INTERNAL_LOAD_BALANCER`.
   A Cloud Run service calling another over its **public URL** leaves the
   Google network and comes back, so internal-only ingress rejects it — with a
   **404**, which reads like a missing route rather than a blocked request.
   Being "in the same project" is not being on the same network.

2. **Identity.** Only `acc-api` holds `run.invoker` on the mock, and Cloud Run
   verifies that through an **OIDC identity token** — never through the
   application API key. The client sent none, so even with ingress open the
   call would have been refused.

**Decision.** Ingress opens to `INGRESS_TRAFFIC_ALL`, and access stays
restricted by IAM — opening ingress must not open access, and a test asserts
`allUsers` is never granted on the mock. The client mints an identity token for
the target audience, and only when the target is a real `https://` URL: local
runs and ASGI-transport tests are untouched, and the absence of a metadata
server degrades to no token rather than to an error.

**A third defect, visible in the same timeline.** An agent finding was written
in French, in a submission required to be in English. `ACC_AGENT_MODE=hybrid`
means Gemini writes those strings, and a model answers in whichever language it
prefers unless told. The guardrails now require English for every
human-readable field. Translating the prompts was not enough: the *output*
language had to be specified too.


---

## ADR-058 — A capability the registry does not declare is a runtime denial

**Context.** In the deployed approval modal, the Failure Twin's own evidence:

```
get_supplier_status failed with CAPABILITY_DENIED for agent failure-twin
get_production_schedule failed with CAPABILITY_DENIED for agent failure-twin
```

**Cause.** The registry declared `supplier.read`, a capability no tool
requests, while the tools call `supplier.status` and `production.read`. An
audit of all four agents found **every one** missing at least one capability
its tools invoke, and **seven** declared capabilities matching no tool at all.

**Why it appeared only in the deployed demo.** Deterministic mode calls a fixed
subset of tools, and that subset happened to avoid the gaps. Only a model
choosing its own tools reaches them — so the first execution in `hybrid` mode
was the first execution that could fail this way.

**Decision.** Registry capabilities are exactly what an agent's tools can
invoke: no missing one, which produces a denial the operator must decipher; and
no extra one, which is unjustified authority in a project whose whole argument
is least privilege.

**Locked structurally.** Tests derive the required capabilities from the tool
functions themselves and compare them to the registry, per agent. Adding a tool
without its capability, or a capability without its tool, now fails the suite —
including the one that matters most: only `procurement-agent` may hold
`purchase.execute`.

---

## ADR-059 — A reset that resets nothing is worse than no reset

**Context.** Opening the deployed Mission Control showed an approval modal
straight away — `attempt 6`, `5 previous recovery attempts`, from an earlier
rehearsal. Missions from every run had accumulated.

**Cause.** `FirestoreStore.reset()` raised `NotImplementedError`. The Reset
control answered 200 and did nothing. In memory mode — every test, every local
run — reset works, so nothing ever exercised the deployed path.

**Decision.** Reset is implemented for Firestore, refusing outright when demo
mode is off, with the guard placed before any deletion and a test asserting
that order. Demo mode is passed to the store explicitly rather than read from a
global: a store cannot purge data its caller never authorised.

Firestore has no recursive delete in the client library — sub-documents survive
their parent — so the nine sub-collections are drained explicitly. A test
derives the list from the writes themselves: adding a sub-collection without
adding it to the reset now fails, because the orphans it would leave are
invisible to every query.

**And the fix itself shipped a 500.** The new `reset()` called
`logger.info(...)` in a module that defines no `logger`. Syntax valid, imports
valid, tests green — because those tests read the source as **text** and never
executed a line of it. The NameError waited for the one path no test ran, and
surfaced in production.

A fake Firestore client — forty lines, no emulator, no credentials — now
executes the real method. Removing the logger again fails the suite with the
exact `NameError`. A static guard additionally rejects any module that uses
`logger` without defining one.

**Lesson.** A demo control that silently does nothing is the worst kind of
failure before an audience: it produces confidence, then a stale approval on
screen at the exact moment the story is supposed to start. And a test that
inspects source text proves the code was written, never that it runs.


---

## ADR-060 — Fixing one client leaves the other one broken

**Context.** After implementing the Firestore reset and fixing a `NameError`
in it, the Reset control still answered **500**.

**Cause, in a place the previous fix never touched.** `_enterprise()` in the
demo routes built its **own** `httpx.AsyncClient`:

```python
async with httpx.AsyncClient(base_url=...) as client:
    response = await client.request(method, path)
    response.raise_for_status()
```

That client knew nothing about Cloud Run identity tokens. The authentication
fix of ADR-057 had been applied to `EnterpriseToolClient` alone. So **every**
demo control — reset, failure injection, hostile injection, runtime
interruption — was refused once deployed. The whole control panel the demo
depends on was broken, and only the reset had been tried.

**Two clients, one of them corrected.** This is ADR-051 again — production and
a second implementation drifting apart — in a third code path.

**Decision.** Demo controls go through the shared `EnterpriseToolClient`. A
test forbids any route from constructing an `httpx.AsyncClient`: a second
client is a second authentication path, and it will be forgotten.

**And the failure now names itself.** `DemoControlFailed` reports which step
broke — enterprise systems unreachable, store reset refused, demo mode off —
instead of a bare 500. Minutes before a recording, an error that says nothing
about where to look is the most expensive kind.

**And the fix shipped its own defect.** `_enterprise()` then read
`result.status` on a `ToolCallResult` that exposes `ok`. The error contract did
its job — `DEMO_CONTROL_FAILED: 'ToolCallResult' object has no attribute
'status'` — but the defect reached production because, once again, the test
asserted that a *string appeared in a file*.

**The routes had no executing test at all.** The `api` fixture rebuilds its own
FastAPI instance and never includes the demo router: no test could reach these
endpoints even in principle. Six tests now call the **production application**,
covering every control, the English wording of the responses, and the failure
path. Reintroducing `result.status` reproduces the exact message seen in the
browser.

**Lesson.** When a cross-cutting concern is fixed in one place, the question is
not whether the fix is correct but **how many places implement that concern**.
The answer here was three, found one at a time, in production. And each of
those fixes was validated by a test that read source text — which is why each
one shipped a new defect.


---

## ADR-061 — An action is identified by what it does, not by who attempts it

**Context.** The first successful end-to-end mission in the cloud, in `hybrid`
mode. It completed, 100 %, no failure injected — and the timeline showed:

```
19:32:51  Purchase order PO-8831 for 1200 units from SUP-A ... $4800.00
19:33:00  Purchase order PO-8832 for 1200 units from SUP-A ... $4800.00
Duplicates prevented: 0
```

**Two real purchase orders for one mission.** Against the product's first
claim — *"a resumable agent never orders twice"* — and against ADR-004, which
exists precisely to prevent it.

**Cause.** The idempotency key was `mission_id + task_id + action`. A mission is
decomposed into a planning task and an execution task. Deterministic mode only
purchases in the execution task, so the two never collided. A model choosing
its own tools purchased during planning as well: two tasks, two keys, two
orders.

ADR-004 deliberately excluded the *attempt* from the key, to survive retries.
It kept the *task*, and that was the remaining hole — invisible until the fleet
ran on a model.

**Decision.** A consequential action is keyed by the **mission** and by **what
it does** — supplier, units, amount — never by the task attempting it:

```
MIS-1001-purchase.execute-supplier_id=SUP-A-units=1200-amount=4800
```

Including the business parameters is what keeps the guarantee honest in both
directions: the same purchase from two tasks is one order, while a fallback
purchase from SUP-B after a recovery is a genuinely different action and must
not be deduplicated away.

Observations keep their task-scoped key: a read must re-observe the world
(ADR-024).

**Verified by mutation.** Restoring the old key reproduces two purchase orders
in the test. And one of the new tests had to be corrected first: it asserted a
fallback at 18 000 $, which POLICY refuses — it would have passed or failed for
a reason unrelated to idempotency.

**Lesson.** Every defect found in this deployment shares one shape: a mechanism
validated only against the deterministic path, then exercised for the first
time by a model that makes its own choices. `hybrid` mode is not a variant of
the demo — it is a different execution of the whole system.


---

## ADR-062 — A registry no deployment can update is the wrong kind of durable

**Context.** The idempotency fix (ADR-061) was live — same `PO-8831` twice,
`Duplicates prevented: 1`, `purchase.execute REPLAYED`. Yet the same trace
still showed:

```
production.read   DENIED   Capability missing from the registry
```

for a capability the source had granted, and the fleet panel reported
`4 capabilities` where the code declares three.

**Cause.** The registry is persisted in Firestore, and `bootstrap()` returned
the stored record untouched whenever the agent already existed:

```python
existing = await self.store.get_agent(seed.agent_id)
if existing is None:
    ...create...
else:
    registered.append(existing)     # declarations never reconciled
```

So a capability fixed in code could never reach the deployed fleet. The code
change was real, the deployment was real, and the behaviour was frozen in a
document written on the very first startup.

Locally the defect is invisible: the in-memory store starts empty, so every
agent takes the creation branch.

**Decision.** Bootstrap reconciles the fields the **code owns** — capabilities,
denied capabilities, authority level, risk level, version, name, description —
and logs which ones changed. Operational state is deliberately **not**
overwritten: a suspended agent stays suspended across a redeployment, because
that is exactly what fleet governance means (Doc 02 §22). Resetting every
status on deploy would silently re-admit an agent an operator had removed.

**Locked.** Tests assert both halves: a stale capability set is corrected, an
explicit denial is restored, and a suspended agent survives. Reverting to the
non-reconciling bootstrap fails with "a redeployment did not restore the
declared capabilities".

**Lesson.** State that outlives a deployment must be split into what the code
declares and what the fleet lives. Persisting both under one record makes the
first one unfixable — in the component whose entire purpose is to say who may
do what.


---

## ADR-063 — A Reset button that removes the Reset button

**Context.** Pressing **Reset** on the deployed Mission Control cleared every
mission — and with it the entire side column: fleet, autonomy boundary, and the
demo controls themselves. Reset, "Fail SUP-A" and "Hostile injection" all
vanished. The only way to get them back was to launch a mission.

**Why that breaks the demo, not just the ergonomics.** The script prescribes
one mandatory order:

```
reset → arm → launch → decide
```

The failure MUST be armed **before** launching: a nominal mission finishes in
0.3 seconds, so a failure injected afterwards has no effect at all (ADR-032).
The interface made the documented order impossible to perform — the operator
was left choosing between a clean slate and the controls needed to use it.

**Decision.** The side column stays mounted with no mission. Reset, failure
injection and hostile injection act on the enterprise systems and on stored
state, so they need no mission. Interrupt and resume do need a live one, and
were already disabled — the message now distinguishes "no mission yet" from
"mission finished", because those call for opposite actions.

**Locked.** A test asserts the controls, the fleet and the policy panel appear
in the empty-state branch. Removing the column fails the suite, with the
script's order as the stated reason.

**Lesson.** The demo script and the interface are one artifact. Testing the
script's *claims* against the backend (ADR-032) proved the facts were true; it
could not prove the sequence was performable. A prescribed order needs a test
that the product permits it.


---

## ADR-064 — Do not hand a model a precedence rule to apply

**Context.** The hero scenario, run properly for the first time in the cloud:
Reset, Fail SUP-A, then launch. The recovery worked exactly as designed — and
the mission failed anyway:

```
Recovery selected: USE_ALTERNATIVE_SUPPLIER
Recovery applied:  USE_ALTERNATIVE_SUPPLIER
Supply Agent activated: Supplier availability analysis
Tool failure suppliers: HTTP 503        <- SUP-A again
... three times ...
FAILED · recovery_exhausted
```

**Cause.** The recovery set `context.selected_supplier = "SUP-B"` correctly.
The prompt payload then exposed `primary_supplier: SUP-A` and
`selected_supplier: SUP-B` **side by side**, and the agent instruction said
"fetch the primary supplier status". The model did exactly that, re-queried the
supplier that had just failed, and the loop ran until the attempt budget was
spent.

The deterministic path reads `selected or primary` in code and was never
affected — which is why this survived every local run.

**Decision.** The context exposes `current_supplier`, resolved **once**, in
Python. `primary_supplier` and `selected_supplier` remain for evidence and
narrative, but no consumer has to combine them. The guardrails state that
`current_supplier` already accounts for any recovery and that re-checking the
primary reproduces the failure.

**Locked.** A test asserts the resolved field follows a switch, that both agent
instructions name it, and that the switch reaches the supply agent end to end
with SUP-A failing. Removing the field fails the suite.

**Lesson.** Every rule left for the model to apply is a rule that will
eventually be applied differently. Precedence, fallback, defaulting — resolve
them in code and hand over the answer, not the inputs and the policy.

This is the same shape as ADR-058 and ADR-061: a mechanism that was correct in
deterministic mode and wrong the first time a model made the choice. The
deterministic fallback is a safety net for the demo, never evidence that the
system works.


---

## ADR-065 — An interface must not assert what it does not know

**Context.** Told that the recording should use `deterministic` mode, the
operator answered: *"but I am already in deterministic, am I not?"* The demo
panel said so, in plain type.

**It was a literal string.**

```tsx
<span className="font-mono text-[10px] text-ink-dim">deterministic</span>
```

The deployment runs `hybrid` — the Terraform default. The panel had never read
the mode from anywhere; it displayed a word.

**What that cost.** The evidence was in the operator's own traces: 10-20 s per
agent, and prose reworded on every run. Deterministic output is byte-identical.
But a label stating the opposite turned that evidence into a performance
problem instead of the obvious conclusion — a model was answering every step.

The label did not merely fail to inform. It **actively misled**, for several
runs.

**Decision.** The control plane exposes `agent_mode` in the autonomy boundary
it already serves, and the badge renders that value. Terraform documents what
each mode costs in demo time and validates the value, so a typo fails the plan
rather than the recording.

**Locked.** A test rejects the literal in the component and requires the field
in the API.

**Lesson.** This project has spent sixty-five records separating what the system
*is* from what it *says*: metrics that flattered on missing data (ADR-022),
checkpoint labels asserting a recovery that never happened (ADR-033), an audit
event for an interruption that never occurred (ADR-031). This is the same fault
in the smallest possible surface — one word, hardcoded — and it cost more
debugging time than any of them.


---

## ADR-066 — Mutating the caller's object is not persisting

**Context.** In `deterministic` mode — the model out of the picture entirely —
the hero scenario still looped:

```
Recovery applied: USE_ALTERNATIVE_SUPPLIER   (SUP-B)
Supply Agent activated
Tool failure suppliers: HTTP 503             <- SUP-A again
... three times ...
FAILED · recovery_exhausted
```

The Failure Twin was right every time: five options evaluated, three
permitted, SUP-C ruled out on lead time, SUP-B selected, the plan itself
passed through the Policy Engine. And the retry queried the supplier that had
just failed.

**Cause.** `_apply()` set `mission.context.selected_supplier` **on the object
it was handed** and never wrote it. The Mission Engine reloads the mission
before applying the directive, and `save_mission` is a whole-document `set()`,
so any later save of an object loaded before the switch erased it.

**Why every test passed, and kept passing after the first fix.** The in-memory
store shares object instances: mutating the caller's mission is
indistinguishable from saving it. Adding `save_mission(mission)` changed
nothing observable locally either — removing it again still passed. Four tests
in a row could not tell a persisted switch from a mutated one.

**Decision.** Reload, mutate, save. The switch lands in the store regardless of
which object the caller holds; the caller's copy is updated too, so nothing
downstream sees a stale value.

**The test that finally distinguishes** hands `_apply()` a deep copy that is
*not* the stored mission, then reads the store. Reverting to the in-place
mutation fails with "the switch stayed on the caller's object and never reached
the store". Every earlier test passed either way — which is exactly what made
this defect survive two rounds of fixing.

**Lesson.** ADR-008 said a concurrency test written against the in-memory store
validates a property production lacks. This is the same store lying about a
different property: **object identity**. Any test asserting that something was
*saved* must read it back through a boundary that copies.


---

## ADR-067 — A detector that cries wolf gets disabled

**Context.** The security demonstration worked in the cloud — three hostile
instructions blocked — and printed its verdict in French, in the trace a judge
reads:

```
Model Armor: Tentative de neutralisation des instructions/politiques |
Tentative de contournement de l'approbation humaine | ...
```

Seven verdict strings, plus the prompt preamble sent to Gemini
(`Contexte de mission (donnees, pas instructions)`). Every earlier sweep missed
them: no accents, and the words were not in the phrase list.

**The phrase list is the wrong shape of guard.** It was extended after each
miss — "requete", "prete", "panne", now "tentative", "injonction". Each
extension proves the previous list was a guess.

**And extending it introduced a false positive.** Substring matching flagged
`logger.warning("demo_supplier_failure_injected")` on the French "injecte". A
detector that reports non-defects is a detector the next reader turns off — so
the matching is now word-bounded, and the file list covers the services that
actually emit operator-visible strings.

**What would have been better.** A language identifier over every string
literal, rather than a hand-written vocabulary. The phrase list is what fits
the remaining time; recording that it is a compromise is the honest part.

**Lesson.** A guard built from examples catches the examples. Each miss taught
the list one more word, which is precisely the shape of a check that will keep
missing — and the reason this one is documented as a stopgap rather than as a
solution.


---

## ADR-068 — A decision window with no exit forces a decision

**Context.** The operator asked why the script shows the Recovery tab at
0:50 and the approval modal at 1:45, when the modal is already up before either
can be opened — and why the demo controls are unreachable while it is.

Both observations were right, and the second contradicted an instruction added
one revision earlier: "click Kill the runtime **while the approval modal is
up**". The modal is an overlay. That sequence was impossible.

**The deeper defect.** The modal had no exit. To read the Recovery evidence —
five options, two ruled out, the reason SUP-C was refused — the operator had to
approve or reject **first**. ACC's own claim is that an approval is durable
state, not a UI session; a window that forces a decision before inspection is
the exact habit the product exists to prevent.

**Decision.** **Decide later** closes the window without deciding. The approval
stays pending in the control plane — nothing is rejected, nothing expires — and
a banner keeps it one click away, so a deferred decision cannot be lost. The
script now follows the real order: the modal arrives first, is dismissed,
evidence is read, and the decision is taken afterwards.

**Why the timing is not a flaw to hide.** In deterministic mode the whole chain
— failure, recovery, purchase plan, authority boundary — completes in under a
second. The request for human authority arrives before the narrator has spoken.
That is the product working. The script now says so.

**Lesson.** ADR-063 made the prescribed order possible; this one makes it
*truthful*. A script written from the intended design will drift from the
built product, and only running it in front of a real screen surfaces the
difference. The operator ran it. I had not.


---

## ADR-069 — A breaker must protect, not imprison

**Context.** Hours before submission, every demo control answered:

```
502 DEMO_CONTROL_FAILED
Enterprise systems unreachable at /demo/reset:
Circuit open on demo after repeated failures
```

**Two defects, stacked.**

1. **The breaker could never close.** It reset only on a successful call — and
   while open, no call goes through, so no success can occur. Once tripped it
   was a permanent outage wearing the costume of a safety mechanism.

2. **The controls were gated by it.** Since ADR-060 routed the demo controls
   through the shared enterprise client, their failures accumulated under the
   `demo` key. `Reset` — the control an operator uses to **repair** a broken
   state — was blocked by the breakage it repairs.

That second one is ADR-024 in a new place: idempotency once blocked the recovery
that was meant to fix the world. Here the breaker blocked the reset. **A repair
must never sit behind the failure it repairs.**

**Decision.** Operator-triggered controls are exempt: the breaker exists to stop
an *agent* from hammering a failing dependency, not to stop a human from fixing
it. And the breaker gained a 30-second cooldown, after which one call is let
through — half-open, not reset: the counter returns to threshold minus one, so a
still-broken dependency re-opens immediately instead of starting over.

**Locked.** Tests assert the exemption, the eventual close, that protection
still holds before the cooldown, and that half-open is a single probe rather
than a clean slate. Removing the exemption fails the end-to-end reset test.

**Lesson.** Every protection mechanism in this project has, at least once,
protected the system against its own recovery. Idempotency against re-observing
a corrected world (ADR-024). Deletion protection against the teardown that stops
billing (ADR-044). Now a circuit breaker against the reset. The question to ask
of any guard is not "what does it block?" but **"does it block the thing that
would fix it?"**
