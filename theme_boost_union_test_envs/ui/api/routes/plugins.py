"""Routes for fetching plugin git references (branches, tags, pull requests).

This proxies the GitHub REST API so that:
- the GitHub token stays on the server
- responses can be cached in-memory to stay within the rate limit
- the browser does not have to deal with CORS on github.com

If the environment variable ``GITHUB_TOKEN`` is set, requests are authenticated
(5000/hour). Otherwise requests go out unauthenticated (60/hour per IP).
"""

from __future__ import annotations

import os
import re
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

import httpx
import yaml
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from theme_boost_union_test_envs.cross_cutting import config

router = APIRouter(prefix="/api/plugins", tags=["plugins"])


class PluginVersion(BaseModel):
    ref: str
    name: str
    type: Literal["branch", "tag", "pr"]


class PluginVersionsResponse(BaseModel):
    versions: list[PluginVersion]


# Simple in-memory cache: { (owner, repo): (expires_at, versions) }
_CACHE: dict[tuple[str, str], tuple[float, list[PluginVersion]]] = {}
_CACHE_TTL_SECONDS = 300  # 5 minutes


def _parse_github_repo_url(repo_url: str) -> tuple[str, str]:
    """Extract (owner, repo) from a GitHub URL like https://github.com/owner/repo(.git)."""
    parsed = urlparse(repo_url)
    if parsed.netloc.lower() != "github.com":
        raise HTTPException(
            status_code=400,
            detail=f"Only github.com repositories are supported, got {parsed.netloc!r}",
        )
    parts = [p for p in parsed.path.strip("/").split("/") if p]
    if len(parts) < 2:
        raise HTTPException(status_code=400, detail=f"Invalid GitHub URL: {repo_url!r}")
    owner, repo = parts[0], parts[1]
    repo = re.sub(r"\.git$", "", repo)
    return owner, repo


def _github_headers() -> dict[str, str]:
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "boost-union-test-envs",
    }
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _paginated_get(client: httpx.Client, url: str, params: dict) -> list[dict]:
    """Fetch all pages of a GitHub list endpoint (max 300 items, 3 pages)."""
    results: list[dict] = []
    page = 1
    while page <= 3:
        resp = client.get(url, params={**params, "page": page, "per_page": 100})
        if resp.status_code == 404:
            raise HTTPException(status_code=404, detail=f"Repository not found: {url}")
        if resp.status_code == 403 and "rate limit" in resp.text.lower():
            raise HTTPException(
                status_code=429,
                detail="GitHub API rate limit exceeded. Set GITHUB_TOKEN on the server.",
            )
        resp.raise_for_status()
        page_data = resp.json()
        if not page_data:
            break
        results.extend(page_data)
        if len(page_data) < 100:
            break
        page += 1
    return results


def _fetch_versions(owner: str, repo: str) -> list[PluginVersion]:
    base = f"https://api.github.com/repos/{owner}/{repo}"
    versions: list[PluginVersion] = []
    with httpx.Client(headers=_github_headers(), timeout=15.0) as client:
        branches = _paginated_get(client, f"{base}/branches", {})
        for b in branches:
            name = b["name"]
            versions.append(PluginVersion(ref=name, name=name, type="branch"))

        tags = _paginated_get(client, f"{base}/tags", {})
        for t in tags:
            name = t["name"]
            versions.append(PluginVersion(ref=name, name=name, type="tag"))

        prs = _paginated_get(client, f"{base}/pulls", {"state": "open"})
        for pr in prs:
            number = pr["number"]
            title = pr.get("title", "")
            versions.append(
                PluginVersion(
                    ref=f"PR#{number}",
                    name=f"PR#{number}: {title}" if title else f"PR#{number}",
                    type="pr",
                )
            )
    return versions


@router.get("/refs", response_model=PluginVersionsResponse)
def list_plugin_refs(
    repo_url: str = Query(..., description="GitHub repository URL"),
) -> PluginVersionsResponse:
    """List all branches, tags and open pull requests of a GitHub repository."""
    owner, repo = _parse_github_repo_url(repo_url)
    cache_key = (owner, repo)

    cached = _CACHE.get(cache_key)
    now = time.time()
    if cached and cached[0] > now:
        return PluginVersionsResponse(versions=cached[1])

    try:
        versions = _fetch_versions(owner, repo)
    except HTTPException:
        raise
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"GitHub API error: {e}") from e

    _CACHE[cache_key] = (now + _CACHE_TTL_SECONDS, versions)
    return PluginVersionsResponse(versions=versions)


# ---------------------------------------------------------------------------
# Plugin catalog CRUD (stored in <working_dir>/plugins.yaml)
# ---------------------------------------------------------------------------


PluginType = Literal["activity", "block", "theme", "local", "admin", "core", "other"]


class PluginCreatedBy(BaseModel):
    id: str
    name: str
    email: str


class Plugin(BaseModel):
    id: str
    name: str
    displayName: str
    repositoryUrl: str
    installationPath: str
    description: str | None = None
    type: PluginType
    isActive: bool = True
    createdAt: str
    updatedAt: str
    createdBy: PluginCreatedBy | None = None


class PluginCreate(BaseModel):
    name: str
    displayName: str
    repositoryUrl: str
    installationPath: str
    description: str | None = None
    type: PluginType
    isActive: bool = True
    createdBy: PluginCreatedBy | None = None


class PluginUpdate(BaseModel):
    displayName: str | None = None
    repositoryUrl: str | None = None
    installationPath: str | None = None
    description: str | None = None
    type: PluginType | None = None
    isActive: bool | None = None


class PluginListResponse(BaseModel):
    plugins: list[Plugin]


# Human-friendly display name + type for known supported plugins. Anything
# not listed falls back to a title-cased name and a prefix-derived type.
_KNOWN_PLUGIN_META: dict[str, tuple[str, PluginType]] = {
    "boost_union": ("Boost Union", "theme"),
    "boost_union_child": ("Boost Union Child", "theme"),
    "bookit": ("BookIT - Exam Booking", "activity"),
}

# Map plugin-key prefixes to a catalog type.
_TYPE_BY_PREFIX: list[tuple[str, PluginType]] = [
    ("block_", "block"),
    ("local_", "local"),
    ("tool_", "admin"),
]

# Legacy auto-seeded catalog entries, now superseded by the supported-plugins.yml
# registry. Dropped on load so they don't duplicate the real registry keys.
_LEGACY_DEFAULT_NAMES = {"theme_boost_union", "mod_bookit"}


def _derive_type(key: str) -> PluginType:
    for prefix, ptype in _TYPE_BY_PREFIX:
        if key.startswith(prefix):
            return ptype
    return "other"


def _supported_plugin_entries() -> list[dict]:
    """Build catalog entries for every plugin in supported-plugins.yml.

    The entry ``name`` is the supported-plugins key, which is exactly the
    identifier the create-infrastructure endpoint expects, so a plugin picked
    in the UI can be provisioned without any name translation.
    """
    now = datetime.now().isoformat()
    entries: list[dict] = []
    for key, info in config().supported_plugins.items():
        display, ptype = _KNOWN_PLUGIN_META.get(
            key, (key.replace("_", " ").title(), _derive_type(key))
        )
        entries.append(
            {
                "id": f"plugin-{key}",
                "name": key,
                "displayName": display,
                "repositoryUrl": info.get("url", ""),
                "installationPath": info.get("install_folder", ""),
                "type": ptype,
                "isActive": True,
                "createdAt": now,
                "updatedAt": now,
            }
        )
    return entries


def _plugins_yaml_path() -> Path:
    return config().working_dir / "plugins.yaml"


def _load_plugins_raw() -> list[dict]:
    """Return the effective plugin catalog.

    The catalog always contains every plugin from supported-plugins.yml (the
    defaults) plus any manually-added plugins persisted in plugins.yaml. User
    edits to supported plugins (e.g. toggling ``isActive``) are preserved.
    """
    path = _plugins_yaml_path()
    supported = _supported_plugin_entries()
    supported_by_name = {e["name"]: e for e in supported}

    if not path.exists():
        _save_plugins_raw(supported)
        return supported

    with open(path, "r") as f:
        data = yaml.safe_load(f) or {}
    stored = list(data.get("plugins", []))
    stored_names = {p.get("name") for p in stored}

    # Manually-added plugins: anything that is neither a supported key nor a
    # legacy default.
    manual = [
        p
        for p in stored
        if p.get("name") not in supported_by_name
        and p.get("name") not in _LEGACY_DEFAULT_NAMES
    ]

    # Preserve already-persisted supported plugins (keeps user edits), then
    # append any supported plugins not yet on disk.
    persisted_supported = [p for p in stored if p.get("name") in supported_by_name]
    persisted_names = {p.get("name") for p in persisted_supported}
    new_supported = [e for e in supported if e["name"] not in persisted_names]

    result = persisted_supported + new_supported + manual

    # Persist only when the catalog gained supported plugins or still carried
    # legacy defaults — avoids rewriting the file on every read.
    if new_supported or (stored_names & _LEGACY_DEFAULT_NAMES):
        _save_plugins_raw(result)
    return result


def _save_plugins_raw(plugins: list[dict]) -> None:
    path = _plugins_yaml_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        yaml.safe_dump({"plugins": plugins}, f, sort_keys=False)


def get_plugin_registry_entry(name: str) -> dict | None:
    """Resolve a plugin's repo URL + install folder by its catalog name.

    Looks in supported-plugins.yml first (the canonical registry), then falls
    back to manually-added plugins in the catalog (plugins.yaml). Returns a
    dict shaped like the supported-plugins.yml entries
    (``{"url": ..., "install_folder": ...}``) or ``None`` if unknown.
    """
    supported = config().supported_plugins
    if name in supported:
        return supported[name]
    for p in _load_plugins_raw():
        if p.get("name") == name:
            return {
                "url": p.get("repositoryUrl", ""),
                "install_folder": p.get("installationPath", ""),
            }
    return None


@router.get("", response_model=PluginListResponse)
def list_plugins() -> PluginListResponse:
    return PluginListResponse(plugins=[Plugin(**p) for p in _load_plugins_raw()])


@router.post("", response_model=Plugin, status_code=201)
def create_plugin(payload: PluginCreate) -> Plugin:
    plugins = _load_plugins_raw()
    if any(p.get("name") == payload.name for p in plugins):
        raise HTTPException(
            status_code=409, detail=f"Plugin with name {payload.name!r} already exists"
        )
    now = datetime.now().isoformat()
    new_plugin = Plugin(
        id=f"plugin-{uuid.uuid4().hex[:8]}",
        createdAt=now,
        updatedAt=now,
        **payload.model_dump(),
    )
    plugins.append(new_plugin.model_dump(exclude_none=True))
    _save_plugins_raw(plugins)
    return new_plugin


@router.patch("/{plugin_id}", response_model=Plugin)
def update_plugin(plugin_id: str, payload: PluginUpdate) -> Plugin:
    plugins = _load_plugins_raw()
    for i, p in enumerate(plugins):
        if p.get("id") == plugin_id:
            updates = payload.model_dump(exclude_unset=True)
            updated = {**p, **updates, "updatedAt": datetime.now().isoformat()}
            plugins[i] = updated
            _save_plugins_raw(plugins)
            return Plugin(**updated)
    raise HTTPException(status_code=404, detail=f"Plugin {plugin_id!r} not found")


@router.delete("/{plugin_id}")
def delete_plugin(plugin_id: str) -> dict:
    plugins = _load_plugins_raw()
    new_plugins = [p for p in plugins if p.get("id") != plugin_id]
    if len(new_plugins) == len(plugins):
        raise HTTPException(status_code=404, detail=f"Plugin {plugin_id!r} not found")
    _save_plugins_raw(new_plugins)
    return {"status": "ok", "message": f"Plugin {plugin_id} deleted"}
