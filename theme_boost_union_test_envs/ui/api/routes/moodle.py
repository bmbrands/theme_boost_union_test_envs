"""Routes for fetching the available Moodle versions from the official
moodle/moodle GitHub repository.

Returns a sorted list of release tags (e.g. "v5.0.2", "v4.5.6", …) filtered
to the ``vMAJOR.MINOR.PATCH`` format. Responses are cached in memory for
one hour to stay well within the GitHub API rate limit.
"""

from __future__ import annotations

import re
import time

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .plugins import _github_headers

router = APIRouter(prefix="/api/moodle", tags=["moodle"])


class MoodleVersion(BaseModel):
    version: str  # e.g. "5.0.2"
    tag: str  # e.g. "v5.0.2"
    major: int
    minor: int
    patch: int


class MoodleVersionsResponse(BaseModel):
    versions: list[MoodleVersion]


_CACHE: dict[str, tuple[float, list[MoodleVersion]]] = {}
_CACHE_TTL_SECONDS = 3600  # 1 hour
_VERSION_TAG_RE = re.compile(r"^v(\d+)\.(\d+)\.(\d+)$")
_MAX_PAGES = 20  # up to 2000 tags — moodle has ~900


def _fetch_moodle_versions() -> list[MoodleVersion]:
    url = "https://api.github.com/repos/moodle/moodle/tags"
    versions: list[MoodleVersion] = []

    with httpx.Client(headers=_github_headers(), timeout=30.0) as client:
        for page in range(1, _MAX_PAGES + 1):
            resp = client.get(url, params={"per_page": 100, "page": page})
            if resp.status_code == 403 and "rate limit" in resp.text.lower():
                raise HTTPException(
                    status_code=429,
                    detail="GitHub API rate limit exceeded. Set GITHUB_TOKEN on the server.",
                )
            resp.raise_for_status()
            page_data = resp.json()
            if not page_data:
                break
            for t in page_data:
                name = t.get("name", "")
                m = _VERSION_TAG_RE.match(name)
                if not m:
                    continue
                major, minor, patch = int(m[1]), int(m[2]), int(m[3])
                versions.append(
                    MoodleVersion(
                        version=f"{major}.{minor}.{patch}",
                        tag=name,
                        major=major,
                        minor=minor,
                        patch=patch,
                    )
                )
            if len(page_data) < 100:
                break

    # Sort newest first
    versions.sort(key=lambda v: (v.major, v.minor, v.patch), reverse=True)
    return versions


@router.get("/versions", response_model=MoodleVersionsResponse)
def list_moodle_versions() -> MoodleVersionsResponse:
    """List all official Moodle release versions (tags of moodle/moodle)."""
    now = time.time()
    cached = _CACHE.get("versions")
    if cached and cached[0] > now:
        return MoodleVersionsResponse(versions=cached[1])

    try:
        versions = _fetch_moodle_versions()
    except HTTPException:
        raise
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"GitHub API error: {e}") from e

    _CACHE["versions"] = (now + _CACHE_TTL_SECONDS, versions)
    return MoodleVersionsResponse(versions=versions)
