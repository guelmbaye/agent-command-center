# Demo script — 4 minutes

The judges must remember **one** story.
*A mission failed. ACC recovered it, without ever stepping outside its limits.*

> **Every figure and every sequence in this script is verified by execution**
> against the real API, in `deterministic` mode. The claims are covered by
> `tests/scenarios/test_demo_script.py`.

---

## Contest video requirements

From the official rules — these are scored, not optional:

| Requirement | How this script satisfies it |
|---|---|
| **Maximum 4 minutes** (only the first 4 are evaluated) | Timings below total 3:50 |
| **Must show the backend running on Google Cloud** | Segment at 3:20 — Cloud Run dashboard + `.run.app` URL |
| Short overview of the **problem** | 0:00 – 0:20 |
| The **value proposition** | 0:00 – 0:20 and closing |
| A **demo of the application in action** | 0:20 – 3:20 |
| Must be **in English** or carry English subtitles | Narration below is in English |
| Live, unedited execution (terminal logs, DB updates, UI changes) | The timeline updates live on screen |

Public on YouTube or Vimeo, link on the submission form.

---

## The trap to know first

**A nominal mission completes in 0.3 seconds.**

Direct consequence: **everything must be armed BEFORE launching the mission.**

| Mistake | What actually happens |
|---|---|
| Injecting the failure *after* launch | No effect — the mission is already `COMPLETED` |
| Arming the hostile injection *mid-flight* | **0 threats detected** — supplier reads are already done |
| Arming the hostile injection *before* launch | **3 threats blocked**, visible in the timeline |

The order is always: **reset → arm → launch → decide**.

---

## Preparation

```bash
make run-mock      # simulated enterprise systems  → :8081
make run           # ACC control plane             → :8080
make web           # Mission Control               → :3000
make doctor        # checks that everything talks to everything
```

In Mission Control, **Demo controls** panel:

1. **Reset**
2. **Fail SUP-A**
3. *(optional)* **Hostile injection**

Only then: **New mission** → the form opens → keep the defaults
(1 200 u., 48 h) → **Launch mission**.

Three safety nets: live execution, `ACC_AGENT_MODE=deterministic` (no model
calls at all), and the recorded fallback.

Have a second browser tab already open on the **Google Cloud Run dashboard** —
you will need it at 3:20 without fumbling.

---

## 0:00 — 0:20 · Opening

> "Enterprise agents can execute tasks. But what happens when the environment
> changes underneath them? An agent stuck at 60 % of a procurement workflow is
> a stopped production line."

The failure is already armed. Open the **New mission** form and show that it
announces the verdict **before** launching:

> *"4 800 $ within autonomous authority → no intervention"*

> "Look: the system already knows what it is allowed to do on its own."

Click **Launch mission**.

---

## 0:20 — 0:50 · Failure, immediately

No calm phase: SUP-A is already down. The timeline chains within a second:

```
Supply Agent activated
Policy: supplier.status → ALLOW
supply-agent failed: Supplier SUP-A status unreachable: HTTP 503
Mission at risk: objective threatened
Failure Twin activated on SUP-A
```

> "This is exactly where agent workflows usually stop. ACC treats failure as an
> operational state, not as the end of the mission."

**Worth pointing out**: the Supply Agent stays **AVAILABLE** in the fleet panel.
It did its job perfectly — detect and report the outage. The supplier is at
fault, not the agent.

---

## 0:50 — 1:45 · The moment that sells the product

Open the **Recovery** tab.

**Five options evaluated, two ruled out:**

| Option | Verdict |
|---|---|
| Retry SUP-A | **not permitted** — DEPENDENCY class: retrying would reproduce the failure |
| Switch to SUP-B | **permitted** — selected |
| Switch to SUP-C | **not permitted** — lead time 60 h > 48 h deadline |
| Wait and reassess | permitted |
| Escalate to the operator | permitted |

> "SUP-C is cheaper — 11 $ a unit against 15 — and lower risk. It is the best
> **operational** option. It is ruled out because it misses the deadline. ACC
> does not select the best option: it selects the best **permitted** option."

Show the footer line: *this plan itself passed through the Policy Engine ·
POL-xxx*.

> "And recovery is not above the rules. The plan goes back through the same
> policy, the same identity and the same audit as any ordinary agent action."

---

## 1:45 — 2:15 · The authority boundary

The approval modal appears: **18 000 $**.

> "The fallback costs 18 000 $. The autonomy threshold is 5 000. The mission
> stops by itself and asks a human. This is not decorative caution: the form
> announced 4 800 $ a moment ago, with no intervention. It is the disruption
> that pushed the mission past the boundary."

**If the hostile injection was armed**, open the **Timeline** tab and show the
three lines:

```
⛨  Untrusted instruction blocked (suppliers)
```

> "The supplier was telling us to ignore the policy and skip the approval.
> Model Armor blocked the instruction, the mission carried on — and the
> approval is still there. External content does not redefine authority."

---

## 2:15 — 2:45 · The durability proof

Click **Kill the runtime**, then **Resume**.

> "The runtime disappears. Mission state lives outside the process — in memory
> here, in Firestore once deployed. On resume: context is restored, the
> approval is **still pending**, and no completed task is replayed."

Verified: after resume the status stays `WAITING_APPROVAL` and the approval
survives.

Approve.

The mission turns **COMPLETED**, purchase order issued (`PO-88xx`).

---

## 2:45 — 3:20 · The evidence

Open the **Trace** tab.

> "Every consequential decision is traceable: what failed, why this recovery,
> who authorised it, what actually executed."

Metrics bar — the exact interface labels:

| Indicator | Expected value |
|---|---|
| Mission continuity | **100 %** · 1 mission disrupted |
| Missions | 1/1 |
| Policy violations | **0** |
| Duplicates prevented | 0 |

---

## 3:20 — 3:40 · Proof it runs on Google Cloud

**Required by the rules.** Switch to the second tab and show, in this order:

1. **Cloud Run dashboard** — the three services `acc-api`, `acc-web`,
   `acc-mock-enterprise`, green, with their revisions
2. The **`.run.app` URL** in the address bar of the running Mission Control
3. *(if time allows)* **Cloud Logging**, filtered on
   `jsonPayload.mission_id="MIS-1001"` — the structured JSON logs of the very
   mission just demonstrated

> "Everything you have just seen runs on Cloud Run, with Firestore as the
> durable source of truth and Pub/Sub for asynchronous continuation. The
> compute can disappear. The mission cannot."

---

## 3:40 — 3:50 · Closing

> "ACC does not try to make agents perfect. It makes enterprise missions
> resilient."

**The agent can fail. The mission doesn't have to.**

---

## Variant — governance with no failure at all

The creation form alone crosses the authority boundary. Useful if a judge asks
"and without a failure?":

| Volume | Amount | What happens |
|---|---|---|
| 1 200 u | 4 800 $ | Below threshold → the mission completes on its own |
| 1 500 u | 6 000 $ | Above threshold → **human approval** |
| 1 601 u + | — | SUP-A capacity (1 500) exceeded → **Failure Twin** |

---

## Variant — ACC's lucidity

Volume ≥ 1 601 u., **without** injecting a failure. No supplier can deliver.

1. The Failure Twin escalates to the operator
2. Approve
3. The retry fails identically
4. ACC **notices that nothing changed** and aborts, with its reason:

> *"Already escalated 1 time(s) with an identical state. Nothing changed in the
> environment: a new attempt would fail the same way."*

> "Knowing how to say 'I can do nothing more, and here is why' is part of
> resilience. A system that endlessly re-asks for the same authorisation
> creates the illusion of progress."

Also worth noting: **ACC does not ask for approval to abort.**
`recovery.abort → ALLOW`. You authorise an action, not an abstention.

**Do not open with this variant** — it ends in failure. It is a second act, not
an overture.

---

## What NOT to do

- **Inject the failure after launching the mission** — no effect
- **Arm the hostile injection mid-flight** — zero threats detected
- Chain several nominal missions: visually identical, finished instantly
- Click **Kill the runtime** or **Resume** on a finished mission: the buttons
  are disabled, with a "nothing left to interrupt" note
- Show agents "chatting"
- Open infrastructure screens beyond the required Cloud Run proof
- Explain the architecture before showing failure and recovery
- Exceed 4 minutes — only the first 4 are evaluated

---

## Cold rehearsal

```bash
python scripts/run_hero_scenario.py
```

Runs the complete scenario in a single process, no server and no browser:
16 checks, including the final assertion that **exactly one** purchase order
was issued on the enterprise side.
