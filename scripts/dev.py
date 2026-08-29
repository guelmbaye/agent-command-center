#!/usr/bin/env python3
"""Cross-platform development launcher.

Why this script rather than variables in the Makefile: the `VAR=value command`
syntax belongs to POSIX shells. On Windows, make delegates to `cmd.exe`, which
reads it as a non-existent command. Going through Python removes every shell
dependency — the same `make run` behaves identically on Windows, macOS and
Linux.

Usage:
    python scripts/dev.py api   [--port 8080] [--mock-port 8081] [--no-reload]
    python scripts/dev.py mock  [--port 8081]
    python scripts/dev.py web   [--api http://127.0.0.1:8080]
    python scripts/dev.py build [--api http://127.0.0.1:8080]
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "apps" / "web"


def run(command: list[str], cwd: Path, env: dict[str, str]) -> int:
    printable = " ".join(command)
    print(f"\033[94m▸\033[0m {printable}")
    print(f"  (dans {cwd})")
    try:
        return subprocess.call(command, cwd=str(cwd), env=env)
    except KeyboardInterrupt:
        return 0
    except FileNotFoundError:
        print(f"\033[91mCommande introuvable : {command[0]}\033[0m", file=sys.stderr)
        return 127


def serve_api(args: argparse.Namespace) -> int:
    env = os.environ.copy()
    # Pin the enterprise systems URL so that --mock-port is actually honoured;
    # otherwise the agents would call the default port.
    env["ACC_ENTERPRISE_BASE_URL"] = f"http://127.0.0.1:{args.mock_port}"
    command = [
        sys.executable, "-m", "uvicorn", "apps.api.main:app",
        "--host", args.host, "--port", str(args.port),
    ]
    if not args.no_reload:
        command.append("--reload")
    return run(command, ROOT, env)


def serve_mock(args: argparse.Namespace) -> int:
    command = [
        sys.executable, "-m", "uvicorn", "mock_enterprise.main:app",
        "--host", args.host, "--port", str(args.port), "--reload",
    ]
    return run(command, ROOT, os.environ.copy())


def _npm() -> str | None:
    """On Windows npm is a .cmd: bare `npm` is not executable."""
    return shutil.which("npm") or shutil.which("npm.cmd")


def _backend_api_key() -> str:
    """Read the API key exactly as the BACKEND sees it (including .env).

    Without this the key lives in two unlinked places: `ACC_API_KEY` on the
    backend and `NEXT_PUBLIC_ACC_API_KEY` on the frontend. Any divergence
    produces 401s on every route, with no clue as to the cause.
    """
    try:
        sys.path.insert(0, str(ROOT))
        from apps.api.core.config import Settings

        return Settings().acc_api_key
    except Exception:
        return os.environ.get("ACC_API_KEY", "")


def _web_env(api: str) -> dict[str, str]:
    env = os.environ.copy()
    # NEXT_PUBLIC_* is frozen at build time: it must be present in the npm
    # process environment, not only in a file.
    env["NEXT_PUBLIC_ACC_API"] = api

    # Single source of truth: the backend key is propagated to the frontend.
    if not env.get("NEXT_PUBLIC_ACC_API_KEY"):
        key = _backend_api_key()
        if key:
            env["NEXT_PUBLIC_ACC_API_KEY"] = key
            print(f"  API key taken from the backend ({key[:4]}...) — "
                  f"calls will be authenticated")
    return env


def serve_web(args: argparse.Namespace) -> int:
    npm = _npm()
    if npm is None:
        print("\033[91mnpm introuvable dans le PATH.\033[0m", file=sys.stderr)
        return 127
    if not (WEB / "node_modules").exists():
        print("\033[93mnode_modules absent — lancez d'abord « make web-install ».\033[0m")
        return 1
    print(f"  Control Plane cible : {args.api}")
    return run([npm, "run", "dev"], WEB, _web_env(args.api))


def build_web(args: argparse.Namespace) -> int:
    npm = _npm()
    if npm is None:
        print("\033[91mnpm introuvable dans le PATH.\033[0m", file=sys.stderr)
        return 127
    return run([npm, "run", "build"], WEB, _web_env(args.api))


def install_web(args: argparse.Namespace) -> int:
    npm = _npm()
    if npm is None:
        print("\033[91mnpm introuvable dans le PATH.\033[0m", file=sys.stderr)
        return 127
    return run([npm, "install"], WEB, os.environ.copy())


def typecheck_web(args: argparse.Namespace) -> int:
    npm = _npm()
    if npm is None:
        print("\033[91mnpm introuvable dans le PATH.\033[0m", file=sys.stderr)
        return 127
    if not (WEB / "node_modules").exists():
        print("\033[93mnode_modules absent — « make web-install » d'abord.\033[0m")
        return 1
    return run([npm, "run", "typecheck"], WEB, os.environ.copy())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    api = sub.add_parser("api", help="Control Plane ACC")
    api.add_argument("--port", type=int, default=8080)
    api.add_argument("--mock-port", type=int, default=8081)
    api.add_argument("--host", default="127.0.0.1")
    api.add_argument("--no-reload", action="store_true")
    api.set_defaults(func=serve_api)

    mock = sub.add_parser("mock", help="Systemes entreprise simules")
    mock.add_argument("--port", type=int, default=8081)
    mock.add_argument("--host", default="127.0.0.1")
    mock.set_defaults(func=serve_mock)

    web = sub.add_parser("web", help="Mission Control (dev)")
    web.add_argument("--api", default="http://127.0.0.1:8080")
    web.set_defaults(func=serve_web)

    build = sub.add_parser("build", help="Mission Control (production)")
    build.add_argument("--api", default="http://127.0.0.1:8080")
    build.set_defaults(func=build_web)

    sub.add_parser("install-web", help="npm install").set_defaults(func=install_web)
    sub.add_parser("typecheck", help="Verification de types").set_defaults(
        func=typecheck_web)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
