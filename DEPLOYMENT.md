# ACC — Deployment guide

From the archive to a Google Cloud deployment, with cost control.

> **Read this first.** None of the Google Cloud steps below were executed from
> the environment where this project was built: no GCP project, no Docker, no
> browser were available. The code itself is verified by execution (277 tests,
> 69/69 audit, hero scenario over real HTTP). The commands below come from
> Google documentation checked in August 2026 — but **you will be the first to
> run them**. Known traps are flagged.

---

## Contents

1. [Local verification — 2 minutes, no cloud](#1-local-verification)
2. [Full local stack](#2-full-local-stack)
3. [Google Cloud — project setup](#3-google-cloud--project-setup)
4. [Budget and guardrails — **do this before anything else**](#4-budget-and-guardrails)
5. [Enabling APIs](#5-enabling-apis)
6. [Firestore](#6-firestore)
7. [Vertex AI and Gemini](#7-vertex-ai-and-gemini)
8. [Model Armor](#8-model-armor)
9. [Secrets](#9-secrets)
10. [Deployment](#10-deployment)
11. [Verifying the deployment](#11-verifying-the-deployment)
12. [Day-to-day cost tracking](#12-day-to-day-cost-tracking)
13. [Teardown](#13-teardown)
14. [Troubleshooting](#14-troubleshooting)

---

## 1. Local verification

No keys, no cloud, no network.

```bash
unzip acc-autonomous-mission-control.zip && cd acc
pip install -r requirements.txt

pytest -q                              # 277 tests
python scripts/audit_coverage.py       # 69/69 requirements linked to a real test
python scripts/run_hero_scenario.py    # full hero scenario, single process
```

The suite is hermetic against your `.env`: a local file cannot change policy
thresholds or Model Armor mode during the run. It also passes **without**
`google-adk` installed — a dedicated CI job proves it.

`deterministic` mode makes no model calls **but still traverses the Agent
Gateway**: policy, idempotency and audit are exercised identically.

---

## 2. Full local stack

```bash
make run-mock      # simulated enterprise systems  → :8081
make run           # ACC control plane             → :8080/docs
make web-install   # once (npm install)
make web           # Mission Control               → :3000
make doctor        # checks that everything talks to everything
```

Port 8080 is heavily contested — llama.cpp, XAMPP and Tomcat all default to it.
Everything is overridable:

```bash
make run PORT=8099
make web ACC_API=http://127.0.0.1:8099
make doctor PORT=8099
```

### Windows notes

Every `make` target goes through `scripts/dev.py`: no POSIX shell syntax is
used, so `make run` behaves identically on Windows, macOS and Linux.

| Point | Detail |
|---|---|
| Interpreter | `make run PY=python3` if `python` is not on the PATH |
| `npm` | Resolved via `shutil.which` — finds `npm.cmd` on Windows |
| Deployment scripts | All Python — `make deploy`, `make costs`, `make teardown` run natively in PowerShell |
| Environment variables | `$env:PROJECT_ID = "..."` in PowerShell, not `export` |
| Virtual environment | `dev.py` uses `sys.executable`, so the active venv is respected |
| API key | `ACC_API_KEY` in the backend `.env` is enough — `make web` propagates it |

To test Gemini locally without Vertex AI:

```bash
export GOOGLE_GENAI_USE_VERTEXAI=0
export GOOGLE_API_KEY="your-AI-Studio-key"
export ACC_AGENT_MODE=hybrid
make run
```

> **Never executed here**: Docker was unavailable. The Dockerfiles are written
> but were never built. Run `make stack` once before relying on it.

---

## 3. Google Cloud — project setup

> **Windows / PowerShell.** `export` is a bash command; PowerShell uses
> `$env:`. Every deployment script is now Python, so **no bash is required** —
> `make deploy`, `make costs` and `make teardown` work natively in PowerShell.

**PowerShell**

```powershell
$env:PROJECT_ID      = "acc-hackathon-2026"   # must be globally unique
$env:REGION          = "europe-west1"         # Belgium — see note below
$env:BILLING_ACCOUNT = "0X0X0X-0X0X0X-0X0X0X"

gcloud auth login
gcloud projects create $env:PROJECT_ID
gcloud billing projects link $env:PROJECT_ID --billing-account=$env:BILLING_ACCOUNT
gcloud config set project $env:PROJECT_ID
gcloud config set run/region $env:REGION

# Application Default Credentials — REQUIRED, and separate from the CLI login
gcloud auth application-default login
gcloud auth application-default set-quota-project $env:PROJECT_ID
```

**bash / zsh**

```bash
export PROJECT_ID="acc-hackathon-2026"
export REGION="europe-west1"
export BILLING_ACCOUNT="0X0X0X-0X0X0X-0X0X0X"

gcloud auth login
gcloud projects create "${PROJECT_ID}"
gcloud billing projects link "${PROJECT_ID}" --billing-account="${BILLING_ACCOUNT}"
gcloud config set project "${PROJECT_ID}"
gcloud config set run/region "${REGION}"

# Application Default Credentials — REQUIRED, and separate from the CLI login
gcloud auth application-default login
gcloud auth application-default set-quota-project "${PROJECT_ID}"
```

> **`gcloud auth login` is not enough.** It authenticates the CLI. Terraform's
> Google provider and the Vertex AI SDK both read **Application Default
> Credentials**, a separate file. Without ADC, `terraform apply` fails — and it
> fails *after* the images have been built and pushed, the most expensive
> moment to discover a missing credential.
>
> `make deploy` therefore checks ADC **before** building anything, and stops on
> a quota project mismatch. That mismatch is exactly what this warning means:
>
> ```
> WARNING: Your active project does not match the quota project in your local
> Application Default Credentials file.
> ```
>
> It does not block Terraform, but it produces **403 PERMISSION_DENIED on
> Vertex AI** — during the demo, after everything looked fine.

You can also skip the variables entirely and pass the project explicitly:

```
python scripts/deploy.py --project-id acc-hackathon-2026 --region europe-west1
```

### Why `europe-west1`

It is one of the few regions where **all four critical services coexist**:
Cloud Run, Firestore, Vertex AI (Gemini) and Model Armor. Model Armor is
available in `europe-west1` (Belgium), `europe-west2` (London), `europe-west3`
(Frankfurt), `europe-west4` (Netherlands), plus the US regions.

If you change region, **check Model Armor first** — it has the narrowest
coverage: <https://docs.cloud.google.com/model-armor/locations>

To find your billing account id:

```bash
gcloud billing accounts list
```

---

## 4. Budget and guardrails

### With 150 $ of credits

**The demo cost is not the risk.** Figures measured from the code, at Vertex AI
prices verified in August 2026:

| Item | Real measurement | Cost |
|---|---|---|
| Model calls | 7 per hero mission, ~700 input tokens each | **~0.07 $ per mission** |
| Firestore writes | 86 documents per hero mission | free tier: 20 000/day |
| Cloud Run | scale to zero, 3 services | free tier: 2 M requests/month |
| Model Armor | 2 scans per agent call | per-call, negligible volume |

**1 000 demo missions would cost roughly 70 $.** A realistic demo run is a few
dozen missions — a couple of dollars.

**The real risk is forgotten resources:**

| Risk | Protection in place |
|---|---|
| Services left running after the hackathon | `make teardown` — run it on submission day |
| `min_instance_count > 0` (bills while idle) | Set to 0, verified by test |
| Runaway recovery loop | Attempt budget + circuit breaker |
| Expensive "Pro" model enabled by accident | `GEMINI_MODEL_REASONING` empty by default, verified by test |
| Artifact Registry images piling up | Survive `destroy` — see §13 |
| Hourly-billing resource (GKE, Cloud SQL, Vertex endpoint) | None in the Terraform, verified by test |

**Recommended budget: 40 $** — a quarter of the credits. Wide enough never to
get in the way, tight enough to warn you before an oversight gets expensive.

### Which model to use

**Mandatory contest requirement: Gemini 3.5 or newer.** This overrides cost
optimisation — a 3.1 model, even cheaper and technically sufficient, would fail
the pass/fail compliance check.

**Default in this project: `gemini-3.6-flash`** — newer than 3.5 *and* cheaper,
thanks to introductory pricing through 31 December 2026.

Cost per hero mission, computed from measured volumetry (7 calls, ~700 input
tokens, ~350 visible output tokens), extrapolated to 1 000 missions:

| Model | 1 000 missions | Compliant | Retirement |
|---|---|---|---|
| **`gemini-3.6-flash`** | **~68 $** | ✅ | — (promo until 31/12/26) |
| `gemini-3.5-flash` | ~162 $ | ✅ | — |
| `gemini-3.1-flash-lite` | ~12 $ | ❌ **below 3.5** | — |
| `gemini-2.5-flash` | ~8 $ | ❌ **below 3.5** | 16 October 2026 |
| `gemini-3.1-pro` | ~245 $ | ❌ **below 3.5** | — |

The gap comes from **thinking tokens** in 3.x models, billed as output. The
multiplier is a documented estimate (×5 to ×10), not a measurement: these
models could not be called from the build environment.

> **Why a light model is the right answer here.** ACC does not ask the model to
> *decide*: policy, idempotency, authority and traceability live in the
> platform. The model produces a structured finding that goes back through the
> Mission Engine. A frontier model would add nothing to this architecture — and
> saying so to the judges is an argument, not an admission.

> **Good news for migration.** `temperature`, `top_p` and `top_k` have been
> deprecated since 21 July 2026 and are the usual blocker when switching
> models. ACC sets none of them: changing model is one environment variable.
> Verified by test.

**Still check the model answers in your region before deploying** (§7).

### Creating the budget

**Do this before enabling a single API.** A budget does not block spending — it
warns you. That is the difference between finding out in two hours or on next
month's invoice.

```bash
gcloud billing budgets create \
  --billing-account="${BILLING_ACCOUNT}" \
  --display-name="ACC hackathon" \
  --budget-amount=40USD \
  --filter-projects="projects/${PROJECT_ID}" \
  --threshold-rule=percent=0.5 \
  --threshold-rule=percent=0.9 \
  --threshold-rule=percent=1.0 \
  --threshold-rule=percent=1.5
```

Thresholds are base 1.0 (`0.5` = 50 %). The 150 % rule catches spending that
**continues** after the overrun — the scenario that actually hurts.

### Guardrails already in the code

| Guardrail | Where | Effect |
|---|---|---|
| `min_instance_count = 0` | `cloud_run.tf` | No cost while idle |
| `max_instance_count = 4` | `var.max_instances_api` | Hard ceiling on spikes |
| `ACC_AGENT_MODE=deterministic` | env var | Zero model calls |
| `GEMINI_MODEL_REASONING` empty | `config.py` | No surprise "Pro" model |
| `acc_agent_timeout_s = 25` | `config.py` | No model call left hanging |
| `max_attempts = 3` | `domain/models.py` | Bounded recovery loop |
| Circuit breaker | `enterprise_tools.py` | Stops repeated failing calls |
| `app=acc` labels | all Cloud Run resources | Billing breakdown |

These are verified by `tests/unit/test_cost_guardrails.py`: a
`min_instance_count > 0`, or adding an hourly-billing resource, fails CI.

---

## 5. Enabling APIs

```bash
gcloud services enable \
  run.googleapis.com \
  firestore.googleapis.com \
  pubsub.googleapis.com \
  aiplatform.googleapis.com \
  secretmanager.googleapis.com \
  artifactregistry.googleapis.com \
  cloudbuild.googleapis.com \
  compute.googleapis.com \
  cloudtrace.googleapis.com \
  logging.googleapis.com \
  monitoring.googleapis.com \
  modelarmor.googleapis.com \
  iam.googleapis.com \
  --project="${PROJECT_ID}"
```

Allow 2–3 minutes for propagation. A `terraform apply` launched too early fails
with `API not enabled` — just run it again.

**Or let the deployment handle it.** It enables whatever is missing, waits for
the service accounts to be provisioned, then continues:

```
make deploy ARGS=--enable-apis
```

Enabling an API is free and idempotent — only usage bills.

> **Why `compute.googleapis.com` is in this list.** ACC runs no virtual
> machine. But Cloud Build changed its default: on projects where the API was
> enabled after that change, builds run as the **Compute Engine default service
> account** — which only exists once the Compute API is enabled. Without it,
> `gcloud builds submit` fails with:
>
> ```
> PERMISSION_DENIED: Permission 'iam.serviceAccounts.get' denied on resource
> (or it may not exist)
> ```
>
> That reads like a permissions problem and is in fact a missing API.
>
> **And once the API is on, a second wall follows.** Recent projects no longer
> grant Editor to default service accounts, so that account holds **no role at
> all**. The next failure is:
>
> ```
> 403: ...-compute@developer.gserviceaccount.com does not have
> storage.objects.get access to the ..._cloudbuild bucket
> ```
>
> Grant it the documented build role once:
>
> ```powershell
> $env:NUMBER = gcloud projects describe $env:PROJECT_ID --format="value(projectNumber)"
> gcloud projects add-iam-policy-binding $env:PROJECT_ID `
>   --member="serviceAccount:$env:NUMBER-compute@developer.gserviceaccount.com" `
>   --role="roles/cloudbuild.builds.builder"
> ```
>
> `make deploy` checks **both** conditions before launching any build, and
> reports every missing prerequisite at once rather than one per attempt.

**PowerShell** — same list, one line:

```powershell
gcloud services enable run.googleapis.com firestore.googleapis.com `
  pubsub.googleapis.com aiplatform.googleapis.com secretmanager.googleapis.com `
  artifactregistry.googleapis.com cloudbuild.googleapis.com compute.googleapis.com `
  cloudtrace.googleapis.com logging.googleapis.com monitoring.googleapis.com `
  modelarmor.googleapis.com iam.googleapis.com --project=$env:PROJECT_ID
```

---

## 6. Firestore

**The most common trap on a first `terraform apply`.**

Terraform tries to create the `(default)` database. If the project already has
one (created by another tool, or by Firebase), the apply fails with
`ALREADY_EXISTS`.

Check first:

```bash
gcloud firestore databases list --project="${PROJECT_ID}"
```

**If the list is empty** → do nothing, Terraform will create it.

**If `(default)` already exists** → import it instead of recreating:

```bash
cd infrastructure/terraform
terraform init
terraform import google_firestore_database.acc \
  "projects/${PROJECT_ID}/databases/(default)"
```

Make sure it is in **Native** mode (not Datastore): ACC uses sub-collections and
transactions that Datastore mode does not serve the same way.

### Composite indexes

Two indexes are declared in `firestore.tf` (`approvals_index`, `missions`).
They take a few minutes to build after the apply. Until they are ready,
`GET /api/v1/approvals?status=PENDING` may return `FAILED_PRECONDITION` with a
direct creation link — that is normal.

---

## 7. Vertex AI and Gemini

Check the model answers in your region before deploying:

```bash
curl -X POST \
  -H "Authorization: Bearer $(gcloud auth print-access-token)" \
  -H "Content-Type: application/json" \
  "https://${REGION}-aiplatform.googleapis.com/v1/projects/${PROJECT_ID}/locations/${REGION}/publishers/google/models/gemini-3.6-flash:generateContent" \
  -d '{"contents":[{"role":"user","parts":[{"text":"Reply with exactly: OK"}]}]}'
```

**If the model does not exist** (HTTP 404), list what is available:

```bash
gcloud ai models list --region="${REGION}" --project="${PROJECT_ID}"
```

then adjust `GEMINI_MODEL` (`var.gemini_model` in Terraform). **Keep 3.5 or
newer** — a lower version fails the contest compliance check, and a test
enforces it.

### The one path never executed here

`tests/integration/test_adk_path.py` covers parsing, timeout, fallback and
sanitisation with a faithful Runner double, and the four agents build against
real ADK 2.7 with correct tool schemas. **But no call has ever reached a Gemini
endpoint.**

A ten-minute check:

```bash
export ACC_AGENT_MODE=hybrid
export GOOGLE_GENAI_USE_VERTEXAI=1
export GOOGLE_CLOUD_PROJECT="${PROJECT_ID}"
export VERTEX_AI_LOCATION="${REGION}"
make run-mock &
make run
# then: ACC_URL=http://localhost:8080 ./scripts/demo_walkthrough.sh
```

In `hybrid` mode, a model failure falls back to the deterministic path
automatically — the demo holds even if Gemini refuses.

---

## 8. Model Armor

### Regional endpoint

```bash
gcloud config set api_endpoint_overrides/modelarmor \
  "https://modelarmor.${REGION}.rep.googleapis.com/"
```

### Creating the template

```bash
gcloud model-armor templates create acc-guardrails \
  --location="${REGION}" \
  --project="${PROJECT_ID}" \
  --pi-and-jailbreak-filter-settings-enforcement=enabled \
  --pi-and-jailbreak-filter-settings-confidence-level=medium-and-above \
  --malicious-uri-filter-settings-enforcement=enabled \
  --basic-config-filter-enforcement=enabled \
  --template-metadata-log-sanitize-operations
```

The **prompt injection / jailbreak** filter is what carries ACC's security
demonstration. `medium-and-above` is the right trade-off: `high` would let the
demo payload through, `low-and-above` would produce false positives on stage.

Get the full name and put it in `MODEL_ARMOR_TEMPLATE`, with
`ACC_MODEL_ARMOR=gcp`:

```bash
gcloud model-armor templates list --location="${REGION}" --project="${PROJECT_ID}"
# → projects/PROJECT_ID/locations/REGION/templates/acc-guardrails
```

### IAM

The control-plane service account needs `roles/modelarmor.user`. It is declared
in `iam.tf` (`local.api_roles`), so Terraform grants it automatically. The
command below is only a catch-up if you deployed before that fix:

```bash
gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
  --member="serviceAccount:acc-api@${PROJECT_ID}.iam.gserviceaccount.com" \
  --role="roles/modelarmor.user"
```

### ⚠ Calendar trap

Model Armor templates on the **Stable** alias switch automatically to **filter
v3 on 31 August 2026** — the submission deadline itself. A template created
today may therefore change behaviour during the submission window.

Two protections:

1. Test the injection scenario **after** 31 August if you demo live
2. Keep `ACC_MODEL_ARMOR=heuristic` as a net — the local detector is
   deterministic and covers the demo payload (`tests/unit/test_model_armor.py`)

---

## 9. Secrets

**Nothing to do.** Terraform generates the two secrets and their versions:

| Secret | Purpose |
|---|---|
| `acc-api-key` | Protects the public Cloud Run URL |
| `acc-pubsub-push-token` | Authenticates Pub/Sub push |

Values are generated by `random_password`, stored in Secret Manager and mounted
into Cloud Run at runtime. They never appear in the repository, in an image, in
a prompt, or in a Terraform output.

> **Why not manual.** An earlier version asked you to create them with
> `openssl rand`. Terraform created only the secret *containers*, so a secret
> with no version had no `latest` and every Cloud Run revision failed with
> `Secret .../versions/latest was not found`. A manual prerequisite is a
> prerequisite that gets skipped — and `openssl` is not in a default
> PowerShell.

To read the generated key back:

```
gcloud secrets versions access latest --secret=acc-api-key --project=$env:PROJECT_ID
```

`terraform output acc_api_key_command` prints that same command.

## 10. Deployment

Works identically on Windows, macOS and Linux — no bash required:

```
python scripts/deploy.py --project-id my-project
```

or, once `PROJECT_ID` is set in the environment:

```
make deploy
```

The script runs in this order:

1. **Preflight** — credentials, APIs, build identity and its role
2. **Artifact Registry** — a targeted `terraform apply` creates the repository
   *before* anything is built, otherwise the push fails on
   `name unknown: Repository "acc" not found`
3. **Three images** — api, mock and web, built through Cloud Build under a
   per-deployment tag (`:20260829-130452`). `:latest` alone would be the same
   string every time, so Terraform would see no change and never roll out what
   was just pushed
4. **Full apply** — Firestore, IAM, secrets **and their versions**, Pub/Sub,
   Cloud Run

Terraform remains the single source of truth: the targeted apply in step 2 is a
no-op when the full apply runs.

Dry run first — no image is built:

```
make plan
# or: python scripts/deploy.py --project-id my-project --plan-only
```

To reuse images already pushed:

```
python scripts/deploy.py --project-id my-project --skip-build
```

> **`--skip-build` does not rebuild Mission Control.** `NEXT_PUBLIC_ACC_API` is
> inlined at build time, so skipping the build preserves whatever the previous
> image was compiled with — including an empty value. If the frontend queries
> its own origin, run a **full** `make deploy`. The script warns about this.

If a previous apply failed halfway and left a service in a broken state:

```
make deploy ARGS="--repair --skip-build"
```

`--repair` handles the two ways a failed apply leaves a service stuck:

- **Tainted** — Terraform wants to replace it, and the replacement is blocked
  by `deletion_protection`. Untainting lets the next apply update it in place.
- **Revision permanently dead** — a Cloud Run revision that failed to start
  never retries, so updating in place keeps reporting the same broken revision.
  The service is deleted and removed from state, and the next apply recreates
  it against an environment that is now correct.

Healthy services are left untouched.

The Terraform was statically validated (23 resources, all cross-references
resolve, cost guardrails present) but **never applied**.

### Known first-apply traps

| Symptom | Cause | Fix |
|---|---|---|
| `ALREADY_EXISTS` on Firestore | pre-existing `(default)` database | `terraform import` (§6) |
| `API not enabled` | propagation in flight | wait 2 min, re-run |
| `Permission denied` on IAM | IAM propagation | re-run the apply |
| `Secret version not found` | secrets not created | do §9 first |
| Pub/Sub push returns 403 | missing token | check `acc-pubsub-push-token` |
| `terraform destroy` blocked | Firestore protection | `make teardown` |

IAM propagation frequently makes the **first** apply fail and the second
succeed. That is not a configuration error.

---

## 11. Verifying the deployment

```bash
cd infrastructure/terraform
export ACC_URL=$(terraform output -raw acc_api_url)
export WEB_URL=$(terraform output -raw acc_web_url)
export ACC_API_KEY=$(gcloud secrets versions access latest --secret=acc-api-key)
cd ../..

curl -fsS "${ACC_URL}/healthz" | python3 -m json.tool
```

In cloud mode `/healthz` stays minimal on purpose — it must remain open to
Cloud Run probes, so it does not describe the service posture. Expect
`{"status":"ok","service":"acc-api","env":"demo"}`.

Then run the full scenario against the deployed instance:

```bash
./scripts/demo_walkthrough.sh
```

And open `${WEB_URL}` in a browser.

**How to confirm the frontend is wired correctly.** Open the deployed Mission
Control, then the browser network tab. Every call must go to
`https://acc-api-...`. A call to `https://acc-web-.../api/v1/...` means the web
image was built without the URL — run a full `make deploy`.

> **On the first deployment, Mission Control derives the API URL from its own
> origin** — `acc-web-…` becomes `acc-api-…`, since both services share the same
> Cloud Run suffix. Running `make deploy` a second time bakes the real value in
> as a build argument. Both paths work; the second is explicit.

> **The one deliverable never observed.** Mission Control is strictly typed,
> builds cleanly and is wired to the real API, but it was never seen rendered
> from the build environment. Layout, projection contrast and live-stream
> behaviour are yours to validate.

**Keep this tab.** The contest rules require the video to show the backend
running on Google Cloud — the Cloud Run dashboard and the `.run.app` URL are
exactly that proof. See `docs/DEMO_SCRIPT.md`, segment 3:20.

---

## 12. Day-to-day cost tracking

```
make costs
# or: python scripts/costs.py --project-id my-project
```

It reports: budget and thresholds, scaling guardrails per service (and warns if
a `min_instance_count > 0` is lingering), Firestore volumetry, and links to
filtered billing reports.

### Where the money actually goes

By risk, not by amount:

| Item | What drives the cost | Risk |
|---|---|---|
| **Vertex AI / Gemini** | tokens × calls | **High** — ~7 calls per mission in `hybrid`; an unbounded retry loop is the expensive scenario |
| **Model Armor** | per sanitisation call | **Medium** — 2 per agent invocation |
| **Firestore** | document reads/writes | **Medium** — 86 documents per hero mission |
| **Cloud Run** | time × requests | **Low** — scales to zero |
| **Pub/Sub** | message volume | **Low** |
| **Artifact Registry** | image storage | **Low but persistent** — survives `terraform destroy` |
| **Cloud Logging** | ingested volume | **Low** — 50 GiB/month free |

### Billing breakdown by component

The `app=acc`, `environment` and `component` labels are set on every Cloud Run
resource by Terraform.

Console → Billing → Reports → **Group by: Label** → `app: acc`, then
**Group by: SKU** to isolate the Gemini and Model Armor share. Labels appear in
reports after roughly 24 hours of collection.

### Habits during the hackathon

- Switch back to `ACC_AGENT_MODE=deterministic` between rehearsals: zero tokens,
  governance still demonstrated
- Never raise `min_instance_count` above 0, even to avoid cold starts
- Run `make costs` once a day
- After submission: `make teardown` the same day

---

## 13. Teardown

```
make teardown
# or: python scripts/teardown.py --project-id my-project
```

The script first lifts Firestore delete protection (without which
`terraform destroy` fails), destroys the infrastructure, then lists what can
still bill.

Cloud Run services carry `deletion_protection = false` for the same reason:
provider v6 protects them by default, which would have made this teardown
impossible. Firestore keeps its protection — it holds mission state — and the
script removes it explicitly, in that order.

What **survives** a destroy: Artifact Registry images and retained logs. The
script prints the commands to remove them.

Absolute guarantee of zero:

```bash
gcloud projects delete "${PROJECT_ID}"
```

---

## 14. Troubleshooting

### Start here

```bash
make doctor          # or: python scripts/doctor.py
```

It identifies in one pass: port held by a third party, IPv6/IPv4 resolution,
missing API key, misconfigured `.env.local`, unreachable enterprise mock. Checks
cascade — one root cause produces one error line, not six.

### Port 8080 is taken: 404 on every `/api/v1/*` route

**Symptom.** The backend prints "Uvicorn running on http://127.0.0.1:8080"
without any error, yet Mission Control receives 404s that do not match the ACC
error contract.

**The Windows trap worth knowing.** On Windows, several processes can bind the
**same** address:port when `SO_EXCLUSIVEADDRUSE` is not set. Uvicorn therefore
reports "running" while another service receives the requests. On Linux the
second bind would fail with "Address already in use" — hence a problem invisible
in CI and very real on your machine.

```powershell
netstat -ano | findstr :8080
```

Three `LISTENING` lines on `127.0.0.1:8080` means three competing processes.

**Frequent squatters:**

| Service | Tell |
|---|---|
| **llama.cpp** | `Server: llama.cpp` — **its default port is 8080** |
| Apache / XAMPP | `Server: Apache/...` |
| Tomcat | `Server: Apache-Coyote` |
| IIS | `Server: Microsoft-IIS` |

`make doctor` reads the `Server` header and names the culprit directly, and
also reports multiple binds with the PIDs involved.

**Recommended fix — move ACC, not the other service:**

```bash
make run PORT=8099
make web ACC_API=http://127.0.0.1:8099
make doctor PORT=8099
```

**IPv4/IPv6 variant.** Uvicorn listens on IPv4 only. On Windows, `localhost`
resolves to IPv6 (`::1`) first: a third-party service bound to `[::1]:8080`
would capture the calls. The frontend client therefore defaults to `127.0.0.1`.

> **Always `127.0.0.1`, never `localhost`** in `NEXT_PUBLIC_ACC_API`.

**After changing `.env.local`, restart `make web`.** `NEXT_PUBLIC_*` variables
are frozen at build time, not read at runtime.

### 401 on every `/api/v1/*` route

**The trap**: an `ACC_API_KEY` environment variable takes precedence over the
`.env` file — **even if the line is commented out there**. A `cat .env` showing
`#ACC_API_KEY=` proves nothing.

```bash
make doctor        # names the source of the key and gives the exact command
```

The backend also logs it at startup:

```json
{"message": "api_key_enforced", "source": "environment",
 "hint": "... To remove it: PowerShell 'Remove-Item Env:ACC_API_KEY' ..."}
```

| Shell | Command |
|---|---|
| PowerShell | `Remove-Item Env:ACC_API_KEY` |
| cmd | `set ACC_API_KEY=` |
| bash / zsh | `unset ACC_API_KEY` |

**If you want to keep the key**, `make web` propagates it to the frontend
automatically — nothing else to do.

### Quick reference

| Symptom | Lead |
|---|---|
| `WARNING: active project does not match the quota project` | `gcloud auth application-default set-quota-project <project>`. Harmless for Terraform, but Vertex AI answers 403 |
| `could not find default credentials` on `terraform apply` | `gcloud auth application-default login` — the CLI login does not create ADC |
| `iam.serviceAccounts.get denied (or it may not exist)` on `builds submit` | `compute.googleapis.com` not enabled: the Cloud Build default identity does not exist. Enable it, wait 2 min, retry |
| `storage.objects.get denied` on the `_cloudbuild` bucket | The build service account holds no role. Grant `roles/cloudbuild.builds.builder` (§5) |
| `name unknown: Repository "acc" not found` on push | The registry did not exist at build time. `make deploy` now creates it first — re-run it |
| `Secret .../versions/latest was not found` | Terraform now generates the secret versions. Re-run `make deploy` |
| `Revision '...' is not ready` **after** the secrets exist | The revision predates the secrets and never retries. `make deploy ARGS="--repair --skip-build"` |
| `cannot destroy service without setting deletion_protection=false` **and it persists after re-running** | A failed apply left the service tainted: Terraform wants to replace it, the replacement is blocked, and the unblocking flag can only be applied by that same apply. Break the deadlock: `make deploy ARGS=--repair` |
| Missions stay in `EXECUTING` / `planning` with no agent activity | Pub/Sub push was rejected: the token must travel in the push URL query string, not a header (ADR-055). Re-run `make deploy` |
| Missions stay in `CREATED` once deployed | Pub/Sub push cannot mint its OIDC token. Terraform now grants `roles/iam.serviceAccountTokenCreator` to the Pub/Sub service agent — re-run `make deploy` if you deployed before that fix |
| `/healthz` says `persistence: memory` in production | `ACC_PERSISTENCE` not passed — check Cloud Run env vars |
| Missions stuck in `CREATED` | Pub/Sub push not arriving: check the subscription and OIDC token |
| Model Armor blocks nothing | Template not found → silent fallback to the heuristic. Check `MODEL_ARMOR_TEMPLATE` and `roles/modelarmor.user` |
| Agents permanently on deterministic fallback | Look for `adk_unavailable` / `agent_model_error` logs — usually a quota or a model missing from the region |
| `FAILED_PRECONDITION` on approvals | Firestore index still building (a few minutes) |
| Frontend shows nothing | `NEXT_PUBLIC_ACC_API` is frozen **at build time**: rebuild after changing the URL |
| Mission Control queries **its own origin** (`acc-web-.../api/v1/...` → 404) | The web image was built with an empty build argument. Re-run `make deploy`: the API URL is known now and gets baked in |
| Images pushed but the app does not change; apply says **"0 to add, N to change"** with only a `scaling` diff | The images carried `:latest`, so Terraform saw no change. Fixed by a per-deployment tag — re-run `make deploy` |
| Cloud Run answers **404 with an HTML page** on the FIRST call, then 200 | Cold start: the instance was scaled to zero. The diagnostic now retries; nothing to fix |
| Cloud Run answers 404 **after three retries** | The request really is not reaching the container. Compare `terraform output -raw acc_api_url` with `gcloud run services describe acc-api --region=REGION --format='value(status.url)'`, and read `status.conditions` |
| SSE never connects | Normal behind some proxies — the hook falls back to polling on its own |
| CORS error from Mission Control | Almost always another server on the port: `curl` ignores CORS, browsers do not. `make doctor` tests the preflight |
| CORS blocked once deployed | Run `python scripts/doctor.py --api <url>`: it now reproduces the browser preflight. If it reports **HTTP 404 with `Server: Google Frontend`**, the OPTIONS request never reached the container — the problem is at the Cloud Run edge, not in the app. Confirm with `gcloud run services logs read acc-api --region=REGION --limit=20`: no OPTIONS line means the request stopped before the container |
| `AttributeError: '_IncludedRouter'` on every request | FastAPI auto-instrumentation, removed in ADR-052. It crashed **before** the CORS middleware, so the browser reported a CORS failure. Re-deploy from a current archive |
| `Circuit open on demo` on a demo control | Fixed: operator controls are exempt from the breaker, which now also closes after 30 s (ADR-069). Re-deploy |
| `Tool failure suppliers: HTTP 404` once deployed | The enterprise mock had internal-only ingress and the client sent no identity token (ADR-057). Re-run `make deploy` |
| All missions go straight to recovery | The enterprise systems are not running: `make run-mock` in a second terminal |

### Reading the logs

```bash
gcloud run services logs read acc-api --region="${REGION}" --limit=50 \
  --project="${PROJECT_ID}"
```

All logs are structured JSON carrying `mission_id` and `trace_id`. To follow a
mission end to end:

```bash
gcloud logging read \
  'resource.type="cloud_run_revision" AND jsonPayload.mission_id="MIS-1001"' \
  --project="${PROJECT_ID}" --limit=100 --format=json
```

This command is also the third shot of the Google Cloud proof segment in the
demo video.

---

## Where to look first in the code

| File | What it proves |
|---|---|
| `docs/DEMO_SCRIPT.md` | Timed 4-minute run-through for the judges |
| `docs/ARCHITECTURE.md` | 37 ADRs, including the bugs found by audit |
| `apps/api/services/agent_gateway.py` | The non-bypassable pipeline |
| `agents/failure_twin/agent.py` | "Best option ≠ best permitted option" |
| `tests/integration/test_concurrency.py` | Why an in-memory test can lie |
| `scripts/audit_coverage.py` | 69 requirements → real tests |

---

## What is left to do

| # | Action | Time | Why it is risky |
|---|---|---|---|
| 0a | `gcloud auth application-default login` + `set-quota-project` (§3) | 2 min | Terraform and Vertex read ADC, not the CLI login |
| 0b | Check `gemini-3.6-flash` answers (§7) | 2 min | A model missing from the region blocks everything |
| 1 | 40 $ budget (§4) | 5 min | No safety net without it |
| 2 | `make plan` then `make deploy` (§10) | 30 min | Never executed — Firestore and IAM traps |
| 3 | Real Gemini in `hybrid` (§7) | 10 min | The only path never tested against a model |
| 4 | `make stack` | 15 min | Docker images never built |
| 5 | Open Mission Control (§11) | 5 min | Never seen rendered |
| 6 | 4-minute video with Cloud Run proof | 2 h | Mandatory submission asset |
| 7 | 10 consecutive runs | 30 min | Blueprint reliability target |
| 8 | `make teardown` | 5 min | On submission day |
