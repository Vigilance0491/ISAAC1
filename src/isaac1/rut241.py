"""RUT241 diagnostics used during ISAAC1 field setup."""

from __future__ import annotations

import argparse
import json
import subprocess
from dataclasses import asdict, dataclass
from typing import Sequence


DEFAULT_RUT241_HOST = "192.168.1.1"
DEFAULT_RUT241_USER = "root"


@dataclass(frozen=True)
class CheckResult:
    name: str
    command: str
    ok: bool
    stdout: str
    stderr: str


RUT241_CHECKS: tuple[tuple[str, str], ...] = (
    ("device_board", "ubus call system board"),
    ("sim_inserted", "gsmctl -z"),
    ("pin_state", "gsmctl -u"),
    ("operator", "gsmctl -o"),
    ("signal", "gsmctl -q"),
    ("default_route", "ip route show default"),
    ("internet_ping", "ping -c 3 1.1.1.1"),
)


def run_ssh_check(
    host: str,
    user: str,
    remote_command: str,
    timeout_seconds: int,
) -> CheckResult:
    target = f"{user}@{host}"
    command = [
        "ssh",
        "-o",
        "BatchMode=yes",
        "-o",
        f"ConnectTimeout={timeout_seconds}",
        target,
        remote_command,
    ]
    completed = subprocess.run(
        command,
        capture_output=True,
        check=False,
        text=True,
        timeout=timeout_seconds + 10,
    )
    return CheckResult(
        name="",
        command=remote_command,
        ok=completed.returncode == 0,
        stdout=completed.stdout.strip(),
        stderr=completed.stderr.strip(),
    )


def run_rut241_checks(host: str, user: str, timeout_seconds: int) -> list[CheckResult]:
    results: list[CheckResult] = []
    for name, remote_command in RUT241_CHECKS:
        result = run_ssh_check(host, user, remote_command, timeout_seconds)
        results.append(
            CheckResult(
                name=name,
                command=result.command,
                ok=result.ok,
                stdout=result.stdout,
                stderr=result.stderr,
            )
        )
    return results


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="isaac1",
        description="ISAAC1 RUT241 setup and diagnostic tools.",
    )
    subparsers = parser.add_subparsers(dest="command")

    check = subparsers.add_parser(
        "rut241-check",
        help="Check RUT241 SIM, signal, route, and internet status over SSH.",
    )
    check.add_argument("--host", default=DEFAULT_RUT241_HOST)
    check.add_argument("--user", default=DEFAULT_RUT241_USER)
    check.add_argument("--timeout", type=int, default=10)
    check.add_argument("--json", action="store_true", help="Print machine-readable JSON.")

    control = subparsers.add_parser(
        "control-ui",
        help="Run the local three-button ISAAC1 control UI.",
    )
    control.add_argument("--bind", default="127.0.0.1")
    control.add_argument("--port", type=int, default=8765)
    control.add_argument("--rut-url", default=None)
    control.add_argument("--token-env", default="ISAAC1_CONTROL_TOKEN")
    control.add_argument("--sound-file-id", type=int, default=20)

    return parser


def print_human_results(results: Sequence[CheckResult]) -> None:
    for result in results:
        status = "PASS" if result.ok else "FAIL"
        print(f"[{status}] {result.name}: {result.command}")
        if result.stdout:
            print(result.stdout)
        if result.stderr:
            print(result.stderr)


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "rut241-check":
        results = run_rut241_checks(args.host, args.user, args.timeout)
        if args.json:
            print(json.dumps([asdict(result) for result in results], indent=2))
        else:
            print_human_results(results)
        return 0 if all(result.ok for result in results) else 1

    if args.command == "control-ui":
        from isaac1.control_server import DEFAULT_RUT241_URL, main as control_main

        control_args = [
            "--bind",
            args.bind,
            "--port",
            str(args.port),
            "--rut-url",
            args.rut_url or DEFAULT_RUT241_URL,
            "--token-env",
            args.token_env,
            "--sound-file-id",
            str(args.sound_file_id),
        ]
        return control_main(control_args)

    parser.print_help()
    return 0
