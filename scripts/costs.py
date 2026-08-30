#!/usr/bin/env python3
"""ACC cost tracking — state of spending and of the guardrails.

Usage:
    python scripts/costs.py --project-id my-project
    python scripts/costs.py --project-id my-project --billing-account 0X0X-0X0X-0X0X
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys

BLUE, GREEN, WARN, DIM, RESET = (
    "\033[94m", "\033[92m", "\033[93m", "\033[2m", "\033[0m"
)


def section(title: str) -> None:
    print(f"\n{BLUE}── {title} ──{RESET}")


def ok(message: str) -> None:
    print(f"  {GREEN}✓{RESET} {message}")


def warn(message: str) -> None:
    print(f"  {WARN}▲{RESET} {message}")


def gcloud_json(gcloud: str, args: list[str]) -> list | dict | None:
    result = subprocess.run([gcloud, *args, "--format=json"],
                            capture_output=True, text=True, timeout=90)
    if result.returncode != 0 or not result.stdout.strip():
        return None
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-id", default=os.environ.get("PROJECT_ID"))
    parser.add_argument("--region",
                        default=os.environ.get("REGION", "europe-west1"))
    parser.add_argument("--billing-account",
                        default=os.environ.get("BILLING_ACCOUNT"))
    args = parser.parse_args()

    if not args.project_id:
        print("--project-id is required (or set PROJECT_ID).", file=sys.stderr)
        return 1

    gcloud = shutil.which("gcloud")
    if not gcloud:
        print("gcloud not found in PATH.", file=sys.stderr)
        return 1

    project = args.project_id

    # --- Budget ------------------------------------------------------------
    section("Budget and alerts")
    account = args.billing_account
    if not account:
        info = gcloud_json(gcloud, ["beta", "billing", "projects", "describe",
                                    project])
        if isinstance(info, dict):
            account = (info.get("billingAccountName") or "").replace(
                "billingAccounts/", "")

    if not account:
        warn("No billing account linked — the project cannot bill (nor run).")
    else:
        ok(f"Billing account: {account}")
        budgets = gcloud_json(gcloud, ["billing", "budgets", "list",
                                       f"--billing-account={account}"])
        if budgets:
            for budget in budgets:
                amount = (budget.get("amount", {})
                          .get("specifiedAmount", {}).get("units", "?"))
                rules = len(budget.get("thresholdRules", []))
                ok(f"{budget.get('displayName', '?')}: {amount} "
                   f"({rules} threshold rule(s))")
        else:
            warn("NO BUDGET SET. Create one before leaving anything running:")
            print(f"{DIM}     gcloud billing budgets create \\\n"
                  f"       --billing-account={account} \\\n"
                  f"       --display-name='ACC hackathon' \\\n"
                  f"       --budget-amount=40USD \\\n"
                  f"       --filter-projects='projects/{project}' \\\n"
                  f"       --threshold-rule=percent=0.5 \\\n"
                  f"       --threshold-rule=percent=0.9 \\\n"
                  f"       --threshold-rule=percent=1.0{RESET}")

    # --- Scaling guardrails ------------------------------------------------
    section("Scaling guardrails")
    services = gcloud_json(gcloud, ["run", "services", "list",
                                    f"--project={project}",
                                    f"--region={args.region}"])
    if not services:
        warn("No Cloud Run service deployed (or region mismatch).")
    else:
        for service in services:
            name = service.get("metadata", {}).get("name", "?")
            annotations = (service.get("spec", {}).get("template", {})
                           .get("metadata", {}).get("annotations", {}))
            minimum = annotations.get("autoscaling.knative.dev/minScale", "0")
            maximum = annotations.get("autoscaling.knative.dev/maxScale", "?")
            if minimum != "0":
                warn(f"{name}: minScale={minimum} — BILLS WHILE IDLE")
            else:
                ok(f"{name}: scales to zero, max {maximum}")

    # --- Volumetry ---------------------------------------------------------
    section("Firestore volumetry")
    print(f"{DIM}  Measured reference: 86 documents per hero mission,{RESET}")
    print(f"{DIM}  free tier 20 000 writes/day.{RESET}")

    section("Model calls")
    print(f"{DIM}  Measured reference: 7 calls per hero mission,{RESET}")
    print(f"{DIM}  ~700 input tokens each -> ~0.07 $ per mission{RESET}")
    print(f"{DIM}  with gemini-3.6-flash. Switch ACC_AGENT_MODE=deterministic{RESET}")
    print(f"{DIM}  between rehearsals: zero tokens, governance still shown.{RESET}")

    # --- Billing reports ---------------------------------------------------
    section("Billing breakdown")
    print(f"{DIM}  Console -> Billing -> Reports{RESET}")
    print(f"{DIM}    Group by: Label -> app: acc      (per component){RESET}")
    print(f"{DIM}    Group by: SKU                    (Gemini / Model Armor share){RESET}")
    print(f"{DIM}  Labels appear after roughly 24 h of collection.{RESET}")

    print(f"\n{DIM}  Teardown: python scripts/teardown.py "
          f"--project-id {project}{RESET}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
