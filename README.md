# ACC — Autonomous Mission Control

**The agent can fail. The mission doesn't have to.**

Mission-continuity and resilience layer for enterprise agent fleets.
**Fortified Enterprise Fleet** track — All Things Agentic Hackathon.

---

## The problem

Today's agent platforms know how to launch agents. They do not answer the one
question that matters in an enterprise: **what happens when an agent fails in
the middle of a critical operation?**

An agent stuck at 60 % of a procurement workflow is a stopped production line.
ACC is the control plane that keeps the mission alive, governed and auditable —
even when agents, dependencies or runtimes go down.

**North star metric: Mission Continuity Rate** — the share of *disrupted*
missions that still reach their objective.

---

## Quick start — 2 minutes, no cloud, no keys

```bash
unzip acc-autonomous-mission-control.zip && cd acc
pip install -r requirements.txt

pytest -q                              # 270 tests
python scripts/audit_coverage.py       # 66/66 requirements linked to a real test
python scripts/run_hero_scenario.py    # full hero scenario, single process
```

`deterministic` mode makes **no model calls at all, yet still traverses the
Agent Gateway** — policy, idempotency and audit are exercised identically.
That is what makes the demo replayable without a Gemini quota.

### Full stack with Mission Control

```bash
make run-mock      # simulated enterprise systems  → :8081
make run           # ACC control plane             → :8080/docs
make web-install   # once
make web           # Mission Control               → :3000
make doctor        # checks that everything talks to everything
```

Port 8080 is heavily contested (llama.cpp, XAMPP, Tomcat all default to it).
Everything is overridable:

```bash
make run PORT=8099
make web ACC_API=http://127.0.0.1:8099
make doctor PORT=8099
```

**Deploying to Google Cloud, cost control and teardown: see `DEPLOYMENT.md`.**

---

## The hero scenario

| Step | What happens | What it proves |
|---|---|---|
| 1 | Mission created: 1 200 units, 48 h deadline. The fleet works. | Multi-agent orchestration |
| 2 | SUP-A goes down (HTTP 503) — operator-triggered, never random | Real failure detection |
| 3 | The Failure Twin evaluates 5 options and **rules out 2** | Recovery intelligence |
| 4 | SUP-C is cheaper and lower-risk but delivers in 60 h > 48 h → **not permitted** | Best option ≠ best *permitted* option |
| 5 | SUP-B selected: 18 000 $ > the 5 000 $ autonomous threshold → **human approval** | Autonomy boundary |
| 6 | The runtime is killed. State survives. Resume replays nothing. | Mission durability |
| 7 | The operator approves → the purchase executes **exactly once** | Idempotency + human authority |

The narrative pivot: in the nominal case SUP-A costs 4 800 $ and the mission
completes **with no human intervention at all**. It is the disruption itself
that pushes the mission past the autonomy boundary. Governance is not scenery —
it fires because the situation changed.

**Three distinct narratives from volume alone**, with no failure injected:

| Volume | Amount | What happens |
|---|---|---|
| 1 200 u | 4 800 $ | Below threshold → the mission completes on its own |
| 1 500 u | 6 000 $ | Above threshold → **human approval required** |
| 1 601 u + | — | SUP-A capacity (1 500) exceeded → **Failure Twin activated** |

---

## Architecture

```
                     ┌──────────────────────────────┐
                     │      Mission Control (UI)     │
                     └───────────────┬──────────────┘
                                     │ REST + SSE
┌────────────────────────────────────▼──────────────────────────────────┐
│                          ACC CONTROL PLANE                            │
│                                                                       │
│  Mission Engine ──▶ Recovery Engine ──▶ Failure Twin                  │
│       │                    │                                          │
│       ▼                    ▼                                          │
│  Checkpoints          Policy Engine ──▶ Approvals (durable state)     │
│  Memory Bank                │                                         │
│  Audit / Traces             ▼                                         │
│                      ╔═════════════════╗                              │
│                      ║  AGENT GATEWAY  ║  ◀── the only way out        │
│                      ╚════════╤════════╝                              │
└───────────────────────────────┼───────────────────────────────────────┘
                                ▼
                  Enterprise systems (ERP, suppliers, procurement)
```

Diagrams: `docs/diagrams/architecture.png` (rendered, ready to view) alongside
the Mermaid sources `architecture.mmd` and `hero_sequence.mmd`. Rebuild the PNG
with `python scripts/make_architecture_diagram.py` — no browser, no Mermaid CLI.

**The Gateway pipeline is mandatory and cannot be bypassed:**

```
IDENTITY → CAPABILITY → POLICY → APPROVAL → IDEMPOTENCY → TOOL → MODEL ARMOR → AUDIT
```

No line of code lets an agent reach an enterprise system any other way. That is
what makes the "Fortified" claim verifiable rather than declarative.

### The strongest technical point

**Recovery is itself governed.** The Failure Twin never triggers an action: it
produces a plan that goes back through the Policy Engine, approval and audit,
exactly like any other agent action.

```
Failure Twin → Recovery Plan → Policy Engine → Approval if required → Gateway → Tool
```

Never: `Failure Twin → direct execution`.

---

## Contest requirements

| Mandatory requirement | Where |
|---|---|
| **Gemini 3.5 or newer** | `gemini-3.6-flash` (`config.py`, Terraform, `.env.example`) |
| **Google Agent Framework** | Google ADK — `agents/base.py`, `agents/runtime.py` |
| **Google Cloud service** | Cloud Run, Firestore, Pub/Sub, Secret Manager — `infrastructure/terraform/` |

All three are verified by `tests/unit/test_contest_compliance.py`, which fails
the build if a non-compliant model is configured.

### Fortified Enterprise Fleet primitives

| Required primitive | ACC implementation |
|---|---|
| Agent Registry | `apps/api/services/registry.py` — declared capabilities, versioning, trust status, suspension |
| Agent Runtime | `agents/runtime.py` — long-running, no local state |
| Memory Bank | `apps/api/services/memory_service.py` — structured, mission-scoped, non-rewritable |
| Agent Identity | `domain/models.py::AgentIdentity` — propagated via contextvars, never forged by a prompt |
| Agent Gateway | `apps/api/services/agent_gateway.py` — the single execution boundary |
| Model Armor | `apps/api/services/model_armor.py` — `gcp` / `heuristic` / `off` modes |
| Agent Observability | `apps/api/core/telemetry.py` + `trace_builder.py` — OTel traces and audit correlated by `mission_id` |

---

## Project layout

```
domain/                  Pure business model (no I/O, no prompts)
  enums.py               Statuses, failure classes, recovery strategies
  models.py              Mission, Task, Checkpoint, RecoveryPlan, Approval, Audit…
  state_machine.py       Allowed transitions — none are implicit
  plans.py               Deterministic decomposition of missions into tasks

apps/api/
  core/                  Config, execution context, JSON logs, telemetry
  repositories/          InMemoryStore (local/tests) + FirestoreStore (Cloud Run)
  services/              The 18 control-plane services
  routes/                REST + SSE + Pub/Sub push + demo controls
  main.py                FastAPI application

apps/web/                Mission Control (Next.js 15 + TypeScript + Tailwind)
  lib/api.ts             Control-plane client, unified error contract
  hooks/                 SSE stream with automatic polling fallback
  components/            Fleet, timeline, recovery, trace, approval panels

agents/                  Google ADK + Gemini fleet
  base.py                ADK wrapper: adk / hybrid / deterministic modes
  contracts.py           Single output contract + robust parsing
  tools/gateway_tools.py ADK tools — each one traverses the Gateway
  supply/ risk/ procurement/ failure_twin/

mock_enterprise/         Deterministic simulated ERP, suppliers and procurement
infrastructure/          Dockerfiles + Google Cloud Terraform
scripts/                 Hero scenario, deployment, diagnostics, cost, teardown
tests/                   270 tests: unit, integration, scenarios, compliance
```

---

## Three agent execution modes

`ACC_AGENT_MODE` drives the fleet:

| Mode | Behaviour | Use |
|---|---|---|
| `adk` | Gemini through ADK only | Production |
| `hybrid` | ADK, deterministic fallback if the model fails | **Recommended for the demo** |
| `deterministic` | No model calls | Tests, demo safety net |

The key point: **deterministic fallbacks still call the Gateway.** Policy,
idempotency and audit are exercised identically, without depending on a Gemini
quota or a network connection during the demo.

---

## Configuration

Copy `.env.example` to `.env`. No secrets in the repository; in production,
Secret Manager and Workload Identity only.

| Variable | Default | Purpose |
|---|---|---|
| `ACC_PERSISTENCE` | `memory` | `memory` or `firestore` |
| `ACC_EVENT_BUS` | `inproc` | `inproc` or `pubsub` |
| `ACC_AGENT_MODE` | `deterministic` | `adk`, `hybrid`, `deterministic` |
| `ACC_MODEL_ARMOR` | `heuristic` | `off`, `heuristic`, `gcp` |
| `GEMINI_MODEL` | `gemini-3.6-flash` | Contest requires 3.5 or newer |
| `GEMINI_MODEL_REASONING` | *(empty)* | Failure Twin model; empty = same as above |
| `POLICY_PURCHASE_AUTONOMOUS_MAX` | `5000` | Autonomous action ceiling |
| `POLICY_PURCHASE_APPROVAL_MAX` | `25000` | Above this: hard denial |

Tests are hermetic against your `.env`: a local file cannot change policy
thresholds or Model Armor mode during the suite.

---

## API

| Method | Route | Purpose |
|---|---|---|
| `POST` | `/api/v1/missions` | Create and start a mission |
| `GET` | `/api/v1/missions/{id}` | Full state + metrics |
| `GET` | `/api/v1/missions/{id}/timeline` | Event feed |
| `GET` | `/api/v1/missions/{id}/trace` | Structured reasoning tree |
| `GET` | `/api/v1/missions/{id}/evidence` | Explainability: options, rejected ones, why |
| `GET` | `/api/v1/missions/{id}/stream` | Live SSE stream |
| `POST` | `/api/v1/missions/{id}/resume` | Resume from checkpoint |
| `GET` | `/api/v1/approvals?status=PENDING` | Approval queue |
| `POST` | `/api/v1/approvals/{id}/approve` | Human decision |
| `GET` | `/api/v1/policy` | Autonomy boundary (authenticated) |
| `GET` | `/api/v1/metrics` | Mission Continuity Rate and fleet health |
| `POST` | `/api/v1/demo/*` | Deterministic failure injection (disabled in production) |

---

## Mission Control

Four views, no more: **Mission**, **Timeline**, **Recovery**, **Trace**, plus
the approval modal.

The Recovery panel is the one that sells the product: it shows not only the
selected option but the **rejected** ones and why. That is the visual proof of
"best operational option ≠ best permitted option".

The frontend is never the source of truth: SSE for responsiveness, but every
event triggers a re-read of authoritative control-plane state. If the stream
drops, it falls back to polling on its own.

---

## Deployment

```
python scripts/deploy.py --project-id my-project   # detail: DEPLOYMENT.md
```

Works identically on Windows, macOS and Linux — no bash required.

Cost tracking and teardown:

```
make plan       # terraform plan, no image built
make deploy     # three images + terraform apply
make costs      # budget, scaling guardrails, volumetry
make teardown   # brings billing back to zero
```

Cloud Run **scales to zero** with a hard instance ceiling, Firestore as the
source of truth, Pub/Sub for asynchronous continuation, Secret Manager for
secrets, dedicated least-privilege service accounts, no service keys generated.

**Measured cost: ~0.07 $ per hero mission** with `gemini-3.6-flash`
(7 model calls, ~700 input tokens each). Firestore writes (86 documents per
hero mission) and Cloud Run stay inside the free tiers.

---

## Verification

| Check | Result |
|---|---|
| Python test suite | 431 tests green |
| Functional coverage audit | 70/70 requirements linked to a real test |
| Strict TypeScript typecheck | 0 errors |
| Next.js production build | compiles, 103 kB shared JS |
| npm audit | 0 vulnerabilities |
| Hero scenario, single process | complete |
| Hero scenario over real HTTP (2 services) | complete, SSE included |
| Test suite **without** the Google SDK | 431 tests green |

```bash
make audit   # links every blueprint requirement to an existing pytest node id
```

`scripts/audit_coverage.py` fails if a referenced test disappears: you cannot
tick a box by renaming a test. It runs in CI.

The demo script is under test too: amounts, thresholds, option counts and UI
labels are compared against real behaviour.

The ADK path is tested with a faithful Runner double
(`tests/integration/test_adk_path.py`): parsing, timeout, fallback, prompt
sanitisation. **It has not yet run against a live Gemini endpoint** — that is
the one remaining blind spot.

---

## What the code proves

- The mission survives runtime death — state lives in the store, not the process
- Recovery is governed like any other action
- The best operational option is rejected when it is not permitted
- An approval is durable state, not a UI session
- Hostile external content never redefines authority
- A resumable agent never orders twice
- Switching agent mode (`adk` / `hybrid` / `deterministic`) changes **nothing** about governance
- A duplicated Pub/Sub delivery never runs the same agent twice
- A suspended agent produces a traced safe hold, never a silent freeze
- Mission risk does not drop just because a fallback is rated "medium"
- A terminal mission leaves nothing "in progress"
- ACC stops asking the same question when nothing has changed

---

## Design decisions

`docs/ARCHITECTURE.md` records 69 numbered ADRs, including the bugs found by
running the system rather than reading it — a Pub/Sub race condition that the
in-memory store hid, an idempotency cache that made recovery structurally
impossible, and a mission deadlock after an approved escalation.
