"""Administrator-set minimum Moodle version for new environments.

Stored as the ``moodle_versions`` section of ``settings.yaml``::

    moodle_versions:
      minimum_version: "4.5"     # "" = no minimum

When set, only that version and newer can be chosen for new environments or
added containers, for every plugin. Existing environments are not affected.
"""

from __future__ import annotations

from typing import Iterable

from packaging import version as pkg_version

from .validation import validate_moodle_version

SECTION = "moodle_versions"


def load_minimum_version() -> str:
    from ..cross_cutting import settings_store

    value = settings_store.get_section(SECTION).get("minimum_version", "")
    return value if isinstance(value, str) else ""


def save_minimum_version(minimum: str) -> None:
    from ..cross_cutting import settings_store

    if minimum:
        validate_moodle_version(minimum)
    settings_store.set_section(SECTION, {"minimum_version": minimum})


def is_allowed(moodle_version: str, minimum: str) -> bool:
    """True when there is no minimum or ``moodle_version`` >= ``minimum``."""
    if not minimum:
        return True
    return pkg_version.parse(moodle_version) >= pkg_version.parse(minimum)


def too_old(versions: Iterable[str], minimum: str) -> list[str]:
    """The versions in ``versions`` that are below ``minimum``."""
    return [v for v in versions if not is_allowed(v, minimum)]
