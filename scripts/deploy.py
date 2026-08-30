#!/usr/bin/env python3
"""Cross-platform Google Cloud deployment for ACC (Doc 09).

Why Python rather than bash: the previous `deploy.sh` used a heredoc piped into
`--config=/dev/stdin`, which does not exist on Windows and behaves erratically
under Git Bash because of path translation. It also never built the Mission
Control image, while Terraform requires `image_web` — so `terraform apply`
failed immediately on a required variable.

Usage:
    python scripts/deploy.py --project-id my-project [--region europe-west1]
    python scripts/deploy.py --project-id my-project --plan-only
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TERRAFORM_DIR = ROOT / "infrastructure" / "terraform"

BLUE, RED, DIM, RESET = "\033[94m", "\033[91m", "\033[2m", "\033[0m"

# APIs without which the deployment cannot even start. `compute` is here
# because Cloud Build's default identity is the Compute Engine service account,
# not because ACC runs any virtual machine.
REQUIRED_APIS = [
    "compute.googleapis.com",
    "cloudbuild.googleapis.com",
    "artifactregistry.googleapis.com",
    "run.googleapis.com",
    "firestore.googleapis.com",
    "pubsub.googleapis.com",
    "aiplatform.googleapis.com",
    "secretmanager.googleapis.com",
    "iam.googleapis.com",
]

IMAGES = [
    # (terraform variable, image name, Dockerfile)
    ("image_mock", "acc-mock-enterprise", "infrastructure/docker/Dockerfile.mock"),
    ("image_api", "acc-api", "infrastructure/docker/Dockerfile.api"),
    ("image_web", "acc-web", "infrastructure/docker/Dockerfile.web"),
]


def step(message: str) -> None:
    print(f"\n{BLUE}▸ {message}{RESET}")


def fail(message: str) -> None:
    print(f"{RED}✕ {message}{RESET}", file=sys.stderr)
    raise SystemExit(1)


def run(command: list[str], cwd: Path = ROOT, check: bool = True) -> int:
    print(f"{DIM}  $ {' '.join(command)}{RESET}")
    code = subprocess.call(command, cwd=str(cwd))
    if check and code != 0:
        fail(f"command failed (exit {code}): {' '.join(command)}")
    return code


def require(binary: str, hint: str) -> str:
    found = shutil.which(binary)
    if not found:
        fail(f"`{binary}` not found in PATH. {hint}")
    return found


def preflight(gcloud: str, project_id: str, auto_enable: bool = False) -> None:
    """Check credentials BEFORE spending time and money on Cloud Build.

    `gcloud auth login` authenticates the CLI. It does NOT create Application
    Default Credentials, which the Terraform Google provider and the Vertex AI
    SDK both read. Without ADC, `terraform apply` fails only after the images
    have been built and pushed — the most expensive possible moment to
    discover a missing credential.
    """
    step("Preflight: credentials")

    token = subprocess.run(
        [gcloud, "auth", "application-default", "print-access-token"],
        capture_output=True, text=True,
    )
    if token.returncode != 0:
        fail(
            "No Application Default Credentials.\n"
            "  Terraform and Vertex AI read ADC, not the gcloud CLI login.\n\n"
            "  gcloud auth application-default login\n"
            f"  gcloud auth application-default set-quota-project {project_id}"
        )
    print(f"{DIM}  ADC present{RESET}")

    # A quota project mismatch does not block Terraform, but it does produce
    # 403 PERMISSION_DENIED on Vertex AI — after deployment, in the demo.
    quota = subprocess.run(
        [gcloud, "auth", "application-default", "print-access-token",
         "--verbosity=none"],
        capture_output=True, text=True,
    )
    adc_path = subprocess.run(
        [gcloud, "info", "--format=value(config.paths.global_config_dir)"],
        capture_output=True, text=True,
    )
    quota_project = None
    if adc_path.returncode == 0:
        candidate = (Path(adc_path.stdout.strip())
                     / "application_default_credentials.json")
        if candidate.exists():
            try:
                quota_project = json.loads(
                    candidate.read_text(encoding="utf-8")
                ).get("quota_project_id")
            except (json.JSONDecodeError, OSError):
                quota_project = None

    if quota_project and quota_project != project_id:
        print(f"{RED}  ▲ ADC quota project is '{quota_project}', "
              f"not '{project_id}'{RESET}")
        print(f"{RED}    Vertex AI will answer 403 during the demo. Fix it:{RESET}")
        print(f"{RED}    gcloud auth application-default "
              f"set-quota-project {project_id}{RESET}")
        fail("Quota project mismatch — fix it before deploying.")
    elif quota_project:
        print(f"{DIM}  ADC quota project matches{RESET}")
    else:
        print(f"{DIM}  ADC quota project not set — run "
              f"`gcloud auth application-default "
              f"set-quota-project {project_id}` if Vertex AI returns 403{RESET}")

    _check_build_identity(gcloud, project_id, auto_enable=auto_enable)


def _enable_apis(gcloud: str, project_id: str, apis: list[str]) -> None:
    """Enable the missing APIs, then wait for the service accounts to appear.

    Enabling an API is free and idempotent; only usage bills. The wait is the
    point: the Compute Engine default service account is created a short while
    AFTER compute.googleapis.com is enabled, so retrying immediately fails
    again on a different message.
    """
    step(f"Enabling {len(apis)} API(s)")
    run([gcloud, "services", "enable", *apis, f"--project={project_id}"])
    print(f"{DIM}  Waiting 90 s for service account provisioning{RESET}")
    time.sleep(90)


def _check_build_identity(gcloud: str, project_id: str,
                          auto_enable: bool = False) -> None:
    """Check EVERY Cloud Build prerequisite at once.

    Cloud Build runs as the Compute Engine default service account. Two
    independent things must hold, and Google reports them one at a time, each
    only after the previous one is fixed:

      1. `compute.googleapis.com` enabled, otherwise the account does not exist
         -> PERMISSION_DENIED on iam.serviceAccounts.get
      2. that account holds `roles/cloudbuild.builds.builder`, otherwise it
         cannot read the uploaded source or push the image
         -> 403 on storage.objects.get

    Automatic Editor grants to default service accounts are disabled on recent
    projects, so a fresh project has an account with NO role at all. Reporting
    both problems together saves a full round trip.
    """
    problems: list[str] = []

    describe = subprocess.run(
        [gcloud, "projects", "describe", project_id,
         "--format=value(projectNumber)"],
        capture_output=True, text=True,
    )
    if describe.returncode != 0:
        print(f"{DIM}  (project number unavailable — build identity not checked){RESET}")
        return
    number = describe.stdout.strip()
    build_sa = f"{number}-compute@developer.gserviceaccount.com"

    enabled = subprocess.run(
        [gcloud, "services", "list", "--enabled", f"--project={project_id}",
         "--format=value(config.name)"],
        capture_output=True, text=True,
    )
    services = set(enabled.stdout.split()) if enabled.returncode == 0 else set()
    missing_apis = [api for api in REQUIRED_APIS if services and api not in services]
    if missing_apis:
        problems.append(
            f"Missing API(s): {', '.join(missing_apis)}\n"
            f"      gcloud services enable {' '.join(missing_apis)} "
            f"--project={project_id}"
        )

    account_exists = subprocess.run(
        [gcloud, "iam", "service-accounts", "describe", build_sa,
         f"--project={project_id}"],
        capture_output=True, text=True,
    ).returncode == 0

    if not account_exists:
        problems.append(
            f"The build service account {build_sa} does not exist.\n"
            "      It is created shortly after compute.googleapis.com is "
            "enabled; wait ~2 minutes."
        )
    else:
        # Recent projects no longer grant Editor to default service accounts,
        # so this one may hold no role whatsoever.
        policy = subprocess.run(
            [gcloud, "projects", "get-iam-policy", project_id,
             "--flatten=bindings[].members",
             f"--filter=bindings.members:{build_sa}",
             "--format=value(bindings.role)"],
            capture_output=True, text=True,
        )
        sufficient = {"roles/cloudbuild.builds.builder", "roles/editor",
                      "roles/owner"}
        # An EMPTY set is precisely the failing case: recent projects grant no
        # role at all to default service accounts. Only skip the check when the
        # command itself failed, never when it succeeded and returned nothing.
        readable = policy.returncode == 0
        roles = set(policy.stdout.split())
        if readable and not (roles & sufficient):
            problems.append(
                f"{build_sa} holds no build role.\n"
                "      It cannot read the uploaded source, nor push the image.\n"
                "      gcloud projects add-iam-policy-binding "
                f"{project_id} \\\n"
                f'        --member="serviceAccount:{build_sa}" \\\n'
                '        --role="roles/cloudbuild.builds.builder"'
            )

    if missing_apis and auto_enable:
        _enable_apis(gcloud, project_id, missing_apis)
        # Re-run the whole check: enabling an API changes the other answers.
        return _check_build_identity(gcloud, project_id, auto_enable=False)

    if problems:
        hint = ""
        if missing_apis:
            hint = ("\n\n  Or let the deployment do it for you:\n"
                    "      make deploy ARGS=--enable-apis\n"
                    "      python scripts/deploy.py --project-id "
                    f"{project_id} --enable-apis")
        fail("Cloud Build prerequisites are not met:\n\n  "
             + "\n\n  ".join(f"{i}. {p}" for i, p in enumerate(problems, 1))
             + hint)

    print(f"{DIM}  Build identity: {build_sa}{RESET}")


def ensure_registry(terraform: str, project_id: str, region: str) -> None:
    """Create the Artifact Registry repository BEFORE building anything.

    Chicken and egg: Terraform owns the repository, but the images are built
    and pushed before `terraform apply` runs. Without this step the build
    succeeds and the push fails on:

        name unknown: Repository "acc" not found

    A targeted apply creates only the registry. Terraform stays the single
    source of truth, and the later full apply is a no-op for that resource.
    """
    step("Artifact Registry")
    run([terraform, "init", "-upgrade"], cwd=TERRAFORM_DIR)
    run([terraform, "apply", "-auto-approve",
         "-target=google_artifact_registry_repository.acc",
         "-var", f"project_id={project_id}",
         "-var", f"region={region}",
         # Required variables, unused by this target.
         "-var", "image_api=placeholder",
         "-var", "image_mock=placeholder",
         "-var", "image_web=placeholder"], cwd=TERRAFORM_DIR)


def repair_state(terraform: str, project_id: str, region: str) -> None:
    """Clear resources left tainted by a failed apply.

    When a Cloud Run service is created but its first revision never becomes
    ready — a missing secret, a bad image — Terraform marks it tainted and the
    next plan wants to REPLACE it. The replacement is then blocked by
    `deletion_protection`, and the fix for that flag can only be applied by the
    very apply the destroy is blocking:

        cannot destroy service without setting deletion_protection=false
        and running `terraform apply`

    Untainting breaks the deadlock: the next apply updates the service in
    place, pushing a healthy revision instead of replacing a broken one.
    """
    step("Repairing Terraform state")
    listed = subprocess.run(
        [terraform, "state", "list"],
        cwd=str(TERRAFORM_DIR), capture_output=True, text=True,
    )
    if listed.returncode != 0:
        print(f"{DIM}  (no state yet — nothing to repair){RESET}")
        return

    services = [line.strip() for line in listed.stdout.splitlines()
                if line.strip().startswith("google_cloud_run_v2_service.")]
    if not services:
        print(f"{DIM}  (no Cloud Run service in state){RESET}")
        return

    gcloud = shutil.which("gcloud") or "gcloud"

    for address in services:
        # `untaint` exits non-zero when the resource is not tainted: that is a
        # normal outcome here, not a failure.
        result = subprocess.run(
            [terraform, "untaint", address],
            cwd=str(TERRAFORM_DIR), capture_output=True, text=True,
        )
        state = "untainted" if result.returncode == 0 else "already clean"

        name = _service_name(terraform, address)
        broken = name and _revision_is_broken(gcloud, name, project_id, region)
        if broken:
            # A Cloud Run revision that failed to start NEVER retries. Updating
            # the service in place keeps reporting the dead revision, so the
            # only way forward is to remove it and let Terraform recreate it
            # against an environment that is now correct.
            print(f"{DIM}  {address}: revision never became ready — recreating{RESET}")
            run([gcloud, "run", "services", "delete", name,
                 f"--region={region}", f"--project={project_id}", "--quiet"],
                check=False)
            subprocess.run([terraform, "state", "rm", address],
                           cwd=str(TERRAFORM_DIR), capture_output=True, text=True)
        else:
            print(f"{DIM}  {address}: {state}{RESET}")


def _service_name(terraform: str, address: str) -> str | None:
    """Read the Cloud Run service name straight from the Terraform state."""
    shown = subprocess.run(
        [terraform, "state", "show", address],
        cwd=str(TERRAFORM_DIR), capture_output=True, text=True,
    )
    if shown.returncode != 0:
        return None
    for line in shown.stdout.splitlines():
        stripped = line.strip()
        if stripped.startswith("name ") and "=" in stripped:
            return stripped.split("=", 1)[1].strip().strip('"')
    return None


def _revision_is_broken(gcloud: str, name: str, project_id: str,
                        region: str) -> bool:
    """True when the service exists but its latest revision never became ready."""
    described = subprocess.run(
        [gcloud, "run", "services", "describe", name, f"--region={region}",
         f"--project={project_id}", "--format=json"],
        capture_output=True, text=True,
    )
    if described.returncode != 0:
        return False  # absent: nothing to repair, Terraform will create it
    try:
        status = json.loads(described.stdout).get("status", {})
    except json.JSONDecodeError:
        return False
    for condition in status.get("conditions", []):
        if condition.get("type") == "Ready" and condition.get("status") != "True":
            return True
    return False


def deployed_api_key(gcloud: str, project_id: str) -> str | None:
    """Read the generated API key so the frontend can be built with it.

    The deployed control plane requires `x-api-key` on every /api/v1 route.
    Mission Control must therefore carry it, and `NEXT_PUBLIC_*` is inlined at
    build time — so it has to be known here, not at runtime.

    This makes the key readable by anyone who loads the page. That is inherent:
    a public single-page app calling a public API cannot hold a secret. The key
    stops casual scanning of the Cloud Run URL, nothing more, and it is
    regenerated by `terraform destroy` + `apply`.
    """
    result = subprocess.run(
        [gcloud, "secrets", "versions", "access", "latest",
         "--secret=acc-api-key", f"--project={project_id}"],
        capture_output=True, text=True,
    )
    key = result.stdout.strip()
    return key if result.returncode == 0 and key else None


def known_api_url(terraform: str) -> str | None:
    """The API URL from a previous apply, if there was one."""
    result = subprocess.run(
        [terraform, "output", "-raw", "acc_api_url"],
        cwd=str(TERRAFORM_DIR), capture_output=True, text=True,
    )
    url = result.stdout.strip()
    return url if result.returncode == 0 and url.startswith("https://") else None


def build_image(gcloud: str, repo: str, name: str, dockerfile: str,
                version: str, build_args: dict[str, str] | None = None) -> str:
    """Build one image through Cloud Build, under a UNIQUE tag.

    `:latest` is the same string on every deployment, so Terraform sees no
    change to `image` and never creates a new revision: the images are pushed
    and the services keep running the old ones. The apply reports
    "0 to add, 3 to change" and nothing actually ships.

    A per-deployment tag makes the change visible to Terraform. `:latest` is
    still pushed alongside, for convenience when pulling by hand.

    The build config is written to a real temporary file rather than piped
    through /dev/stdin: that path does not exist on Windows.
    """
    versioned = f"{repo}/{name}:{version}"
    latest = f"{repo}/{name}:latest"
    args = ["build", "-f", dockerfile]
    for key, value in (build_args or {}).items():
        args += ["--build-arg", f"{key}={value}"]
    args += ["-t", versioned, "-t", latest, "."]
    config = {
        "steps": [{
            "name": "gcr.io/cloud-builders/docker",
            "args": args,
        }],
        "images": [versioned, latest],
    }

    handle = tempfile.NamedTemporaryFile(
        "w", suffix=".json", delete=False, encoding="utf-8"
    )
    try:
        json.dump(config, handle)
        handle.close()
        step(f"Building {name}")
        run([gcloud, "builds", "submit", f"--config={handle.name}", "."])
    finally:
        os.unlink(handle.name)
    return versioned


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-id", default=os.environ.get("PROJECT_ID"))
    parser.add_argument("--region",
                        default=os.environ.get("REGION", "europe-west1"))
    parser.add_argument("--plan-only", action="store_true",
                        help="terraform plan without applying, no image build")
    parser.add_argument("--skip-build", action="store_true",
                        help="reuse the images already in Artifact Registry")
    parser.add_argument("--repair", action="store_true",
                        help="untaint Cloud Run services left broken by a "
                             "failed apply, before applying again")
    parser.add_argument("--enable-apis", action="store_true",
                        help="enable the missing APIs, then wait for the "
                             "service accounts to be provisioned")
    args = parser.parse_args()

    if not args.project_id:
        fail("--project-id is required (or set the PROJECT_ID environment "
             "variable).\n"
             "  PowerShell : $env:PROJECT_ID = \"my-project\"\n"
             "  bash       : export PROJECT_ID=my-project")

    gcloud = require("gcloud", "Install the Google Cloud CLI.")
    terraform = require("terraform", "Install Terraform >= 1.5.")

    repo = f"{args.region}-docker.pkg.dev/{args.project_id}/acc"

    step("Project configuration")
    run([gcloud, "config", "set", "project", args.project_id])

    preflight(gcloud, args.project_id, auto_enable=args.enable_apis)

    # A tag that changes on every deployment: without it Terraform sees no
    # difference and never rolls out the images that were just pushed.
    version = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")

    if args.plan_only or args.skip_build:
        tags = {var: f"{repo}/{name}:latest" for var, name, _ in IMAGES}
        if args.plan_only:
            print(f"{DIM}  (plan only: no image is built){RESET}")
        elif known_api_url(terraform):
            # `NEXT_PUBLIC_ACC_API` is inlined at build time. Skipping the build
            # keeps whatever the previous image was compiled with — including an
            # EMPTY value, which makes Mission Control query its own origin.
            print(f"{RED}  ▲ --skip-build: the web image is NOT rebuilt.{RESET}")
            print(f"{RED}    If Mission Control queries its own origin "
                  f"(acc-web-.../api/v1/... -> 404),{RESET}")
            print(f"{RED}    run a full `make deploy` so the API URL gets "
                  f"baked in.{RESET}")
    else:
        run([gcloud, "auth", "configure-docker",
             f"{args.region}-docker.pkg.dev", "--quiet"])
        ensure_registry(terraform, args.project_id, args.region)
        # `NEXT_PUBLIC_*` is inlined at build time. On a first deployment the
        # API URL does not exist yet, so the frontend derives it from its own
        # origin at runtime. Once it IS known, bake it in — an explicit value
        # always beats a derivation.
        api_url = known_api_url(terraform)
        api_key = deployed_api_key(gcloud, args.project_id)
        if api_url:
            print(f"{DIM}  Baking NEXT_PUBLIC_ACC_API={api_url}{RESET}")
        if api_key:
            print(f"{DIM}  Baking NEXT_PUBLIC_ACC_API_KEY={api_key[:6]}... "
                  f"(public by nature, see deployed_api_key){RESET}")
        else:
            print(f"{RED}  ▲ API key unavailable: Mission Control will get 401s."
                  f"{RESET}")

        tags = {}
        for variable, name, dockerfile in IMAGES:
            extra = None
            if name == "acc-web":
                extra = {}
                if api_url:
                    extra["NEXT_PUBLIC_ACC_API"] = api_url
                if api_key:
                    extra["NEXT_PUBLIC_ACC_API_KEY"] = api_key
            tags[variable] = build_image(gcloud, repo, name, dockerfile,
                                         version, extra)

    step("Infrastructure")
    if args.plan_only or args.skip_build:
        run([terraform, "init", "-upgrade"], cwd=TERRAFORM_DIR)

    if args.repair and not args.plan_only:
        repair_state(terraform, args.project_id, args.region)

    # Terraform declares image_api, image_mock AND image_web with no default.
    # Omitting one blocks the apply on an interactive prompt.
    variables: list[str] = [
        "-var", f"project_id={args.project_id}",
        "-var", f"region={args.region}",
    ]
    for variable, _, _ in IMAGES:
        variables += ["-var", f"{variable}={tags[variable]}"]

    action = "plan" if args.plan_only else "apply"
    run([terraform, action, *variables], cwd=TERRAFORM_DIR)

    if args.plan_only:
        return 0

    step("ACC deployed")
    for output in ("acc_api_url", "acc_web_url"):
        result = subprocess.run(
            [terraform, "output", "-raw", output],
            cwd=str(TERRAFORM_DIR), capture_output=True, text=True,
        )
        if result.returncode == 0:
            print(f"  {output:<12} {result.stdout.strip()}")

    print(f"\n{DIM}  Next: python scripts/doctor.py --api <acc_api_url>{RESET}")
    print(f"{DIM}  Then open <acc_web_url> and check the browser network tab:{RESET}")
    print(f"{DIM}  calls must go to acc-api-..., never to acc-web-... .{RESET}")
    print(f"{DIM}  Keep the Cloud Run dashboard open — the video must show it.{RESET}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
