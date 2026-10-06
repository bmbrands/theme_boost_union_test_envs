"""Automated instance-lifecycle management (work package 3).

This module holds the *decision logic* for reaping Moodle test instances:

- :func:`load_policy` reads the admin-configurable policy from ``settings.yaml``.
- :func:`plan_actions` is a **pure** function: given the testbed state, a policy
  and the current time, it returns the list of stop/destroy/teardown actions to
  perform. It performs no I/O and touches no Docker, so it is trivially testable.
- :func:`execute` applies a list of actions using the existing ``core`` lifecycle
  methods (or reports them, in dry-run mode).

The reaper is intended to be driven periodically by ``scripts/reap_instances.py``
from system cron. Automation is **disabled by default**: nothing is stopped or
destroyed until an administrator opts in via ``settings.yaml``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, time, timedelta, timezone
from typing import Any, Callable

# Status strings the provisioner writes into infrastructure.yaml.
STATUS_STARTED = "STARTED"
STATUS_STOPPED = "STOPPED"
# Provisioned but never started; idle just like a stopped instance.
STATUS_CREATED = "CREATED"


# ---------------------------------------------------------------------------
# Policy
# ---------------------------------------------------------------------------


@dataclass
class LifecyclePolicy:
    """Admin-configurable lifecycle policy. Safe, automation-off defaults."""

    auto_stop_enabled: bool = False
    max_runtime_minutes: int = 480  # 8 hours
    daily_stop_time: str = ""  # "HH:MM" (UTC); empty disables
    auto_cleanup_enabled: bool = False
    stopped_retention_days: int = 7
    cleanup_empty_infrastructures: bool = True


def policy_from_values(values: dict[str, Any] | None) -> LifecyclePolicy:
    """Build a policy from a settings ``values`` dict's ``lifecycle`` block.

    Unknown/absent keys fall back to the dataclass defaults; malformed values
    are ignored in favour of the default so a bad setting never disables safety.
    """
    block: dict[str, Any] = {}
    if isinstance(values, dict):
        candidate = values.get("lifecycle")
        if isinstance(candidate, dict):
            block = candidate

    defaults = LifecyclePolicy()

    def _bool(key: str, default: bool) -> bool:
        v = block.get(key, default)
        if isinstance(v, bool):
            return v
        if isinstance(v, str):
            return v.strip().lower() in ("1", "true", "yes", "on")
        return default

    def _int(key: str, default: int) -> int:
        v = block.get(key, default)
        try:
            return int(v)
        except (TypeError, ValueError):
            return default

    def _str(key: str, default: str) -> str:
        v = block.get(key, default)
        return v if isinstance(v, str) else default

    return LifecyclePolicy(
        auto_stop_enabled=_bool("auto_stop_enabled", defaults.auto_stop_enabled),
        max_runtime_minutes=_int("max_runtime_minutes", defaults.max_runtime_minutes),
        daily_stop_time=_str("daily_stop_time", defaults.daily_stop_time),
        auto_cleanup_enabled=_bool(
            "auto_cleanup_enabled", defaults.auto_cleanup_enabled
        ),
        stopped_retention_days=_int(
            "stopped_retention_days", defaults.stopped_retention_days
        ),
        cleanup_empty_infrastructures=_bool(
            "cleanup_empty_infrastructures", defaults.cleanup_empty_infrastructures
        ),
    )


def load_policy() -> LifecyclePolicy:
    """Load the lifecycle policy from ``<working_dir>/settings.yaml``."""
    from ..cross_cutting import settings_store

    return policy_from_values({"lifecycle": settings_store.get_section("lifecycle")})


def save_policy(policy: LifecyclePolicy) -> None:
    """Persist ``policy`` as the ``lifecycle`` section of ``settings.yaml``."""
    from dataclasses import asdict

    from ..cross_cutting import settings_store

    settings_store.set_section("lifecycle", asdict(policy))


# ---------------------------------------------------------------------------
# Planning (pure)
# ---------------------------------------------------------------------------


@dataclass
class Action:
    """A single lifecycle action the reaper should perform."""

    kind: str  # "stop" | "destroy" | "teardown" | "notify"
    infrastructure: str
    version: str | None = None
    reason: str = ""
    # For "notify": the deletion time being warned about (naive UTC).
    deadline: datetime | None = None


def _parse_ts(value: Any) -> datetime | None:
    """Parse a stored timestamp into a naive-UTC datetime, or None.

    Tolerates both the ``"%Y-%m-%d %H:%M:%S"`` form (infra/started/stopped) and
    ISO-8601 (moodle ``created_at``), with or without a timezone.
    """
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    parsed: datetime | None = None
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
            try:
                parsed = datetime.strptime(text, fmt)
                break
            except ValueError:
                continue
    if parsed is None:
        return None
    # Normalise to naive UTC for consistent comparison.
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


def _first_ts(*values: Any) -> datetime | None:
    for v in values:
        ts = _parse_ts(v)
        if ts is not None:
            return ts
    return None


def _parse_hhmm(value: str) -> time | None:
    try:
        hh, mm = value.strip().split(":", 1)
        return time(int(hh), int(mm))
    except (ValueError, AttributeError):
        return None


def _next_daily_boundary(after: datetime, stop_time: time) -> datetime:
    """First occurrence of ``stop_time`` strictly after ``after`` (naive UTC)."""
    candidate = datetime.combine(after.date(), stop_time)
    if candidate <= after:
        candidate += timedelta(days=1)
    return candidate


@dataclass
class Deadlines:
    """When an instance will be auto-stopped / auto-destroyed (naive UTC).

    ``stop_reason`` is ``"runtime"`` or ``"daily"`` depending on which limit
    determines ``auto_stop_at``.
    """

    auto_stop_at: datetime | None = None
    stop_reason: str = ""
    started: datetime | None = None
    auto_delete_at: datetime | None = None
    stopped: datetime | None = None


# Key on a moodle record holding the deletion deadline (ISO) that a warning
# email was already sent for, so each stop cycle is warned about only once.
WARNING_SENT_KEY = "deletion_warning_sent_for"


def deadline_key(value: datetime) -> str:
    return value.strftime("%Y-%m-%dT%H:%M:%SZ")


def compute_deadlines(
    moodle: dict[str, Any],
    infra: dict[str, Any],
    policy: LifecyclePolicy,
) -> Deadlines:
    """Compute the lifecycle deadlines of a single moodle record.

    Pure. A running instance is stopped at the earlier of ``started +
    max_runtime`` and the first daily stop time *after* it was started, so an
    instance started after today's stop time runs until tomorrow's. A stopped
    instance (or one created but never started) is destroyed
    ``stopped_retention_days`` after it was stopped.
    Deadlines are ``None`` when the relevant automation is disabled, the
    status does not apply, or no usable timestamp exists.
    """
    result = Deadlines()
    status = moodle.get("status")
    infra_modified = infra.get("last_modified_at")

    if policy.auto_stop_enabled and status == STATUS_STARTED:
        started = _first_ts(
            moodle.get("started_at"), infra_modified, infra.get("created_at")
        )
        if started is not None:
            result.started = started
            max_runtime = timedelta(minutes=max(0, policy.max_runtime_minutes))
            result.auto_stop_at = started + max_runtime
            result.stop_reason = "runtime"
            stop_time = (
                _parse_hhmm(policy.daily_stop_time) if policy.daily_stop_time else None
            )
            if stop_time is not None:
                daily = _next_daily_boundary(started, stop_time)
                if daily < result.auto_stop_at:
                    result.auto_stop_at = daily
                    result.stop_reason = "daily"

    if policy.auto_cleanup_enabled and status in (STATUS_STOPPED, STATUS_CREATED):
        stopped = _first_ts(
            moodle.get("stopped_at"), infra_modified, moodle.get("created_at")
        )
        if stopped is not None:
            retention = timedelta(days=max(0, policy.stopped_retention_days))
            result.stopped = stopped
            result.auto_delete_at = stopped + retention

    return result


def policy_summary(policy: LifecyclePolicy) -> dict[str, Any]:
    """Serialisable view of the policy for the API / frontend help text."""
    return {
        "auto_stop_enabled": policy.auto_stop_enabled,
        "max_runtime_minutes": policy.max_runtime_minutes,
        "daily_stop_time": policy.daily_stop_time
        if _parse_hhmm(policy.daily_stop_time or "")
        else "",
        "auto_cleanup_enabled": policy.auto_cleanup_enabled,
        "stopped_retention_days": policy.stopped_retention_days,
        "cleanup_empty_infrastructures": policy.cleanup_empty_infrastructures,
    }


def plan_actions(
    testbed_info: dict[str, Any],
    policy: LifecyclePolicy,
    now: datetime | None = None,
    warn_before: timedelta | None = None,
) -> list[Action]:
    """Decide which instances to stop / destroy / teardown / warn about.

    With ``warn_before`` set, a ``notify`` action is planned once per stop
    cycle for an instance whose deletion is due within that window (and not
    yet due), unless a warning for that same deadline was already sent.

    Pure: no I/O, no Docker. ``now`` defaults to the current UTC time (naive).
    Malformed infrastructure/moodle records are skipped individually so a single
    bad entry never aborts the whole plan.
    """
    if now is None:
        now = datetime.now(timezone.utc).replace(tzinfo=None)
    elif now.tzinfo is not None:
        now = now.astimezone(timezone.utc).replace(tzinfo=None)

    actions: list[Action] = []

    for infra_name, infra in (testbed_info or {}).items():
        if not isinstance(infra, dict):
            continue
        moodles = infra.get("moodles")
        if not isinstance(moodles, dict):
            continue

        all_versions = [str(v) for v in moodles.keys()]
        to_destroy: list[str] = []

        for version, moodle in moodles.items():
            if not isinstance(moodle, dict):
                continue
            version = str(version)
            deadlines = compute_deadlines(moodle, infra, policy)

            # --- auto-stop: running past runtime / daily stop time ----------
            if deadlines.auto_stop_at is not None and now >= deadlines.auto_stop_at:
                if deadlines.stop_reason == "daily":
                    reason = f"past daily stop time {policy.daily_stop_time} UTC"
                else:
                    reason = (
                        f"running for {now - deadlines.started} "
                        f"(> {policy.max_runtime_minutes}m max runtime)"
                    )
                actions.append(Action("stop", infra_name, version, reason))

            # --- auto-cleanup: stopped/idle past retention -----------------
            delete_at = deadlines.auto_delete_at
            if delete_at is not None and now >= delete_at:
                to_destroy.append(version)
            elif (
                delete_at is not None
                and warn_before is not None
                and now >= delete_at - warn_before
                and moodle.get(WARNING_SENT_KEY) != deadline_key(delete_at)
            ):
                actions.append(
                    Action(
                        "notify",
                        infra_name,
                        version,
                        f"deletion due {deadline_key(delete_at)}",
                        deadline=delete_at,
                    )
                )

        # If every moodle in the infra is being cleaned up, tear the whole
        # infrastructure down in one go instead of per-moodle destroys.
        if (
            to_destroy
            and policy.cleanup_empty_infrastructures
            and set(to_destroy) == set(all_versions)
        ):
            actions.append(
                Action(
                    "teardown",
                    infra_name,
                    None,
                    f"all {len(all_versions)} instance(s) idle > "
                    f"{policy.stopped_retention_days}d",
                )
            )
        else:
            for version in to_destroy:
                actions.append(
                    Action(
                        "destroy",
                        infra_name,
                        version,
                        f"stopped/idle > {policy.stopped_retention_days}d",
                    )
                )

    return actions


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------


@dataclass
class ReapSummary:
    stopped: int = 0
    destroyed: int = 0
    torn_down: int = 0
    notified: int = 0
    failures: int = 0
    planned: list[Action] = field(default_factory=list)


def execute(
    actions: list[Action],
    core: Any,
    *,
    dry_run: bool = False,
    on_pre_destroy: Callable[[Action], None] | None = None,
    notifier: Callable[[Action], None] | None = None,
    logger: Callable[[str], None] | None = None,
) -> ReapSummary:
    """Apply lifecycle ``actions`` using ``core``.

    In ``dry_run`` mode no ``core`` method is called; actions are only reported.
    ``on_pre_destroy`` is invoked before each destroy/teardown; ``notifier``
    handles ``notify`` actions (deletion warning emails). Each action is
    isolated: a failure is logged and counted, but does not abort the
    remaining actions.
    """
    def _log(msg: str) -> None:
        if logger is not None:
            logger(msg)

    summary = ReapSummary(planned=list(actions))

    for action in actions:
        target = (
            f"{action.infrastructure}/{action.version}"
            if action.version
            else action.infrastructure
        )
        verb = {"notify": "send deletion warning for"}.get(action.kind, action.kind)
        prefix = "[dry-run] would " if dry_run else ""
        _log(f"{prefix}{verb} {target} ({action.reason})")

        if dry_run:
            continue

        try:
            if action.kind == "stop":
                core.stop_environment(action.infrastructure, action.version)
                summary.stopped += 1
            elif action.kind == "destroy":
                if on_pre_destroy is not None:
                    on_pre_destroy(action)
                core.destroy_environment(action.infrastructure, action.version)
                summary.destroyed += 1
            elif action.kind == "teardown":
                if on_pre_destroy is not None:
                    on_pre_destroy(action)
                core.teardown_infrastructure(action.infrastructure)
                summary.torn_down += 1
            elif action.kind == "notify":
                if notifier is None:
                    raise RuntimeError("no notifier configured")
                notifier(action)
                summary.notified += 1
        except Exception as exc:  # noqa: BLE001 - one bad action must not abort
            summary.failures += 1
            _log(f"FAILED: {verb} {target}: {exc}")

    return summary
