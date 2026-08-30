"""Cost guardrails.

With a fixed budget (hackathon credits), an expensive default or a service that
bills while idle is discovered on the invoice.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from tests.conftest import make_settings

ROOT = Path(__file__).resolve().parents[2]
TERRAFORM = "\n".join(
    p.read_text(encoding="utf-8")
    for p in sorted((ROOT / "infrastructure" / "terraform").glob("*.tf"))
)


def test_no_agent_uses_a_pro_model_by_default():
    """A "Pro" model costs roughly 4x more: never by default."""
    settings = make_settings()
    assert settings.gemini_model_reasoning == "", (
        "le modèle de raisonnement doit être vide par défaut"
    )
    assert settings.reasoning_model == settings.gemini_model
    assert "pro" not in settings.gemini_model.lower()


def test_reasoning_model_is_actually_wired():
    """Regression: this setting was declared but never read.

    A button that does nothing is worse than no button: it gives the illusion
    of a control.
    """
    from apps.api.repositories.factory import reset_store
    from apps.api.services.container import build_container

    reset_store()
    # Arbitrary value: the test checks the WIRING, not a model name. Hardcoding
    # a real identifier here would make it wrong at the next retirement.
    marker = "modele-de-raisonnement-distinct"
    settings = make_settings(gemini_model_reasoning=marker)
    container = build_container(settings)
    assert container.runtime.get("failure-twin").model == marker
    assert container.runtime.get("supply-agent").model == settings.gemini_model
    reset_store()


def test_every_cloud_run_service_scales_to_zero():
    """A minimum instance count > 0 bills even while idle."""
    minimums = re.findall(r"min_instance_count\s*=\s*(\S+)", TERRAFORM)
    assert minimums, "aucun min_instance_count déclaré"
    for value in minimums:
        assert value == "0", f"min_instance_count = {value} facture à l'inactivité"


def test_every_cloud_run_service_has_an_instance_ceiling():
    services = TERRAFORM.count("resource \"google_cloud_run_v2_service\"")
    ceilings = len(re.findall(r"max_instance_count", TERRAFORM))
    assert ceilings >= services, "un service sans plafond peut s'emballer"


@pytest.mark.parametrize("expensive", [
    "google_container_cluster",      # GKE facture en continu
    "google_sql_database_instance",  # Cloud SQL idem
    "google_redis_instance",
    "google_compute_instance",
    "google_vertex_ai_endpoint",     # un endpoint deployé facture à l'heure
])
def test_no_continuously_billing_resource(expensive):
    """Items that bill by the hour rather than by usage are excluded."""
    assert expensive not in TERRAFORM


def test_firestore_is_protected_against_accidental_deletion():
    assert "delete_protection_state" in TERRAFORM


def test_cost_labels_allow_billing_breakdown():
    """Without labels, ACC spend cannot be isolated in the invoice."""
    assert "cost_labels" in TERRAFORM
    assert re.search(r'app\s*=\s*"acc"', TERRAFORM)


def test_agent_timeout_is_bounded():
    """An unbounded model call can consume without end."""
    settings = make_settings()
    assert 0 < settings.acc_agent_timeout_s <= 60


def test_retry_budget_is_bounded():
    """An unbounded recovery loop would multiply model calls."""
    from domain.models import Task

    assert Task(mission_id="M", type="t").max_attempts <= 5


# ---------------------------------------------------------------------------
# Model lifecycle
#
# The initial default `gemini-2.5-flash` retires on 16 October 2026. It would
# have worked during the hackathon, then returned 404 if evaluation ran into
# October — a silent failure, after submission.
# ---------------------------------------------------------------------------
RETIRING_MODELS = {
    # id -> announced retirement date
    "gemini-2.5-pro": "2026-10-16",
    "gemini-2.5-flash": "2026-10-16",
    "gemini-2.5-flash-lite": "2026-10-16",
    "gemini-2.5-flash-image": "2026-10-02",
    "gemini-2.0-flash": "2026-06-01 (already retired)",
    "gemini-2.0-flash-lite": "2026-06-01 (already retired)",
}

CONFIG_FILES = [
    ROOT / "apps" / "api" / "core" / "config.py",
    ROOT / ".env.example",
    ROOT / "infrastructure" / "terraform" / "variables.tf",
]


@pytest.mark.parametrize("path", CONFIG_FILES, ids=lambda p: p.name)
def test_no_retiring_model_is_configured(path):
    """No default may point at an end-of-life model."""
    text = path.read_text(encoding="utf-8")
    for model, eol in RETIRING_MODELS.items():
        # The name may appear in an explanatory comment; only real assignments
        # are rejected.
        assignments = re.findall(
            rf'(?:=|default\s*=)\s*"{re.escape(model)}"', text
        )
        assert not assignments, (
            f"{path.name} configure {model}, retiré le {eol}"
        )


def test_configured_model_is_current_generation():
    settings = make_settings()
    assert settings.gemini_model not in RETIRING_MODELS
    assert settings.gemini_model.startswith("gemini-3."), (
        f"{settings.gemini_model} n'est pas de génération courante"
    )


def test_no_hardwired_sampling_parameters():
    """temperature / top_p / top_k have been deprecated since 21 July 2026.

    Hardwiring them is the usual blocker when switching models. ACC sets none
    of them: changing model is a single environment variable.
    """
    for source in (ROOT / "agents").rglob("*.py"):
        text = source.read_text(encoding="utf-8")
        code = "\n".join(
            line for line in text.splitlines() if not line.lstrip().startswith("#")
        )
        for banned in ("temperature=", "top_p=", "top_k="):
            assert banned not in code, f"{source.name} câble {banned}"


# ---------------------------------------------------------------------------
# Deployment tooling
#
# Regression found on a Windows workstation: the guide and the scripts were
# written entirely in bash. `export PROJECT_ID=...` is not a PowerShell command,
# and `deploy.sh` piped a heredoc into `--config=/dev/stdin`, a path that does
# not exist on Windows.
#
# Worse: deploy.sh never built the Mission Control image and never passed
# `image_web`, a required Terraform variable. `terraform apply` would have
# stopped on an interactive prompt at the very first deployment.
# ---------------------------------------------------------------------------
DEPLOY = ROOT / "scripts" / "deploy.py"


def _call_position(source: str, function: str) -> int:
    """Offset of the first CALL to `function`, ignoring its definition.

    Ordering tests must not depend on a signature: adding a parameter would
    then break a test that says nothing about parameters.
    """
    match = re.search(rf"(?<!def )\b{re.escape(function)}\(", source)
    assert match, f"no call to {function}() found"
    return match.start()


def test_deployment_tooling_is_cross_platform():
    """No bash-only script is left on the deployment path."""
    leftovers = [p.name for p in (ROOT / "scripts").glob("*.sh")
                 if p.stem in {"deploy", "teardown", "costs"}]
    assert not leftovers, f"bash-only deployment scripts: {leftovers}"
    for expected in ("deploy.py", "teardown.py", "costs.py"):
        assert (ROOT / "scripts" / expected).exists()


def test_deploy_builds_every_required_image():
    """Terraform declares three images with no default: all three are needed."""
    source = DEPLOY.read_text(encoding="utf-8")
    variables = re.findall(r'variable "(image_\w+)"', TERRAFORM)
    assert set(variables) == {"image_api", "image_mock", "image_web"}
    for variable in variables:
        assert variable in source, (
            f"{variable} is required by Terraform but absent from deploy.py"
        )


def test_every_image_has_a_dockerfile():
    source = DEPLOY.read_text(encoding="utf-8")
    for dockerfile in re.findall(r'"(infrastructure/docker/Dockerfile\.\w+)"', source):
        assert (ROOT / dockerfile).exists(), f"{dockerfile} referenced but missing"


def test_deploy_does_not_use_posix_only_paths():
    """/dev/stdin does not exist on Windows.

    The module docstring legitimately mentions it — it explains why the bash
    version was replaced. So the check targets executable code only, parsed
    with `ast` rather than sliced by hand.
    """
    import ast

    tree = ast.parse(DEPLOY.read_text(encoding="utf-8"))
    literals = [
        node.value for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    ]
    # `clean=False` is essential: get_docstring() dedents and strips by
    # default, so the returned text no longer matches the raw literal.
    docstrings = {ast.get_docstring(tree, clean=False)} | {
        ast.get_docstring(node, clean=False) for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    }
    executable = [text for text in literals if text not in docstrings]
    offenders = [t for t in executable if "/dev/stdin" in t]
    assert not offenders, f"POSIX-only path in executable code: {offenders}"


def test_makefile_targets_reach_the_python_launchers():
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    for target in ("deploy:", "plan:", "costs:", "teardown:"):
        assert f"\n{target}" in makefile
    assert ".sh" not in makefile, "the Makefile must not call a bash script"


def test_deploy_checks_credentials_before_building():
    """Failing after the images are built is the most expensive failure.

    `gcloud auth login` authenticates the CLI but does NOT create Application
    Default Credentials, which Terraform and Vertex AI both read. Without a
    preflight, the missing credential surfaces only at `terraform apply` —
    after Cloud Build has already run three times.
    """
    source = DEPLOY.read_text(encoding="utf-8")
    assert "def preflight(" in source
    assert "application-default" in source

    # The preflight must run before the build loop, not after it.
    # Keyed on the CALL, not the signature: adding a parameter must not break
    # an ordering test — that would say nothing about ordering.
    assert _call_position(source, "preflight") < _call_position(source, "build_image"), (
        "credentials are checked after the images are built"
    )


def test_deployment_guide_documents_adc():
    guide = (ROOT / "DEPLOYMENT.md").read_text(encoding="utf-8")
    assert "gcloud auth application-default login" in guide
    assert "set-quota-project" in guide


def test_deploy_checks_the_build_identity():
    """Cloud Build runs as the Compute Engine default service account.

    That account only exists once `compute.googleapis.com` is enabled. Without
    it, `gcloud builds submit` fails with an `iam.serviceAccounts.get` denial
    that reads like a permissions problem and is a missing API.
    """
    source = DEPLOY.read_text(encoding="utf-8")
    assert "compute.googleapis.com" in source
    assert "-compute@developer.gserviceaccount.com" in source

    assert (_call_position(source, "_check_build_identity")
            < _call_position(source, "build_image")), (
        "the build identity is checked after the build has started"
    )


def test_deployment_guide_enables_the_compute_api():
    guide = (ROOT / "DEPLOYMENT.md").read_text(encoding="utf-8")
    assert "compute.googleapis.com" in guide, (
        "the API list must include compute, or the first build fails"
    )


def test_deploy_detects_a_build_account_with_no_role():
    """An EMPTY role set is the failing case, not a reason to skip the check.

    Recent projects no longer grant Editor to default service accounts, so a
    fresh build identity holds no role at all. A first version of the check
    read `if roles and ...`, which silently let exactly that case through.
    """
    source = DEPLOY.read_text(encoding="utf-8")
    assert "readable = policy.returncode == 0" in source, (
        "the check must distinguish a failed command from an empty result"
    )
    assert "if readable and not (roles & sufficient):" in source


def test_deploy_reports_every_prerequisite_at_once():
    """One error per attempt wastes a full round trip each time."""
    source = DEPLOY.read_text(encoding="utf-8")
    assert "problems: list[str] = []" in source
    assert "problems.append" in source
    assert source.count("problems.append") >= 3


def test_pubsub_agent_can_mint_its_oidc_token():
    """Without this role the subscription is created but every push is rejected.

    The mission then stays in CREATED with no application-level error — the
    hardest possible symptom to diagnose after a deployment.
    """
    assert "roles/iam.serviceAccountTokenCreator" in TERRAFORM
    assert "gcp-sa-pubsub.iam.gserviceaccount.com" in TERRAFORM


def test_every_runtime_service_account_can_write_logs():
    """A service unable to log is invisible exactly when it fails."""
    for service in ("api", "mock", "web"):
        assert f'"google_service_account" "{service}"' in TERRAFORM
    assert TERRAFORM.count("roles/logging.logWriter") >= 3


def test_no_documentation_points_at_a_deleted_script():
    """A guide that names a file which no longer exists sends the reader nowhere."""
    for name in ("README.md", "DEPLOYMENT.md"):
        text = (ROOT / name).read_text(encoding="utf-8")
        for script in ("deploy.sh", "costs.sh", "teardown.sh"):
            assert script not in text, f"{name} still references {script}"

    for tf in (ROOT / "infrastructure" / "terraform").glob("*.tf"):
        content = tf.read_text(encoding="utf-8")
        for script in ("deploy.sh", "costs.sh", "teardown.sh"):
            assert script not in content, f"{tf.name} still references {script}"


def test_deploy_can_enable_the_missing_apis():
    """Five round trips to enable APIs one batch at a time is not tooling."""
    source = DEPLOY.read_text(encoding="utf-8")
    assert "--enable-apis" in source
    assert "def _enable_apis(" in source

    # After enabling, the whole check must run again: enabling one API changes
    # the answer to the others (the build service account appears afterwards).
    assert "auto_enable=False" in source, (
        "the re-check must not loop forever"
    )
    assert "time.sleep" in source, (
        "service account provisioning is asynchronous; retrying immediately "
        "fails again on a different message"
    )


def test_makefile_forwards_arguments_to_deploy():
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    assert "$(ARGS)" in makefile, "make deploy ARGS=--enable-apis must work"


def test_registry_is_created_before_any_image_is_built():
    """Chicken and egg found on the first real deployment.

    Terraform owns the Artifact Registry repository, but images are built and
    pushed before `terraform apply` runs. The build succeeded and the push
    failed on `name unknown: Repository "acc" not found` — after ten retries
    and a full build's worth of billed minutes.
    """
    source = DEPLOY.read_text(encoding="utf-8")
    assert "def ensure_registry(" in source
    assert "google_artifact_registry_repository.acc" in source
    assert (_call_position(source, "ensure_registry")
            < _call_position(source, "build_image")), (
        "the registry is created after the images are built"
    )


def test_targeted_registry_apply_supplies_every_required_variable():
    """A missing variable turns a targeted apply into an interactive prompt."""
    source = DEPLOY.read_text(encoding="utf-8")
    start = source.index("def ensure_registry(")
    end = source.index("def build_image(")
    body = source[start:end]
    for variable in re.findall(r'variable "(image_\w+)"', TERRAFORM):
        assert variable in body, (
            f"{variable} is required by Terraform but absent from the "
            "targeted registry apply"
        )


# ---------------------------------------------------------------------------
# Secrets
#
# Found on the first real deployment: Terraform created the secret CONTAINERS
# but no VERSION. A secret with no version has no `latest`, so every Cloud Run
# revision failed with:
#   Secret projects/.../secrets/acc-api-key/versions/latest was not found
#
# The values were meant to be created by hand with `openssl rand` — a manual
# step, easy to skip, and unavailable in a default PowerShell.
# ---------------------------------------------------------------------------
def test_every_secret_has_a_version():
    """A secret container without a version cannot serve `latest`."""
    containers = set(re.findall(
        r'resource "google_secret_manager_secret" "(\w+)"', TERRAFORM))
    versions = set(re.findall(
        r'resource "google_secret_manager_secret_version" "(\w+)"', TERRAFORM))
    assert containers, "no secret declared"
    missing = containers - versions
    assert not missing, f"secret(s) with no version: {sorted(missing)}"


def test_secret_values_are_generated_not_manual():
    """A manual prerequisite is a prerequisite that gets skipped."""
    assert "random_password" in TERRAFORM
    assert 'source  = "hashicorp/random"' in TERRAFORM, (
        "the random provider must be declared"
    )


def test_no_secret_value_is_printed_as_an_output():
    outputs = (ROOT / "infrastructure" / "terraform" / "outputs.tf").read_text(
        encoding="utf-8")
    assert "random_password" not in outputs
    assert "secret_data" not in outputs


def test_cloud_run_waits_for_the_secret_versions():
    """Terraform infers a dependency on the SECRET, never on its VERSION.

    Declaring the versions is not enough: without an explicit `depends_on`,
    the service can still be created before any version exists.
    """
    cloud_run = (ROOT / "infrastructure" / "terraform" / "cloud_run.tf").read_text(
        encoding="utf-8")
    match = re.search(
        r'resource "google_cloud_run_v2_service" "api" \{(.*?)\n\}',
        cloud_run, re.S)
    assert match, "the api service was not found"
    body = match.group(1)
    for version in ("api_key", "pubsub_push_token"):
        assert f"google_secret_manager_secret_version.{version}" in body, (
            f"the api service does not wait for the {version} version"
        )


def test_no_resource_declares_depends_on_twice():
    """A duplicate argument is rejected by Terraform — I introduced one."""
    for path in (ROOT / "infrastructure" / "terraform").glob("*.tf"):
        text = path.read_text(encoding="utf-8")
        for match in re.finditer(r'resource "[\w.]+" "\w+" \{', text):
            start, depth, index = match.end(), 1, match.end()
            while depth:
                if text[index] == "{":
                    depth += 1
                elif text[index] == "}":
                    depth -= 1
                index += 1
            block = text[start:index - 1]
            count = len(re.findall(r"^\s*depends_on\s*=", block, re.M))
            assert count <= 1, (
                f"{path.name}: {match.group(0)} declares depends_on {count} times"
            )


# ---------------------------------------------------------------------------
# Teardown must actually work
#
# Found on the first real deployment: provider v6 defaults Cloud Run services to
# deletion_protection = true. That blocks a replacement after a failed revision
# — and it blocks `terraform destroy` too, which means `make teardown` could
# never have brought billing back to zero.
# ---------------------------------------------------------------------------
def test_every_cloud_run_service_can_be_destroyed():
    services = re.findall(
        r'resource "google_cloud_run_v2_service" "(\w+)"', TERRAFORM)
    assert len(services) == 3, f"expected 3 services, found {services}"
    assert TERRAFORM.count("deletion_protection = false") == len(services), (
        "a protected service blocks both replacement and teardown"
    )


def test_firestore_protection_is_lifted_by_teardown():
    """Firestore stays protected — it holds mission state.

    That is deliberate, so the teardown must lift it explicitly. A protection
    nobody can remove is a permanent bill.
    """
    assert "DELETE_PROTECTION_ENABLED" in TERRAFORM
    teardown = (ROOT / "scripts" / "teardown.py").read_text(encoding="utf-8")
    assert "--no-delete-protection" in teardown
    assert teardown.index("--no-delete-protection") < teardown.index('"destroy"'), (
        "protection must be lifted before terraform destroy runs"
    )


def test_apis_are_not_disabled_on_destroy():
    """Disabling APIs on destroy cascades into unrelated resources."""
    assert "disable_on_destroy = false" in TERRAFORM


def test_no_resource_prevents_its_own_destruction():
    assert "prevent_destroy" not in TERRAFORM, (
        "prevent_destroy would make teardown impossible"
    )


def test_deploy_can_repair_a_tainted_service():
    """A failed apply leaves a deadlock the next apply cannot break alone.

    A Cloud Run service created with a broken first revision is marked tainted.
    The next plan wants to REPLACE it, the replacement is blocked by
    deletion_protection, and the fix for that flag can only be applied by the
    very apply the destroy is blocking.
    """
    source = DEPLOY.read_text(encoding="utf-8")
    assert "--repair" in source
    assert "def repair_state(" in source
    assert '"untaint"' in source

    # The repair must precede the apply, and never run in plan-only mode.
    assert (_call_position(source, "repair_state")
            < source.index('action = "plan" if args.plan_only else "apply"'))
    assert "args.repair and not args.plan_only" in source


def test_repair_does_not_treat_a_clean_resource_as_a_failure():
    """`terraform untaint` exits non-zero when nothing was tainted."""
    source = DEPLOY.read_text(encoding="utf-8")
    start = source.index("def repair_state(")
    end = source.index("def build_image(")
    body = source[start:end]
    assert "already clean" in body
    assert "check=True" not in body, (
        "a clean resource must not abort the deployment"
    )


def test_repair_recreates_a_service_whose_revision_never_started():
    """A failed Cloud Run revision never retries.

    Untainting is enough to break the deletion_protection deadlock, but not
    when the revision itself is permanently dead: updating in place keeps
    reporting the same broken revision. The only way forward is to remove the
    service and let Terraform recreate it against a now-correct environment.
    """
    source = DEPLOY.read_text(encoding="utf-8")
    assert "def _revision_is_broken(" in source
    assert '"Ready"' in source
    assert '"state", "rm"' in source

    start = source.index("def repair_state(")
    end = source.index("def _service_name(")
    body = source[start:end]
    assert "run\", \"services\", \"delete\"" in body


def test_repair_leaves_healthy_services_alone():
    """Only a service reporting Ready != True is recreated."""
    source = DEPLOY.read_text(encoding="utf-8")
    start = source.index("def _revision_is_broken(")
    end = source.index("def build_image(")
    body = source[start:end]
    assert 'condition.get("status") != "True"' in body
    assert "return False" in body, "an absent service must not be 'broken'"


# ---------------------------------------------------------------------------
# The frontend must find the control plane once deployed
#
# `NEXT_PUBLIC_*` is inlined AT BUILD TIME. Passing it as a Cloud Run runtime
# variable has no effect — the value was already compiled into the bundle. And
# on a first deployment the API URL does not exist yet, so it cannot be baked.
# Without a runtime fallback, the deployed Mission Control calls 127.0.0.1.
# ---------------------------------------------------------------------------
def test_frontend_resolves_the_api_at_runtime_when_not_baked():
    api = (ROOT / "apps" / "web" / "lib" / "api.ts").read_text(encoding="utf-8")
    assert "function resolveApiBase()" in api
    assert "window.location.origin" in api
    assert 'replace("acc-web", "acc-api")' in api
    assert "process.env.NEXT_PUBLIC_ACC_API" in api, (
        "an explicitly baked value must still win"
    )


def test_deploy_bakes_the_api_url_once_it_is_known():
    """An explicit value always beats a derivation."""
    source = DEPLOY.read_text(encoding="utf-8")
    assert "def known_api_url(" in source
    assert "--build-arg" in source
    assert "NEXT_PUBLIC_ACC_API" in source


def test_web_dockerfile_accepts_the_build_argument():
    dockerfile = (ROOT / "infrastructure" / "docker" / "Dockerfile.web").read_text(
        encoding="utf-8")
    assert "ARG NEXT_PUBLIC_ACC_API" in dockerfile
    assert "ENV NEXT_PUBLIC_ACC_API" in dockerfile


def test_cors_regex_covers_the_deployed_frontend():
    """A frontend blocked by CORS is a blank page in front of the judges."""
    import re as _re
    from tests.conftest import make_settings

    pattern = make_settings().acc_cors_origin_regex
    for url in ("https://acc-web-jycspetv4a-ew.a.run.app",
                "https://acc-web-327474819537.europe-west1.run.app"):
        assert _re.fullmatch(pattern, url), f"{url} would be blocked by CORS"
    assert not _re.fullmatch(pattern, "https://acc-web-x.a.run.app.evil.com")


def test_empty_build_arg_does_not_win_over_the_fallback():
    """`ENV VAR=${ARG}` with no --build-arg yields "", not undefined.

    Observed on the deployed Mission Control: `process.env.X ?? fallback` kept
    the empty string, every call became relative, and the frontend queried its
    own origin — 404 on every /api/v1 route.
    """
    api = (ROOT / "apps" / "web" / "lib" / "api.ts").read_text(encoding="utf-8")
    resolver = api[api.index("function resolveApiBase()"):
                   api.index("export const API_BASE")]
    assert "if (baked) return baked;" in resolver
    assert "NEXT_PUBLIC_ACC_API ??" not in resolver, (
        "?? keeps an empty string; use truthiness"
    )


def test_dockerfile_declares_the_arg_before_the_build():
    """The value must be inlined during `next build`, not after."""
    dockerfile = (ROOT / "infrastructure" / "docker" / "Dockerfile.web").read_text(
        encoding="utf-8")
    arg_line = dockerfile.index("ARG NEXT_PUBLIC_ACC_API")
    build_line = dockerfile.index("npm run build") if "npm run build" in dockerfile \
        else dockerfile.index("next build")
    assert arg_line < build_line, (
        "the build argument must be declared before the build step"
    )


def test_skip_build_warns_that_the_frontend_is_not_rebuilt():
    """`--skip-build` keeps whatever the previous web image was compiled with.

    Since `NEXT_PUBLIC_ACC_API` is inlined at build time, skipping the build
    silently preserves an empty value — and Mission Control keeps querying its
    own origin. The flag saves minutes and costs a debugging session.
    """
    source = DEPLOY.read_text(encoding="utf-8")
    assert "--skip-build: the web image is NOT rebuilt" in source
    assert "queries its own origin" in source


def test_only_the_web_image_receives_the_api_url():
    """Baking it into the API or mock image would be meaningless."""
    source = DEPLOY.read_text(encoding="utf-8")
    start = source.index('if name == "acc-web":')
    end = source.index("build_image(gcloud, repo, name, dockerfile", start)
    assert "NEXT_PUBLIC_ACC_API" in source[start:end]
    # Nothing is baked outside that branch.
    before = source[:start]
    assert 'extra = None' in before or "extra = None" in source[:end]


# ---------------------------------------------------------------------------
# Images must actually roll out
#
# Observed on the first successful deployment: the three images were built and
# pushed, then Terraform reported "0 to add, 3 to change" and changed only a
# scaling block. The `image` attribute was the same string — `:latest` — so
# Terraform saw no difference and never created a new revision. The containers
# kept running the previous build.
# ---------------------------------------------------------------------------
def test_images_carry_a_per_deployment_tag():
    source = DEPLOY.read_text(encoding="utf-8")
    assert "version: str" in source, "build_image must take a version"
    assert 'f"{repo}/{name}:{version}"' in source
    assert 'strftime("%Y%m%d-%H%M%S")' in source


def test_terraform_receives_the_versioned_tag_not_latest():
    """Passing `:latest` to Terraform is what silently skipped the rollout."""
    source = DEPLOY.read_text(encoding="utf-8")
    assert "return versioned" in source, (
        "build_image must return the unique tag, which is what Terraform gets"
    )
    # `:latest` is still pushed, and is the right fallback when not building.
    assert 'f"{repo}/{name}:latest"' in source


def test_latest_is_still_pushed_alongside():
    """Convenience for a manual `docker pull`, never the deployed reference."""
    source = DEPLOY.read_text(encoding="utf-8")
    assert '"images": [versioned, latest]' in source


# ---------------------------------------------------------------------------
# CORS must reach the container
#
# Found on the deployed instance: the regex was correct and tested, and it was
# never passed to Cloud Run. In cloud mode the control plane therefore allowed
# no origin at all, and the browser blocked every call from Mission Control —
# while `curl` kept working, which is exactly how it stayed invisible.
# ---------------------------------------------------------------------------
CLOUD_RUN = (ROOT / "infrastructure" / "terraform" / "cloud_run.tf").read_text(
    encoding="utf-8")


def _service_block(name: str) -> str:
    match = re.search(
        rf'resource "google_cloud_run_v2_service" "{name}" \{{', CLOUD_RUN)
    assert match, f"service {name} not found"
    start, depth, index = match.end(), 1, match.end()
    while depth:
        if CLOUD_RUN[index] == "{":
            depth += 1
        elif CLOUD_RUN[index] == "}":
            depth -= 1
        index += 1
    return CLOUD_RUN[start:index - 1]


def test_cors_configuration_is_passed_to_the_api_service():
    """A setting the container never receives is not a setting."""
    api = _service_block("api")
    assert "ACC_CORS_ORIGINS" in api, (
        "without it the deployed frontend is blocked by CORS"
    )
    assert "ACC_CORS_ORIGIN_REGEX" in api
    code = "\n".join(
        line for line in api.splitlines() if not line.lstrip().startswith("#")
    )
    assert "google_cloud_run_v2_service.web" not in code, (
        "referencing the web service from the API is what created the cycle; "
        "the regex covers the Cloud Run URLs without any cross-reference"
    )


def test_cors_regex_default_covers_both_cloud_run_url_formats():
    match = re.search(
        r'variable "cors_origin_regex".*?default\s*=\s*"(.*?)"\n\}',
        (ROOT / "infrastructure" / "terraform" / "variables.tf").read_text(
            encoding="utf-8"), re.S)
    assert match
    pattern = match.group(1).replace("\\\\", "\\")

    for url in ("https://acc-web-jycspetv4a-ew.a.run.app",
                "https://acc-web-327474819537.europe-west1.run.app"):
        assert re.fullmatch(pattern, url), f"{url} would be blocked"
    for hostile in ("https://acc-web-x.a.run.app.evil.com",
                    "http://acc-web-x.a.run.app",
                    "https://evil-web-x.a.run.app"):
        assert not re.fullmatch(pattern, hostile), f"{hostile} must be refused"


def test_no_dependency_cycle_between_cloud_run_services():
    """Terraform refuses a cycle outright:

        Error: Cycle: google_cloud_run_v2_service.api,
                      google_cloud_run_v2_service.web

    A first fix had the API read the web service URL for CORS while the web
    service still passed the API URL back. Note that `api -> mock` is a
    legitimate, acyclic dependency — banning every cross-reference would have
    been simpler and wrong. The property is the ABSENCE OF A CYCLE, of any
    length, so it is detected by traversal rather than pairwise.
    """
    names = re.findall(r'resource "google_cloud_run_v2_service" "(\w+)"', CLOUD_RUN)
    graph: dict[str, set[str]] = {}
    for name in names:
        code = "\n".join(
            line for line in _service_block(name).splitlines()
            if not line.lstrip().startswith("#")
        )
        graph[name] = set(
            re.findall(r"google_cloud_run_v2_service\.(\w+)\.", code)) - {name}

    visiting: set[str] = set()
    done: set[str] = set()

    def walk(node: str, path: list[str]) -> None:
        if node in done:
            return
        assert node not in visiting, f"cycle: {' -> '.join(path + [node])}"
        visiting.add(node)
        for target in sorted(graph.get(node, ())):
            walk(target, path + [node])
        visiting.discard(node)
        done.add(node)

    for name in names:
        walk(name, [])


def test_web_service_does_not_set_a_build_time_variable_at_runtime():
    """Only an actual assignment counts — the comment explaining why must stay."""
    web = _service_block("web")
    code = "\n".join(
        line for line in web.splitlines() if not line.lstrip().startswith("#")
    )
    assert 'name  = "NEXT_PUBLIC_ACC_API"' not in code, (
        "a NEXT_PUBLIC_* runtime variable has no effect and creates a cycle"
    )


def test_deploy_bakes_the_api_key_into_the_frontend():
    """The deployed control plane requires x-api-key on every /api/v1 route.

    Mission Control must carry it, and `NEXT_PUBLIC_*` is inlined at build
    time — so it has to be read from Secret Manager during the build, not
    supplied at runtime.
    """
    source = DEPLOY.read_text(encoding="utf-8")
    assert "def deployed_api_key(" in source
    assert "NEXT_PUBLIC_ACC_API_KEY" in source
    assert "secrets" in source and "acc-api-key" in source


def test_the_key_is_only_baked_into_the_web_image():
    source = DEPLOY.read_text(encoding="utf-8")
    start = source.index('if name == "acc-web":')
    end = source.index("build_image(gcloud, repo, name, dockerfile", start)
    assert "NEXT_PUBLIC_ACC_API_KEY" in source[start:end]


def test_web_dockerfile_accepts_the_key_before_the_build():
    dockerfile = (ROOT / "infrastructure" / "docker" / "Dockerfile.web").read_text(
        encoding="utf-8")
    assert "ARG NEXT_PUBLIC_ACC_API_KEY" in dockerfile
    build = dockerfile.index("npm run build") if "npm run build" in dockerfile \
        else dockerfile.index("next build")
    assert dockerfile.index("ARG NEXT_PUBLIC_ACC_API_KEY") < build


def test_the_public_nature_of_the_key_is_documented():
    """A key inside a public bundle is not a secret. Say so where it is read."""
    source = DEPLOY.read_text(encoding="utf-8")
    start = source.index("def deployed_api_key(")
    end = source.index("def known_api_url(")
    assert "cannot hold a secret" in source[start:end]


# ---------------------------------------------------------------------------
# Service-to-service reachability
#
# Found on the deployed instance: every supplier call returned `HTTP 404`. The
# enterprise mock had internal-only ingress, and a Cloud Run service calling
# another over its public URL leaves the Google network — so the request was
# rejected, with a 404 that reads like a missing route.
# ---------------------------------------------------------------------------
def test_the_enterprise_mock_is_reachable_from_cloud_run():
    mock = _service_block("mock")
    code = "\n".join(
        line for line in mock.splitlines() if not line.lstrip().startswith("#")
    )
    assert "INGRESS_TRAFFIC_INTERNAL_LOAD_BALANCER" not in code, (
        "internal-only ingress rejects the call from acc-api with a 404"
    )
    assert "INGRESS_TRAFFIC_ALL" in code


def test_the_mock_stays_restricted_by_iam():
    """Opening ingress must not open access."""
    assert "api_calls_mock" in TERRAFORM
    assert 'role     = "roles/run.invoker"' in TERRAFORM
    # allUsers must never be granted on the enterprise mock.
    mock_binding = TERRAFORM[TERRAFORM.index('"api_calls_mock"'):]
    assert "allUsers" not in mock_binding[:400]


def test_the_client_proves_its_identity_to_cloud_run():
    """IAM checks an OIDC token, never the application API key."""
    source = (ROOT / "apps" / "api" / "services" / "enterprise_tools.py").read_text(
        encoding="utf-8")
    assert "fetch_id_token" in source
    assert "Bearer" in source
    # Only for a real https target: local runs and ASGI tests must be untouched.
    assert 'startswith("https://")' in source
    assert "self._transport is not None" in source


def test_agents_are_told_to_answer_in_english():
    """A model answers in the language it feels like unless told otherwise.

    The deployed fleet produced a French `finding` in the timeline, in a
    submission required to be in English.
    """
    guardrails = (ROOT / "agents" / "base.py").read_text(encoding="utf-8")
    assert "human-readable string in English" in guardrails


# ---------------------------------------------------------------------------
# Demo reset must actually reset
#
# `FirestoreStore.reset()` raised NotImplementedError, so the Reset control did
# nothing once deployed. Missions from every rehearsal piled up, and the first
# thing a judge saw was a stale approval from an earlier run.
# ---------------------------------------------------------------------------
STORE = ROOT / "apps" / "api" / "repositories" / "firestore_store.py"


def test_firestore_reset_is_implemented():
    source = STORE.read_text(encoding="utf-8")
    assert "raise NotImplementedError" in source, "the demo-mode guard must remain"
    reset = source[source.index("async def reset("):]
    assert ".delete()" in reset, "reset() must actually delete something"


def test_reset_is_refused_outside_demo_mode():
    source = STORE.read_text(encoding="utf-8")
    reset = source[source.index("async def reset("):]
    guard = reset.index("if not self._demo_mode")
    first_delete = reset.index(".delete()")
    assert guard < first_delete, "the guard must precede any deletion"


def test_reset_covers_every_mission_subcollection():
    """Firestore has no recursive delete: a missed sub-collection leaves orphans."""
    import re as _re

    source = STORE.read_text(encoding="utf-8")
    declared = set(_re.findall(
        r'MISSION_SUBCOLLECTIONS = \((.*?)\)', source, _re.S)[0].replace('"', '').split())
    declared = {name.strip(",") for name in declared if name.strip(",")}
    written = set(_re.findall(r'_sub\([^,]+, "([a-z_]+)"', source))
    missing = written - declared
    assert not missing, f"reset() would leave orphans in {sorted(missing)}"


def test_every_module_using_a_logger_defines_one():
    """A NameError only surfaces when the line runs.

    `firestore_store.py` called `logger.info(...)` without defining `logger`.
    The syntax was valid, the imports were valid, and the failure waited for
    the one code path no test executed — reached for the first time in
    production, as a 500.
    """
    import ast as _ast

    offenders = []
    for directory in ("apps", "agents", "domain", "mock_enterprise", "scripts"):
        for path in sorted((ROOT / directory).rglob("*.py")):
            source = path.read_text(encoding="utf-8")
            if "logger." not in source:
                continue
            tree = _ast.parse(source)
            defined = any(
                isinstance(node, _ast.Assign)
                and any(getattr(t, "id", None) == "logger" for t in node.targets)
                for node in _ast.walk(tree)
            ) or any(
                isinstance(node, (_ast.Import, _ast.ImportFrom))
                and any(a.asname == "logger" or a.name == "logger"
                        for a in node.names)
                for node in _ast.walk(tree)
            ) or any(
                isinstance(node, _ast.arg) and node.arg == "logger"
                for node in _ast.walk(tree)
            )
            if not defined:
                offenders.append(str(path.relative_to(ROOT)))
    assert not offenders, f"`logger` used but never defined in: {offenders}"


# ---------------------------------------------------------------------------
# One client, one authentication path
#
# `_enterprise()` in the demo routes built its own `httpx.AsyncClient`. It knew
# nothing about Cloud Run identity tokens, so every demo control — reset,
# failure injection, hostile injection — was refused once deployed and surfaced
# as a bare 500. The authentication fix had been applied to
# `EnterpriseToolClient` only.
# ---------------------------------------------------------------------------
def test_no_route_builds_its_own_enterprise_client():
    """A second client is a second authentication path, and it will be forgotten."""
    for path in sorted((ROOT / "apps" / "api" / "routes").glob("*.py")):
        source = path.read_text(encoding="utf-8")
        code = "\n".join(
            line for line in source.splitlines()
            if not line.lstrip().startswith("#")
        )
        assert "httpx.AsyncClient(" not in code, (
            f"{path.name} builds its own HTTP client: it will not carry the "
            f"identity token the shared client acquires"
        )


def test_demo_controls_report_which_step_failed():
    """A bare 500 minutes before a recording says nothing about where to look."""
    demo = (ROOT / "apps" / "api" / "routes" / "demo.py").read_text(encoding="utf-8")
    assert "DemoControlFailed" in demo
    assert "Enterprise reset failed" in demo
    assert "Store reset failed" in demo
    assert "restricted to demo mode" in demo


def test_demo_control_error_follows_the_error_contract():
    from domain.errors import ACCError, DemoControlFailed

    assert issubclass(DemoControlFailed, ACCError)
    assert DemoControlFailed.code == "DEMO_CONTROL_FAILED"
    # `http_status`, not `status_code`: the contract's own attribute name.
    assert DemoControlFailed.http_status == 502


# ---------------------------------------------------------------------------
# The interface must not assert what it does not know
#
# The demo panel printed "deterministic" as a literal string. Deployed in
# `hybrid`, it displayed the wrong mode — and a two-minute run read as a
# performance problem rather than as evidence that a model was answering every
# step.
# ---------------------------------------------------------------------------
def test_the_agent_mode_badge_is_not_a_literal():
    controls = (ROOT / "apps" / "web" / "components" / "DemoControls.tsx").read_text(
        encoding="utf-8")
    code = "\n".join(
        line for line in controls.splitlines()
        if not line.lstrip().startswith(("*", "//", "/*"))
    )
    assert '>deterministic<' not in code, (
        "the badge must report the mode the control plane is running"
    )
    assert "agentMode" in code


def test_the_control_plane_exposes_the_agent_mode():
    policy = (ROOT / "apps" / "api" / "services" / "policy_engine.py").read_text(
        encoding="utf-8")
    assert '"agent_mode": self.settings.acc_agent_mode' in policy


def test_agent_mode_is_validated_at_deploy_time():
    """A typo in the variable must fail the plan, not the demo."""
    variables = (ROOT / "infrastructure" / "terraform" / "variables.tf").read_text(
        encoding="utf-8")
    block = variables[variables.index('variable "agent_mode"'):]
    assert "validation {" in block[:1200]
    assert 'contains(["adk", "hybrid", "deterministic"]' in block[:1200]
