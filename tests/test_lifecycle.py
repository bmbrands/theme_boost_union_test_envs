"""Tests for the automated instance-lifecycle reaper (work package 3).

The planner is pure, so it is exercised directly with synthetic testbed state
and a fixed clock. The executor is tested against a fake ``core`` that records
calls. The status-change timestamp stamping is tested against an isolated
``infrastructure.yaml``. No Docker is involved.
"""

from __future__ import annotations

import types
from datetime import datetime, timedelta
from pathlib import Path

import pytest
import yaml

from theme_boost_union_test_envs.cross_cutting import infrastructure_parser as parser_mod
from theme_boost_union_test_envs.domain import lifecycle
from theme_boost_union_test_envs.domain.lifecycle import (
    Action,
    LifecyclePolicy,
    execute,
    plan_actions,
    policy_from_values,
)
from theme_boost_union_test_envs.entities import GitReference, GitReferenceType

NOW = datetime(2026, 1, 10, 12, 0, 0)


def _ts(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def _testbed(moodles: dict, **infra_extra) -> dict:
    infra = {
        "created_at": _ts(NOW - timedelta(days=30)),
        "last_modified_at": _ts(NOW - timedelta(days=30)),
        "git_ref": {"type": "BRANCH", "reference": "main"},
        "plugin": "boost_union",
        "moodles": moodles,
    }
    infra.update(infra_extra)
    return {"demo": infra}


# ---- policy loader ------------------------------------------------------


def test_policy_defaults_disable_automation() -> None:
    p = policy_from_values(None)
    assert p.auto_stop_enabled is False
    assert p.auto_cleanup_enabled is False
    assert p.max_runtime_minutes == 480
    assert p.stopped_retention_days == 7
    assert p.cleanup_empty_infrastructures is True


def test_policy_reads_overrides() -> None:
    p = policy_from_values(
        {
            "lifecycle": {
                "auto_stop_enabled": True,
                "max_runtime_minutes": 60,
                "daily_stop_time": "20:00",
                "auto_cleanup_enabled": "yes",
                "stopped_retention_days": 3,
                "cleanup_empty_infrastructures": False,
            }
        }
    )
    assert p.auto_stop_enabled is True
    assert p.max_runtime_minutes == 60
    assert p.daily_stop_time == "20:00"
    assert p.auto_cleanup_enabled is True  # coerced from "yes"
    assert p.stopped_retention_days == 3
    assert p.cleanup_empty_infrastructures is False


def test_policy_ignores_malformed_values() -> None:
    p = policy_from_values({"lifecycle": {"max_runtime_minutes": "not-a-number"}})
    assert p.max_runtime_minutes == 480  # falls back to default


# ---- planner: auto-stop -------------------------------------------------


def test_stop_when_running_past_max_runtime() -> None:
    policy = LifecyclePolicy(auto_stop_enabled=True, max_runtime_minutes=60)
    tb = _testbed(
        {"5.0.0": {"status": "STARTED", "started_at": _ts(NOW - timedelta(hours=3))}}
    )
    actions = plan_actions(tb, policy, NOW)
    assert actions == [Action("stop", "demo", "5.0.0", actions[0].reason)]
    assert "max runtime" in actions[0].reason


def test_no_stop_when_within_runtime() -> None:
    policy = LifecyclePolicy(auto_stop_enabled=True, max_runtime_minutes=240)
    tb = _testbed(
        {"5.0.0": {"status": "STARTED", "started_at": _ts(NOW - timedelta(hours=1))}}
    )
    assert plan_actions(tb, policy, NOW) == []


def test_no_stop_when_auto_stop_disabled() -> None:
    policy = LifecyclePolicy(auto_stop_enabled=False, max_runtime_minutes=1)
    tb = _testbed(
        {"5.0.0": {"status": "STARTED", "started_at": _ts(NOW - timedelta(days=1))}}
    )
    assert plan_actions(tb, policy, NOW) == []


def test_stop_at_daily_stop_time() -> None:
    policy = LifecyclePolicy(
        auto_stop_enabled=True, max_runtime_minutes=100000, daily_stop_time="10:00"
    )
    tb = _testbed(
        {"5.0.0": {"status": "STARTED", "started_at": _ts(NOW - timedelta(minutes=5))}}
    )
    # NOW is 12:00 UTC, past the 10:00 stop time.
    actions = plan_actions(tb, policy, NOW)
    assert [a.kind for a in actions] == ["stop"]
    assert "daily stop time" in actions[0].reason


def test_stop_falls_back_to_infra_timestamp_when_started_at_missing() -> None:
    policy = LifecyclePolicy(auto_stop_enabled=True, max_runtime_minutes=60)
    tb = _testbed(
        {"5.0.0": {"status": "STARTED"}},  # no started_at
        last_modified_at=_ts(NOW - timedelta(hours=5)),
    )
    actions = plan_actions(tb, policy, NOW)
    assert [a.kind for a in actions] == ["stop"]


# ---- planner: auto-cleanup ---------------------------------------------


def test_destroy_when_stopped_past_retention() -> None:
    policy = LifecyclePolicy(
        auto_cleanup_enabled=True,
        stopped_retention_days=7,
        cleanup_empty_infrastructures=False,
    )
    tb = _testbed(
        {
            "5.0.0": {"status": "STOPPED", "stopped_at": _ts(NOW - timedelta(days=10))},
            "4.5.0": {"status": "STARTED", "started_at": _ts(NOW)},
        }
    )
    actions = plan_actions(tb, policy, NOW)
    assert actions == [Action("destroy", "demo", "5.0.0", actions[0].reason)]


def test_no_destroy_when_recently_stopped() -> None:
    policy = LifecyclePolicy(auto_cleanup_enabled=True, stopped_retention_days=7)
    tb = _testbed(
        {"5.0.0": {"status": "STOPPED", "stopped_at": _ts(NOW - timedelta(days=2))}}
    )
    assert plan_actions(tb, policy, NOW) == []


def test_teardown_when_all_instances_idle() -> None:
    policy = LifecyclePolicy(
        auto_cleanup_enabled=True,
        stopped_retention_days=7,
        cleanup_empty_infrastructures=True,
    )
    tb = _testbed(
        {
            "5.0.0": {"status": "STOPPED", "stopped_at": _ts(NOW - timedelta(days=10))},
            "4.5.0": {"status": "STOPPED", "stopped_at": _ts(NOW - timedelta(days=10))},
        }
    )
    actions = plan_actions(tb, policy, NOW)
    assert [a.kind for a in actions] == ["teardown"]
    assert actions[0].version is None


def test_per_moodle_destroy_when_not_all_idle() -> None:
    policy = LifecyclePolicy(
        auto_cleanup_enabled=True,
        stopped_retention_days=7,
        cleanup_empty_infrastructures=True,
    )
    tb = _testbed(
        {
            "5.0.0": {"status": "STOPPED", "stopped_at": _ts(NOW - timedelta(days=10))},
            "4.5.0": {"status": "STARTED", "started_at": _ts(NOW)},
        }
    )
    actions = plan_actions(tb, policy, NOW)
    assert [(a.kind, a.version) for a in actions] == [("destroy", "5.0.0")]


def test_malformed_record_is_skipped() -> None:
    policy = LifecyclePolicy(auto_stop_enabled=True, max_runtime_minutes=1)
    tb = {
        "bad": "not-a-dict",
        "demo": {
            "moodles": {
                "5.0.0": "also-bad",
                "4.5.0": {"status": "STARTED", "started_at": _ts(NOW - timedelta(days=1))},
            }
        },
    }
    actions = plan_actions(tb, policy, NOW)
    assert [(a.kind, a.version) for a in actions] == [("stop", "4.5.0")]


# ---- executor -----------------------------------------------------------


class _FakeCore:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple]] = []

    def stop_environment(self, name, *versions):
        self.calls.append(("stop", (name, *versions)))

    def destroy_environment(self, name, *versions):
        self.calls.append(("destroy", (name, *versions)))

    def teardown_infrastructure(self, name):
        self.calls.append(("teardown", (name,)))


def test_execute_applies_actions_and_pre_destroy_hook() -> None:
    core = _FakeCore()
    notified: list[str] = []
    actions = [
        Action("stop", "demo", "5.0.0"),
        Action("destroy", "demo", "4.5.0"),
        Action("teardown", "old", None),
    ]
    summary = execute(
        actions, core, on_pre_destroy=lambda a: notified.append(a.infrastructure)
    )
    assert core.calls == [
        ("stop", ("demo", "5.0.0")),
        ("destroy", ("demo", "4.5.0")),
        ("teardown", ("old",)),
    ]
    assert summary.stopped == 1 and summary.destroyed == 1 and summary.torn_down == 1
    assert notified == ["demo", "old"]  # hook fired before destroy + teardown


def test_execute_dry_run_makes_no_calls() -> None:
    core = _FakeCore()
    actions = [Action("destroy", "demo", "5.0.0")]
    summary = execute(actions, core, dry_run=True)
    assert core.calls == []
    assert summary.destroyed == 0
    assert summary.planned == actions


def test_execute_isolates_failures() -> None:
    class _BoomCore(_FakeCore):
        def stop_environment(self, name, *versions):
            raise RuntimeError("docker down")

    core = _BoomCore()
    actions = [Action("stop", "demo", "5.0.0"), Action("destroy", "demo", "4.5.0")]
    summary = execute(actions, core)
    # First action fails but the second still runs.
    assert summary.failures == 1
    assert summary.destroyed == 1


# ---- timestamp stamping on status change --------------------------------


@pytest.fixture()
def parser(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    infra_yaml = tmp_path / "infrastructure.yaml"
    infra_yaml.write_text("")
    fake = types.SimpleNamespace(infra_yaml=infra_yaml)
    monkeypatch.setattr(parser_mod, "config", lambda: fake)
    return parser_mod.InfrastructureYAMLParser()


def test_status_change_records_started_and_stopped_at(parser) -> None:
    parser.new_infrastructure(
        "demo", "boost_union", GitReference("main", GitReferenceType.BRANCH)
    )
    parser.add_moodles_to_infrastructure("demo", {"5.0.0": {"status": "CREATED"}})

    parser.change_moodle_test_container_status("demo", "STARTED", "5.0.0")
    entry = yaml.safe_load(open(parser.yaml))["demo"]["moodles"]["5.0.0"]
    assert entry["status"] == "STARTED"
    assert "started_at" in entry and entry["started_at"]

    parser.change_moodle_test_container_status("demo", "STOPPED", "5.0.0")
    entry = yaml.safe_load(open(parser.yaml))["demo"]["moodles"]["5.0.0"]
    assert entry["status"] == "STOPPED"
    assert "stopped_at" in entry and entry["stopped_at"]
    # started_at is preserved across the stop transition.
    assert "started_at" in entry
