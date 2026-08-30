#!/usr/bin/env python3
"""ACC local installation diagnostic.

Answers "why does Mission Control not see the backend?" without sending anyone
digging through logs. Works on Windows, macOS and Linux.

Usage:  python scripts/doctor.py
        python scripts/doctor.py --api http://127.0.0.1:8080
"""
from __future__ import annotations

import argparse
import json
import os
import socket
import time
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

OK, WARN, BAD = "  [OK]   ", "  [!]    ", "  [FAIL] "
problems: list[str] = []


def report(level: str, message: str, hint: str = "") -> None:
    print(f"{level} {message}")
    if hint:
        print(f"          -> {hint}")
    if level is BAD:
        problems.append(message)


def probe_port(host: str, port: int, family: int) -> bool:
    """Test whether anything is listening, IPv4 and IPv6 separately."""
    try:
        with socket.socket(family, socket.SOCK_STREAM) as sock:
            sock.settimeout(1.0)
            return sock.connect_ex((host, port)) == 0
    except OSError:
        return False


def fetch(url: str, timeout: float = 4.0,
          headers: dict[str, str] | None = None) -> tuple[int, str, dict | None, str]:
    """Return (status, body, json, server).

    The `Server` header is the single most useful piece of diagnostic data: it
    names the process that intercepted the call (llama.cpp, Apache, ...).
    """
    request = urllib.request.Request(
        url, headers={"Accept": "application/json", **(headers or {})})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8", "replace")
            server = response.headers.get("Server", "")
            try:
                return response.status, raw, json.loads(raw), server
            except json.JSONDecodeError:
                return response.status, raw, None, server
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", "replace")
        server = exc.headers.get("Server", "") if exc.headers else ""
        try:
            return exc.code, raw, json.loads(raw), server
        except json.JSONDecodeError:
            return exc.code, raw, None, server
    except Exception as exc:  # connexion refusée, DNS, timeout
        return 0, str(exc), None, ""


# Frequent squatters on port 8080, with their characteristic Server header.
KNOWN_SQUATTERS = {
    "llama.cpp": "a llama.cpp server (its default port IS 8080)",
    "apache": "Apache, often via XAMPP",
    "nginx": "nginx",
    "microsoft-iis": "IIS",
    "jetty": "Jetty",
    "coyote": "Tomcat",
    "werkzeug": "a Flask development server",
    "kestrel": "an ASP.NET application",
}


def port_holders(port: int) -> list[str]:
    """Best-effort list of the processes holding the port, per platform."""
    import subprocess

    # `text=True` decodes with the local encoding: on Windows, cp1252 fails on
    # unmapped bytes in netstat output (UnicodeDecodeError inside a subprocess
    # reader thread). So we decode ourselves, tolerantly.
    def _capture(command: list[str]) -> str:
        result = subprocess.run(command, capture_output=True, timeout=8)
        return result.stdout.decode("utf-8", errors="replace")

    try:
        if sys.platform.startswith("win"):
            out = _capture(["netstat", "-ano"])
            return [l.strip() for l in out.splitlines()
                    if f":{port}" in l and "LISTENING" in l.upper()]
        out = _capture(["ss", "-ltnp"])
        return [l.strip() for l in out.splitlines() if f":{port}" in l]
    except Exception:
        return []


def check_ports(port: int) -> None:
    print(f"\n-- Port {port} --")
    v4 = probe_port("127.0.0.1", port, socket.AF_INET)
    v6 = probe_port("::1", port, socket.AF_INET6)

    holders = port_holders(port)
    if len(holders) > 1:
        # Windows trap: without SO_EXCLUSIVEADDRUSE several processes can bind
        # the SAME address:port. Uvicorn then prints "running" without ever
        # receiving a request — another process is receiving them.
        report(BAD, f"{len(holders)} processes hold 127.0.0.1:{port}",
               "On Windows several processes can bind the same port: uvicorn may "
               "look started while receiving nothing. Stop the others, or run "
               "ACC on a free port.")
        for line in holders[:5]:
            print(f"          {line}")

    if v4 and v6:
        report(WARN, f"Two stacks are listening: 127.0.0.1:{port} AND [::1]:{port}",
               "On Windows the browser picks ::1 for localhost. "
               "Use http://127.0.0.1 in NEXT_PUBLIC_ACC_API.")
    elif v4:
        report(OK, f"127.0.0.1:{port} is listening (IPv4)")
    elif v6:
        report(BAD, f"Only [::1]:{port} is listening — that is not uvicorn",
               "Another server holds the port. "
               "Windows: netstat -ano | findstr :" + str(port))
    else:
        report(BAD, f"Nothing is listening on port {port}", "Run 'make run'.")


def check_identity(base: str) -> bool:
    """True only if ACC answers. Otherwise testing routes is pointless."""
    print(f"\n-- Service identity on {base} --")
    status, raw, payload, server = fetch(f"{base}/healthz")

    if status == 0:
        report(BAD, f"Unreachable: {raw}", "Is the backend running? 'make run'")
        return False

    is_acc = bool(payload) and (
        payload.get("service") == "acc-api"
        or (payload.get("status") == "ok" and "agent_mode" in payload)
    )
    if is_acc:
        report(OK, "This is the ACC Control Plane")
        for key in ("env", "persistence", "event_bus", "agent_mode",
                    "model_armor", "demo_mode"):
            if key in payload:
                print(f"          {key:<14}= {payload.get(key)}")
        if "agent_mode" not in payload:
            print("          (cloud mode: /healthz stays minimal on purpose)")
        return True

    identified = ""
    for signature, description in KNOWN_SQUATTERS.items():
        if signature in server.lower():
            identified = description
            break

    if identified:
        report(BAD, f"This port is held by {identified}",
               f"Server header: {server}. Stop that service, or run ACC "
               f"elsewhere: make run PORT=8099")
    else:
        extract = raw[:110].replace("\n", " ")
        report(BAD, f"This is NOT ACC (HTTP {status})"
                    + (f", Server: {server}" if server else ""),
               f"Response received: {extract} — stop that service or run ACC "
               f"elsewhere: make run PORT=8099")
    return False


def check_routes(base: str) -> None:
    print(f"\n-- API routes --")
    unauthorized: list[str] = []
    for path in ("/api/v1/policy", "/api/v1/agents", "/api/v1/metrics",
                 "/api/v1/missions"):
        status, raw, payload, _ = fetch(f"{base}{path}")
        if status == 200:
            healthy_routes += 1
            report(OK, f"{path} -> 200")
        elif status == 401:
            # A single root cause: print the remedy only once.
            unauthorized.append(path)
            print(f"{BAD} {path} -> 401")
        elif status == 404 and payload is None:
            report(BAD, f"{path} -> 404 hors contrat ACC",
                   "Réponse d'un serveur tiers, pas d'ACC.")
        else:
            report(BAD, f"{path} -> {status}", raw[:100])

    if unauthorized:
        source = _api_key_source()
        if source == "environment":
            remedy = ("An ACC_API_KEY ENVIRONMENT variable is active — it takes "
                      "precedence over .env, even if the line is commented "
                      "out there. Remove it: PowerShell "
                      "'Remove-Item Env:ACC_API_KEY', cmd 'set ACC_API_KEY=', "
                      "bash 'unset ACC_API_KEY'. Then run 'make run' again.")
        elif source == ".env":
            remedy = ("ACC_API_KEY is set in .env. Comment it out for local use, "
                      "or let 'make web' propagate the key.")
        else:
            remedy = ("Key origin undetermined: check the environment of the "
                      "process running uvicorn.")
        report(BAD, f"{len(unauthorized)} routes require an API key", remedy)


def check_cors(base: str, origin: str = "http://localhost:3000") -> None:
    """The browser sends an OPTIONS preflight before any cross-origin call.

    A backend reachable with curl can be entirely unreachable from Mission
    Control if this header is missing — curl itself ignores CORS.
    """
    print(f"\n-- CORS (origin {origin}) --")
    import urllib.request
    request = urllib.request.Request(f"{base}/api/v1/agents", method="OPTIONS")
    request.add_header("Origin", origin)
    request.add_header("Access-Control-Request-Method", "GET")
    try:
        with urllib.request.urlopen(request, timeout=4) as response:
            allowed = response.headers.get("Access-Control-Allow-Origin")
    except urllib.error.HTTPError as exc:
        allowed = exc.headers.get("Access-Control-Allow-Origin") if exc.headers else None
    except Exception as exc:
        report(BAD, f"Preflight failed: {exc}")
        return

    if allowed in (origin, "*"):
        report(OK, f"Preflight allowed ({allowed})")
    elif allowed:
        report(WARN, f"Unexpected origin returned: {allowed}")
    else:
        report(BAD, "No Access-Control-Allow-Origin header",
               "The browser will block every call. Check ACC_CORS_ORIGINS and "
               "ACC_CORS_ORIGIN_REGEX, or that ACC is really answering.")


def _api_key_source() -> str:
    """Reuse the backend detection so both speak the same language."""
    try:
        sys.path.insert(0, str(ROOT))
        from apps.api.core.config import api_key_source

        return api_key_source()
    except Exception:
        return "environment" if os.environ.get("ACC_API_KEY") else ""


def check_frontend_config(base: str) -> None:
    print("\n-- Mission Control configuration --")
    env_local = ROOT / "apps" / "web" / ".env.local"
    if not env_local.exists():
        report(WARN, "apps/web/.env.local missing",
               f"The frontend will use {base} by default. Copy "
               ".env.local.example if you need to change it.")
        return

    configured = ""
    for line in env_local.read_text(encoding="utf-8").splitlines():
        if line.strip().startswith("NEXT_PUBLIC_ACC_API="):
            configured = line.split("=", 1)[1].strip()

    if not configured:
        report(WARN, "NEXT_PUBLIC_ACC_API not set in .env.local")
    elif "localhost" in configured:
        report(WARN, f"NEXT_PUBLIC_ACC_API = {configured}",
               "Replace localhost with 127.0.0.1: on Windows, localhost "
               "resolves to IPv6 and may reach another service.")
    else:
        report(OK, f"NEXT_PUBLIC_ACC_API = {configured}")

    print("          Reminder: this value is frozen AT BUILD TIME. "
          "Restart 'make web' after changing it.")


def check_enterprise(url: str, acc_running: bool) -> None:
    print(f"\n-- Simulated enterprise systems ({url}) --")
    status, raw, payload, _ = fetch(f"{url}/healthz")
    if payload and payload.get("status") == "ok":
        report(OK, f"Reachable ({payload.get('suppliers')} suppliers)")
    elif status == 0:
        # If the control plane is running, a missing mock is not a warning:
        # NO mission can complete. Reporting it as non-blocking would produce
        # an "all clear" in front of a system that cannot work.
        level = BAD if acc_running else WARN
        report(level, "Unreachable — no mission can complete",
               "Run 'make run-mock' in a second terminal. Without it every "
               "supplier call fails and missions go straight to recovery.")
    else:
        report(BAD, f"Unexpected response (HTTP {status}): {raw[:80]}")


def is_remote(base: str) -> bool:
    """A deployed target has nothing local to check.

    Checking port 80, `apps/web/.env.local` and a local enterprise mock against
    a Cloud Run URL produces three failures that say nothing about the
    deployment — and buries the one line that matters.
    """
    return base.startswith("https://") or ".run.app" in base


# A Cloud Run instance scaled to zero takes several seconds to boot. The first
# request pays for it: 4 s is a local timeout, not a cold-start one.
REMOTE_TIMEOUT = 25.0


def wake_up(base: str) -> tuple[int, str, dict | None, str]:
    """First contact with a service that may be scaled to zero.

    Until an instance is ready, Cloud Run answers the caller itself — with its
    own HTML page. Reading that as "this is not ACC" was wrong: the service was
    fine, it was asleep. So the first call is retried before any verdict.
    """
    for attempt in range(1, 4):
        result = fetch(f"{base}/healthz", timeout=REMOTE_TIMEOUT)
        status, raw, payload, _ = result
        if payload or status not in (0, 404, 429, 502, 503):
            return result
        if attempt < 3:
            print(f"          cold start, retrying ({attempt}/3)...")
            time.sleep(4)
    return result


def _check_remote_preflight(base: str, origin: str) -> None:
    """The one thing curl never tells you by accident.

    A browser sends an OPTIONS preflight before any cross-origin call. `curl`
    does not, so an API can answer every GET perfectly and still be unusable
    from Mission Control. This check reproduces exactly what the browser does,
    and reports what came back.
    """
    if not origin:
        origin = base.replace("acc-api", "acc-web")

    print(f"\n-- CORS preflight (origin {origin}) --")
    request = urllib.request.Request(
        f"{base}/api/v1/missions", method="OPTIONS",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type,x-api-key",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=REMOTE_TIMEOUT) as response:
            status, headers = response.status, dict(response.headers)
    except urllib.error.HTTPError as exc:
        status, headers = exc.code, dict(exc.headers)
    except Exception as exc:
        report(BAD, f"Preflight failed: {exc}")
        return

    allowed = headers.get("Access-Control-Allow-Origin")
    server = headers.get("Server", "")
    if allowed == origin or allowed == "*":
        report(OK, f"Preflight allowed (HTTP {status}, origin echoed)")
        return

    if status == 404:
        report(BAD, f"Preflight -> HTTP 404, Server: {server or 'unknown'}",
               "The OPTIONS request did not reach the container. Confirm with:\n"
               "          gcloud run services logs read acc-api "
               "--region=REGION --limit=20\n"
               "          If no OPTIONS line appears, the request stops before "
               "the app.")
        return

    report(BAD, f"Preflight -> HTTP {status}, no Access-Control-Allow-Origin",
           f"Server: {server or 'unknown'}. The app answered but refused the "
           f"origin: check ACC_CORS_ORIGIN_REGEX against {origin}")


def check_remote_service(base: str, api_key: str, origin: str = "") -> None:
    """What actually matters on a deployed instance."""
    print(f"\n-- Deployed service {base} --")
    probe_failed = False
    status, raw, payload, server = wake_up(base)

    if payload and payload.get("service") == "acc-api":
        report(OK, "ACC Control Plane is answering")
        for key in ("env", "persistence", "event_bus", "agent_mode",
                    "model_armor", "demo_mode"):
            if key in payload:
                print(f"          {key:<14}= {payload.get(key)}")
    elif status == 0:
        report(BAD, f"Unreachable: {raw}")
    elif status == 404 and "<html" in raw.lower():
        # Deliberately NOT a blocking verdict yet. If the /api/v1 routes below
        # answer, the service is demonstrably up and only this probe is odd —
        # declaring the whole deployment broken on one failing check, while
        # four others pass, is how a diagnostic misleads.
        probe_failed = True
        report(WARN, "/healthz answers with Cloud Run's own HTML page",
               "Checking the API routes before drawing any conclusion.\n"
               "          To see the raw answer:\n"
               f"          curl -i {base}/healthz")
    elif status in (401, 403):
        report(BAD, f"HTTP {status} on /healthz",
               "The probe must stay open. Check that api_public grants "
               "roles/run.invoker to allUsers.")
    else:
        report(BAD, f"Unexpected response (HTTP {status})", raw[:120])
        return

    print(f"\n-- API routes --")
    headers = {"x-api-key": api_key} if api_key else {}
    healthy_routes = 0
    if not api_key:
        report(WARN, "No API key provided",
               "Deployed routes require one:\n"
               "          $env:ACC_API_KEY = gcloud secrets versions access "
               "latest --secret=acc-api-key --project=PROJECT\n"
               "          python scripts/doctor.py --api URL")
        return

    for path in ("/api/v1/policy", "/api/v1/agents", "/api/v1/metrics",
                 "/api/v1/missions"):
        status, raw, payload, _ = fetch(f"{base}{path}", timeout=REMOTE_TIMEOUT,
                                        headers=headers)
        if status == 200:
            healthy_routes += 1
            report(OK, f"{path} -> 200")
        elif status == 401:
            report(BAD, f"{path} -> 401",
                   "The key does not match the deployed secret. Read it again "
                   "with `gcloud secrets versions access latest "
                   "--secret=acc-api-key`.")
        else:
            report(BAD, f"{path} -> {status}", raw[:100])

    _check_remote_preflight(base, origin)

    if probe_failed and healthy_routes:
        print(f"\n{OK} The service IS serving: {healthy_routes}/4 API routes "
              f"answered 200.")
        print("          Only /healthz is odd. ACC is usable; the Cloud Run "
              "startup")
        print("          probe targets that same path and passed, so the "
              "container")
        print("          answers it internally. Investigate later, not now.")
    elif probe_failed:
        report(BAD, "No route answered",
               "The service is genuinely unreachable. Check:\n"
               "          gcloud run services describe acc-api "
               "--region=REGION --format='value(status.url)'\n"
               "          gcloud run services describe acc-api "
               "--region=REGION --format='value(status.conditions)'")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api", default="http://127.0.0.1:8080")
    parser.add_argument("--enterprise", default="http://127.0.0.1:8081")
    parser.add_argument("--origin", default="",
                        help="browser origin to test the CORS preflight with "
                             "(defaults to the acc-web URL)")
    parser.add_argument("--api-key", default=os.environ.get("ACC_API_KEY", ""),
                        help="required for the deployed /api/v1 routes")
    args = parser.parse_args()

    print("=" * 66)
    print("  ACC — local installation diagnostic")
    print("=" * 66)

    if is_remote(args.api):
        check_remote_service(args.api, args.api_key, args.origin)
        print("\n" + "=" * 66)
        if problems:
            print(f"  {len(problems)} blocking problem(s):")
            for problem in problems:
                print(f"    - {problem}")
            return 1
        print("  No blocking problem detected.")
        return 0

    port = int(args.api.rsplit(":", 1)[-1]) if ":" in args.api.rsplit("/", 1)[-1] else 80
    check_ports(port)
    acc_running = False
    # Checks cascade: if the service is not ACC, testing routes would only
    # produce noise derived from a single root cause.
    if check_identity(args.api):
        acc_running = True
        check_routes(args.api)
        check_cors(args.api)
    else:
        print("\n-- Routes de l'API --")
        print("  [...]    skipped: the service was not identified as ACC")
    check_frontend_config(args.api)
    check_enterprise(args.enterprise, acc_running)

    print("\n" + "=" * 66)
    if problems:
        print(f"  {len(problems)} blocking problem(s):")
        for item in problems:
            print(f"    - {item}")
        return 1
    print("  No blocking problem detected.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
