# Devpost submission — ready to paste

Character limits are respected and shown. Anything marked **[YOU]** needs a
value only you have.

---

## Project name (60 max)

```
ACC — Autonomous Mission Control
```
*31 characters.*

---

## Elevator pitch (200 max)

```
Enterprise agents break. ACC keeps the mission alive: it detects the failure, picks the best PERMITTED recovery, asks a human when authority runs out, and proves every decision.
```
*175 characters.*

---

## About the project

### Inspiration

Every agent platform we looked at knows how to launch agents. None of them
answers the question an operations team asks first: **what happens when an
agent fails in the middle of something that matters?**

An agent stuck at 60 % of a procurement workflow is a stopped production line.
The industry's answer is to make agents smarter. We think that is the wrong
unit of reliability. A single agent will always be able to fail — the mission
is what must not.

So we changed the question. Not "how do we make this agent better?" but **"how
do we keep the mission alive when the agent, the dependency, or the runtime
goes down?"**

### What it does

ACC is a control plane for autonomous enterprise missions. A governed fleet of
four ADK agents executes a long-running mission; when reality breaks, ACC
recovers it **without leaving its authority boundary**.

The hero scenario, running live on Cloud Run:

1. A mission must secure 1 200 units within 48 hours. The fleet starts work.
2. The primary supplier returns HTTP 503. The mission is marked AT RISK.
3. The **Failure Twin** diagnoses it, evaluates five recovery options and rules
   out two: retrying a DEPENDENCY failure, and a cheaper supplier that would
   deliver in 60 h against a 48 h deadline.
4. It selects the best **permitted** option — not the best one. That distinction
   is the product.
5. The fallback costs 18 000 $, above the 5 000 $ autonomous threshold, so ACC
   stops and asks a human. In the nominal run the same mission costs 4 800 $ and
   completes with no intervention: it is the *disruption* that crosses the
   boundary.
6. A hostile supplier message tries to bypass the policy. Model Armor blocks it;
   the approval is still required.
7. The operator approves. The purchase executes **exactly once**, and the whole
   chain is reconstructable from the trace.

Two properties hold throughout: **recovery is itself governed** — the Failure
Twin's plan goes back through the Policy Engine like any other action — and an
approval is **durable state**, surviving a runtime kill and resuming when the
human answers.

North star metric: **Mission Continuity Rate**, the share of *disrupted*
missions that still reach their objective. The deployed run reports 100 % on
one disrupted mission, with zero policy violations.

### How we built it

- **Control plane** — FastAPI on Cloud Run: Mission Engine, Recovery Engine,
  Policy Engine, Approvals, Memory Bank, Agent Registry, Audit.
- **Agent fleet** — Google ADK with **Gemini 3.6 Flash**: Supply, Risk,
  Procurement and the Failure Twin. Three execution modes (`adk`, `hybrid`,
  `deterministic`); the deterministic path calls no model **but still traverses
  the Agent Gateway**, so governance is demonstrable without a quota.
- **The Agent Gateway** is the single execution boundary:
  `IDENTITY → CAPABILITY → POLICY → APPROVAL → IDEMPOTENCY → TOOL → MODEL ARMOR → AUDIT`.
  No line of code lets an agent reach an enterprise system any other way.
- **State** — Firestore is the source of truth; Pub/Sub carries asynchronous
  continuation, so no mission depends on an HTTP request or a container's
  lifetime.
- **Security** — Model Armor on prompts and tool output, Secret Manager for
  generated secrets, per-service IAM identities, OIDC between services.
- **Frontend** — Next.js 15 on Cloud Run, live SSE with automatic polling
  fallback.
- **Infrastructure** — Terraform, Cloud Build, Artifact Registry, one
  cross-platform Python deployment script with a preflight that verifies
  credentials, APIs and build identity *before* spending anything.

### Challenges we ran into

Almost every real defect had the same shape: **a mechanism that was correct in
the deterministic path and wrong the first time a model made its own choices,
or correct in memory and wrong the first time state crossed a process.**

- **Two purchase orders for one mission.** The idempotency key contained the
  task id. A mission has a planning task and an execution task; the model
  purchased from both. Fixed by keying a consequential action on the mission
  and on *what it does* — while keeping a fallback purchase from another
  supplier a genuinely different action.
- **A recovery that recovered nothing.** The switch to the fallback supplier was
  written on the caller's object and never persisted. The in-memory store shares
  instances, so every local test passed; Firestore returns a copy, and the retry
  queried the supplier that had just failed.
- **CORS that was never CORS.** The browser reported a CORS failure for days.
  The real cause was three layers down: an OpenTelemetry instrumentation
  crashing on FastAPI ≥ 0.141, *before* the CORS middleware, so every request
  became a 500 with no headers.
- **Authentication mechanisms checked against what the caller cannot send.**
  Pub/Sub push cannot set a custom header. Neither can `EventSource`. Both were
  authenticated by a header.
- **A UI that asserted what it did not know.** The demo panel printed
  "deterministic" as a literal string while the fleet ran on Gemini — turning
  20-second agent calls into a suspected performance problem.

### Accomplishments that we're proud of

- The hero scenario runs end to end **on Google Cloud**, and every figure the
  demo script quotes is verified by an executable test — option counts,
  thresholds, amounts, even the mandatory click order.
- **423 tests and an 87-requirement coverage audit** that links each blueprint
  requirement to a real pytest node id: you cannot tick a box by renaming a test.
  The suite also passes with `google-adk` uninstalled.
- **68 numbered architecture decisions**, most of them recording a defect found
  by running the system rather than by reading it — including the ones above.
- Recovery that cannot bypass governance, and a Failure Twin that explains why
  the *best* option was refused.

### What we learned

**A test that inspects source text proves the code was written, never that it
runs.** Two production 500s reached us through tests asserting that a string
appeared in a file.

**The in-memory store lies about two different things** — concurrency, and
object identity. A test asserting something was *saved* must read it back
through a boundary that copies.

**A prescribed sequence needs a test that the product permits it.** Our demo
script was verified against the backend and still described an impossible click
order, twice.

And the one that cost the most: **every rule left for the model to apply is a
rule that will eventually be applied differently.** Precedence, fallback,
defaulting — resolve them in code and hand the model the answer, not the inputs
and the policy.

### What's next for ACC

- Proxy the API through the Next.js server so the operator key never reaches the
  browser bundle — the honest limitation of the current deployment.
- Replace our hand-written French-phrase detector with a real language check on
  string literals.
- Multi-mission fleet scheduling, agent suspension on anomaly, and recovery
  strategies learned from the recovery history ACC already records.

---

## Built with (25 max — 18 used)

```
python, fastapi, google-adk, gemini, vertex-ai, cloud-run, firestore,
pub-sub, model-armor, secret-manager, cloud-build, artifact-registry,
opentelemetry, terraform, typescript, next.js, react, tailwindcss
```

---

## Form answers

| Field | Answer |
|---|---|
| **Category** | Fortified Enterprise Fleet |
| **Google SDK used** | Google ADK (Agent Development Kit) |
| **Google Cloud services** | Cloud Run, Firestore, Pub/Sub, Vertex AI, Model Armor, Secret Manager, Cloud Build, Artifact Registry, Cloud Logging, IAM |
| **Google AI models** | **Gemini 3.6 Flash** (`gemini-3.6-flash`) via Vertex AI — meets the "3.5 or newer" requirement |
| **Reproducible testing in README?** | Yes |
| **Architecture diagram** | Upload `docs/diagrams/architecture.png` |
| **Hosted project URL** | `https://acc-web-jycspetv4a-ew.a.run.app` |
| **Submitter type** | **[YOU]** — Individual, unless you submit for a company |
| **Organization name** | **[YOU]** — leave empty if individual |
| **Start date (MM-DD-YY)** | **[YOU]** — must fall inside the submission period |
| **Code repository URL** | **[YOU]** — see the check below |
| **Startup Prize** | Skip unless you have an **incorporated** company and a corporate email |

---

## Testing instructions (paste into the private field)

```
No credentials are required: the deployed Mission Control is open, and the
API key is compiled into the frontend bundle by design (a public SPA calling a
public API cannot hold a secret; the key only deters casual scanning).

LIVE — https://acc-web-jycspetv4a-ew.a.run.app

The order matters. A nominal mission completes in 0.3 s, so the failure must be
armed BEFORE launching:

  1. Reset
  2. Fail SUP-A
  3. Launch mission          (defaults: 1200 units, 48 h)
  4. The approval modal appears immediately — click "Decide later"
  5. Recovery tab: 5 options evaluated, 2 ruled out. SUP-C is cheaper and
     lower-risk but delivers in 60 h against a 48 h deadline, so it is NOT
     permitted. ACC selects the best PERMITTED option.
  6. Click the banner, approve the 18 000 $ purchase
  7. Trace tab: identity, policy decision, approval, single execution

Optional, before step 3: click "Hostile injection" — a supplier message tries
to bypass the policy. Model Armor blocks it and the approval is still required.

Optional, while the mission is WAITING_APPROVAL: "Kill the runtime" then
"Resume". The approval survives.

LOCALLY — no cloud, no keys, under two minutes:

  pip install -r requirements.txt
  pytest -q                            # 423 tests
  python scripts/audit_coverage.py     # 87/87 requirements linked to a test
  python scripts/run_hero_scenario.py  # the full scenario in one process
```

---

## Before you press submit

- [ ] **Repository** — public, or shared with `testing@devpost.com` **and**
      `cloudhackathons@google.com`. Open it in a private window to be sure.
- [ ] **Video** — public on YouTube (not unlisted), ≤ 4 minutes, English or
      subtitled, and it shows the Cloud Run console.
- [ ] **Architecture diagram** — the PNG is *uploaded*, not just linked.
- [ ] **Category** — Fortified Enterprise Fleet actually selected.
- [ ] **Start date** — inside the submission period.
- [ ] **`.env` is not in the repository** — the archive excludes it; check your
      own working copy before pushing.
- [ ] Then, and only then: `make teardown` to stop billing.

Do not edit the repository, the video, or any linked material after the
deadline. Fork it if you want to keep building.
