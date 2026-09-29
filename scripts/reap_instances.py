#!/usr/bin/env python3
"""Automatically stop long-running and clean up long-idle Moodle test instances.

This is the periodic *reaper* for work package 3 ("automated processes"). It is
intended to be scheduled from system cron on the server, run **from the backend
directory** (so ``config.yml`` / the active ``env.*.yml`` resolve), for example
every 15 minutes::

    */15 * * * * cd /opt/boost-union-envs/backend && \
        /opt/boost-union-envs/venv/bin/python scripts/reap_instances.py \
        >> /var/log/boost-union-reap.log 2>&1

Behaviour is driven entirely by the ``lifecycle`` block in the working
directory's ``settings.yaml`` and is **disabled by default**: nothing is stopped
or destroyed until an administrator opts in. All timestamps are treated as UTC.

Use ``--dry-run`` to preview the actions without changing anything.
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone

# The application resolves its active ``env.*.yml`` relative to ``sys.path[0]``
# and its ``config.yml`` relative to the current working directory, so both must
# point at the backend directory. Cron is expected to ``cd`` there first; align
# ``sys.path[0]`` with the working directory to match (the package itself is
# imported from the installed environment).
sys.path[0] = os.getcwd()

from theme_boost_union_test_envs.app import Application  # noqa: E402
from theme_boost_union_test_envs.domain import lifecycle  # noqa: E402


def _log(message: str) -> None:
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    print(f"{timestamp}  {message}", flush=True)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="report the actions that would be taken without changing anything",
    )
    parser.add_argument(
        "--now",
        type=str,
        default="",
        help="override the current time (ISO-8601, UTC) for testing",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv if argv is not None else sys.argv[1:])

    now: datetime | None = None
    if args.now:
        try:
            now = datetime.fromisoformat(args.now)
        except ValueError:
            _log(f"invalid --now value: {args.now!r} (expected ISO-8601)")
            return 2

    # Build the DI container so core + the yaml parser + config are available.
    app = Application()
    app.wire(packages=["theme_boost_union_test_envs"])
    core = app.core()
    parser = app.cross_cutting_concerns.infrastructure_yaml_parser()

    policy = lifecycle.load_policy()
    if not policy.auto_stop_enabled and not policy.auto_cleanup_enabled:
        _log(
            "lifecycle automation is disabled "
            "(set lifecycle.auto_stop_enabled / auto_cleanup_enabled in "
            "settings.yaml to enable) - nothing to do"
        )
        return 0

    try:
        testbed_info = parser.load_testbed_info()
    except FileNotFoundError:
        _log("no infrastructure.yaml found - nothing to do")
        return 0

    actions = lifecycle.plan_actions(dict(testbed_info), policy, now)
    if not actions:
        _log("no instances match the lifecycle policy - nothing to do")
        return 0

    summary = lifecycle.execute(
        actions,
        core,
        dry_run=args.dry_run,
        logger=_log,
    )

    _log(
        "done: "
        f"stopped={summary.stopped} destroyed={summary.destroyed} "
        f"torn_down={summary.torn_down} failures={summary.failures} "
        f"(planned {len(summary.planned)}{', dry-run' if args.dry_run else ''})"
    )
    return 1 if summary.failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
