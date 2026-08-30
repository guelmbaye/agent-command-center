#!/usr/bin/env python3
"""Full ACC teardown — brings billing back to zero.

The only reliable way to stop costs after the hackathon.

Usage:
    python scripts/teardown.py --project-id my-project
    python scripts/teardown.py --project-id my-project --yes   # no prompt
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TERRAFORM_DIR = ROOT / "infrastructure" / "terraform"

BLUE, RED, DIM, RESET = "\033[94m", "\033[91m", "\033[2m", "\033[0m"


def step(message: str) -> None:
    print(f"\n{BLUE}▸ {message}{RESET}")


def run(command: list[str], cwd: Path = ROOT, check: bool = False) -> int:
    print(f"{DIM}  $ {' '.join(command)}{RESET}")
    code = subprocess.call(command, cwd=str(cwd))
    if check and code != 0:
        print(f"{RED}  command failed (exit {code}){RESET}", file=sys.stderr)
    return code


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-id", default=os.environ.get("PROJECT_ID"))
    parser.add_argument("--region",
                        default=os.environ.get("REGION", "europe-west1"))
    parser.add_argument("--yes", action="store_true",
                        help="skip the typed confirmation")
    args = parser.parse_args()

    if not args.project_id:
        print(f"{RED}--project-id is required (or set PROJECT_ID).{RESET}",
              file=sys.stderr)
        return 1

    gcloud = shutil.which("gcloud")
    terraform = shutil.which("terraform")
    if not gcloud or not terraform:
        print(f"{RED}gcloud and terraform must both be in PATH.{RESET}",
              file=sys.stderr)
        return 1

    print(f"{RED}⚠ This destroys all ACC infrastructure in project "
          f"{args.project_id}{RESET}")
    if not args.yes:
        typed = input("Type the project name to confirm: ").strip()
        if typed != args.project_id:
            print("Cancelled.")
            return 1

    step("Lifting Firestore delete protection")
    # Terraform cannot destroy the database while protection is on.
    if run([gcloud, "firestore", "databases", "update", "--database=(default)",
            "--no-delete-protection", f"--project={args.project_id}"]) != 0:
        print(f"{DIM}  (already lifted, or no database){RESET}")

    step("Destroying the infrastructure")
    run([terraform, "destroy", "-auto-approve",
         "-var", f"project_id={args.project_id}",
         "-var", f"region={args.region}",
         "-var", "image_api=unused",
         "-var", "image_mock=unused",
         "-var", "image_web=unused"], cwd=TERRAFORM_DIR)

    step("Remaining billable resources")
    run([gcloud, "run", "services", "list", f"--project={args.project_id}",
         "--format=table(name,region)"])
    run([gcloud, "artifacts", "repositories", "list",
         f"--project={args.project_id}",
         "--format=table(name,format,sizeBytes)"])

    print(f"""
What can still bill after a destroy:
  · Artifact Registry images (storage)
      gcloud artifacts repositories delete acc \\
        --location={args.region} --project={args.project_id}
  · Logs retained in Cloud Logging (30-day default, usually free)
  · The Firestore database if protection could not be lifted

Nuclear option, guaranteed zero:
  gcloud projects delete {args.project_id}
""")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
