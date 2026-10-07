"""Validation of user-supplied identifiers.

Infrastructure names and Moodle versions end up in file system paths, in the
sourced ``.env`` of each moodle-docker project and in shell command lines;
git references are passed to git. Everything coming from the API or the CLI
must pass these checks before it is used, so that no value can escape its
directory or be interpreted by a shell.
"""

from __future__ import annotations

import re

from ..exceptions import BoostUnionTestEnvValueError

# Letters, digits, dot, underscore, dash; must start with a letter or digit.
# Upper case and dots are accepted for compatibility with environments created
# with the CLI; the web UI only creates lower-case names.
_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,62}$")
# Moodle release numbers, e.g. 4.5, 5.0.2, 5.1.10
_VERSION_RE = re.compile(r"^\d{1,2}\.\d{1,2}(\.\d{1,3})?$")
# Branch or tag names: no leading dash (git option injection), no whitespace
# or shell metacharacters.
_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/+-]{0,199}$")
_COMMIT_RE = re.compile(r"^[0-9a-fA-F]{7,40}$")


class InvalidInputError(BoostUnionTestEnvValueError):
    """A user-supplied name, version or git reference is not acceptable."""


def validate_infrastructure_name(name: str) -> str:
    if not isinstance(name, str) or not _NAME_RE.fullmatch(name) or ".." in name:
        raise InvalidInputError(
            f"Invalid environment name {name!r}: use 1-63 letters, digits, '.', '_' "
            "or '-', starting with a letter or digit"
        )
    return name


def validate_moodle_version(version: str) -> str:
    if not isinstance(version, str) or not _VERSION_RE.fullmatch(version):
        raise InvalidInputError(
            f"Invalid Moodle version {version!r}: expected e.g. 4.5 or 5.0.2"
        )
    return version


def validate_git_ref(ref_type: object, ref: str | int) -> str | int:
    """Validate a git reference for the given type (branch, tag, commit, pr).

    ``ref_type`` may be a plain string or a ``GitReferenceType``.
    """
    kind = str(getattr(ref_type, "value", ref_type)).lower()
    if kind == "pr":
        try:
            number = int(ref)
        except (TypeError, ValueError):
            number = 0
        if number <= 0:
            raise InvalidInputError(f"Invalid pull request number {ref!r}")
        return number
    text = str(ref)
    if kind == "commit":
        if not _COMMIT_RE.fullmatch(text):
            raise InvalidInputError(f"Invalid commit SHA {text!r}")
        return text
    if kind in ("branch", "tag"):
        if not _REF_RE.fullmatch(text) or ".." in text or text.endswith((".", "/", ".lock")):
            raise InvalidInputError(f"Invalid {kind} name {text!r}")
        return text
    raise InvalidInputError(f"Invalid git reference type {ref_type!r}")
