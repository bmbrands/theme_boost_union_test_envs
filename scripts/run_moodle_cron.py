#!/usr/bin/env python3
"""Trigger Moodle cron for every running test environment.

Reads the provisioner's ``infrastructure.yaml``, finds all Moodle
environments whose status is ``STARTED`` and fetches their public
``admin/cron.php`` endpoint (the same URL a browser-based cron would hit),
e.g. ``https://testsystem.moodle-an-hochschulen.de/bookit/5.2.0/admin/cron.php``.

Intended to be scheduled from the Plesk server cron, for example every
5 minutes::

    */5 * * * * /opt/boost-union-envs/backend/scripts/run_moodle_cron.py \
        --infra-file /opt/boost-union-envs/backend/example_pwd/infrastructure.yaml \
        >> /var/log/boost-union-cron.log 2>&1

Only depends on PyYAML (already a project dependency); no other third-party
packages are required.
"""

from __future__ import annotations

import argparse
import socket
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import yaml

# Default location of the provisioner's serialization file on the server.
DEFAULT_INFRA_FILE = (
    Path(__file__).resolve().parent.parent / "example_pwd" / "infrastructure.yaml"
)
# Status string the provisioner writes for a running environment.
RUNNING_STATUS = "STARTED"
CRON_PATH = "admin/cron.php"


def _log(message: str) -> None:
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    print(f"{timestamp}  {message}", flush=True)


def iter_running_envs(infra: dict) -> list[tuple[str, str, str]]:
    """Yield (infra_name, version, base_url) for every STARTED Moodle.

    ``base_url`` is taken verbatim from the infrastructure file; it is the
    public, externally reachable URL of the environment.
    """
    running: list[tuple[str, str, str]] = []
    for infra_name, infra_data in (infra or {}).items():
        if not isinstance(infra_data, dict):
            continue
        for version, moodle in (infra_data.get("moodles") or {}).items():
            if not isinstance(moodle, dict):
                continue
            if moodle.get("status") != RUNNING_STATUS:
                continue
            url = moodle.get("url")
            if not url:
                _log(f"skip {infra_name}/{version}: no url in infrastructure file")
                continue
            running.append((infra_name, str(version), str(url)))
    return running


def cron_url(base_url: str) -> str:
    return f"{base_url.rstrip('/')}/{CRON_PATH}"


def trigger_cron(url: str, timeout: float) -> tuple[bool, str]:
    """Fetch the cron URL. Returns (success, detail)."""
    request = urllib.request.Request(url, headers={"User-Agent": "boost-union-cron"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            status = response.status
            # Drain the body so the request fully completes server-side.
            response.read()
        return (200 <= status < 400, f"HTTP {status}")
    except urllib.error.HTTPError as exc:
        return (False, f"HTTP {exc.code}")
    except urllib.error.URLError as exc:
        return (False, f"connection error: {exc.reason}")
    except socket.timeout:
        return (False, "timeout")
    except OSError as exc:
        return (False, f"error: {exc}")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--infra-file",
        type=Path,
        default=DEFAULT_INFRA_FILE,
        help=f"path to infrastructure.yaml (default: {DEFAULT_INFRA_FILE})",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=120.0,
        help="per-request timeout in seconds (default: 120)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv if argv is not None else sys.argv[1:])

    if not args.infra_file.exists():
        _log(f"infrastructure file not found: {args.infra_file}")
        return 1

    try:
        infra = yaml.safe_load(args.infra_file.read_text()) or {}
    except yaml.YAMLError as exc:
        _log(f"failed to parse {args.infra_file}: {exc}")
        return 1

    running = iter_running_envs(infra)
    if not running:
        _log("no running (STARTED) environments found - nothing to do")
        return 0

    failures = 0
    for infra_name, version, base_url in running:
        url = cron_url(base_url)
        ok, detail = trigger_cron(url, args.timeout)
        status_word = "ok" if ok else "FAILED"
        _log(f"{status_word}: {infra_name}/{version} -> {url} ({detail})")
        if not ok:
            failures += 1

    _log(f"done: {len(running) - failures}/{len(running)} cron runs succeeded")
    # Non-zero exit if anything failed, so cron mail / monitoring can notice.
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
