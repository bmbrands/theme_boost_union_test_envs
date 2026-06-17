import threading
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel, Field

from theme_boost_union_test_envs.cross_cutting import yaml_parser
from theme_boost_union_test_envs.cross_cutting.logger import log
from ..models import InfrastructureListResponse, InfrastructureResponse, MoodleContainerResponse

router = APIRouter(prefix="/api/infrastructures", tags=["infrastructures"])


# In-memory tracker of infrastructures currently being provisioned.
# Shape: {name: {git_ref_type, git_ref_reference, moodle_versions, created_at, error?}}
_provisioning: dict[str, dict] = {}
_provisioning_lock = threading.Lock()


def _get_core():
    """Get the BoostUnionTestEnvCore singleton from the DI container."""
    from theme_boost_union_test_envs.app import Application
    return Application().core()


class CreateInfrastructureRequest(BaseModel):
    name: str = Field(..., min_length=1, description="Unique infrastructure name")
    plugin: str = Field(
        default="boost_union",
        min_length=1,
        description="Plugin key as defined in supported-plugins.yml (e.g. 'boost_union')",
    )
    git_ref_type: Literal["branch", "tag", "commit", "pr"]
    git_ref: str = Field(..., min_length=1, description="Branch/tag name, commit SHA or PR number")
    moodle_versions: list[str] = Field(..., min_length=1, description="Moodle versions to build")


class CreateInfrastructureResponse(BaseModel):
    status: str
    message: str
    name: str


@router.get("", response_model=InfrastructureListResponse)
def list_infrastructures() -> InfrastructureListResponse:
    """List all infrastructures and their Moodle containers."""
    raw = yaml_parser().load_testbed_info()

    infrastructures = []
    for name, data in raw.items():
        git_ref = data.get("git_ref", {})
        moodles_raw = data.get("moodles", {})

        moodles = []
        for version, moodle_data in moodles_raw.items():
            # Map backend status names to frontend-friendly names
            status_map = {"STARTED": "running", "STOPPED": "stopped", "CREATED": "stopped"}
            backend_status = moodle_data.get("status", "CREATED")

            moodles.append(
                MoodleContainerResponse(
                    moodle_version=str(version),
                    status=status_map.get(backend_status, "stopped"),
                    url=moodle_data.get("url", ""),
                    admin_password=moodle_data.get("admin_pw", ""),
                    www_port=str(moodle_data.get("www_port", "")),
                    db_port=str(moodle_data.get("db_port", "")),
                    created_at=moodle_data.get("created_at", ""),
                )
            )

        # If this infra is still being provisioned, append provisioning-status
        # placeholders for any moodle versions not yet present in the yaml.
        with _provisioning_lock:
            prov = _provisioning.get(name)
        if prov:
            existing_versions = {m.moodle_version for m in moodles}
            for v in prov["moodle_versions"]:
                if str(v) not in existing_versions:
                    moodles.append(
                        MoodleContainerResponse(
                            moodle_version=str(v),
                            status="provisioning",
                            url="",
                            admin_password="",
                            www_port="",
                            db_port="",
                            created_at=prov.get("created_at", ""),
                        )
                    )

        infrastructures.append(
            InfrastructureResponse(
                name=name,
                git_ref_type=git_ref.get("type", ""),
                git_ref_reference=str(git_ref.get("reference", "")),
                created_at=data.get("created_at", ""),
                plugin=str(data.get("plugin", "")),
                moodles=moodles,
                provisioning_phase=prov.get("phase") if prov else None,
                provisioning_error=prov.get("error") if prov else None,
            )
        )

    # Append purely-provisioning infrastructures (not yet in yaml).
    with _provisioning_lock:
        pending = {name: prov for name, prov in _provisioning.items() if name not in raw}
    for name, prov in pending.items():
        infrastructures.append(
            InfrastructureResponse(
                name=name,
                git_ref_type=prov.get("git_ref_type", ""),
                git_ref_reference=str(prov.get("git_ref_reference", "")),
                created_at=prov.get("created_at", ""),
                plugin=str(prov.get("plugin", "")),
                moodles=[
                    MoodleContainerResponse(
                        moodle_version=str(v),
                        status="provisioning",
                        url="",
                        admin_password="",
                        www_port="",
                        db_port="",
                        created_at=prov.get("created_at", ""),
                    )
                    for v in prov["moodle_versions"]
                ],
                provisioning_phase=prov.get("phase"),
                provisioning_error=prov.get("error"),
            )
        )

    return InfrastructureListResponse(infrastructures=infrastructures)


def _set_phase(name: str, phase: str) -> None:
    with _provisioning_lock:
        entry = _provisioning.get(name)
        if entry is not None:
            entry["phase"] = phase


def _run_provisioning(name: str, plugin: str, git_ref_type: str, ref: str | int, moodle_versions: list[str]) -> None:
    """Background worker that performs the actual setup + build.

    Runs in FastAPI's BackgroundTasks threadpool. Updates `_provisioning`
    so the list endpoint can report progress or errors.
    """
    from theme_boost_union_test_envs.domain.git import GitReference, GitReferenceType

    try:
        core = _get_core()
        git_ref = GitReference(ref, GitReferenceType(git_ref_type))
        _set_phase(name, "cloning")
        core.setup_infrastructure(name, plugin, git_ref)
        _set_phase(name, "building")
        core.build_infrastructure(name, *moodle_versions)
        _set_phase(name, "finalizing")
    except Exception as e:  # noqa: BLE001 - we must record any failure
        log().exception("Provisioning failed for infrastructure '{}'", name)
        with _provisioning_lock:
            if name in _provisioning:
                _provisioning[name]["error"] = str(e)
                _provisioning[name]["phase"] = "error"
        return

    with _provisioning_lock:
        _provisioning.pop(name, None)


@router.post("", response_model=CreateInfrastructureResponse, status_code=202)
def create_infrastructure(
    payload: CreateInfrastructureRequest,
    background_tasks: BackgroundTasks,
) -> CreateInfrastructureResponse:
    """Schedule creation of a new infrastructure and its Moodle containers.

    Returns 202 immediately and performs the actual work (clone + moodle-docker
    setup + container build) in a background thread. The infrastructure shows
    up in the list with status ``provisioning`` until it is ready.

    Equivalent to running:

        boost-union-envs setup <name> <git_ref_type> <git_ref>
        boost-union-envs build <name> <moodle_version> [<moodle_version> ...]
    """
    # Reject duplicate names up-front (both in-flight and already-persisted).
    existing = yaml_parser().load_testbed_info()
    with _provisioning_lock:
        if payload.name in _provisioning or payload.name in existing:
            raise HTTPException(
                status_code=409,
                detail=f"Infrastructure '{payload.name}' already exists",
            )

    # Validate the plugin against the known registry (supported-plugins.yml
    # plus manually-added catalog plugins) so we fail fast with a clear 400
    # instead of blowing up inside the background task.
    from .plugins import get_plugin_registry_entry

    if get_plugin_registry_entry(payload.plugin) is None:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Unknown plugin '{payload.plugin}'. It must be defined in "
                f"supported-plugins.yml or added to the plugin catalog."
            ),
        )

    # PRs are passed as ints in the domain layer. The plugin-refs endpoint
    # exposes PRs with a "PR#" prefix (e.g. "PR#123") for display, so strip it
    # before coercing to int.
    ref: str | int = payload.git_ref
    if payload.git_ref_type == "pr":
        try:
            ref = int(payload.git_ref.removeprefix("PR#"))
        except ValueError as e:
            raise HTTPException(status_code=400, detail="PR reference must be numeric") from e

    with _provisioning_lock:
        _provisioning[payload.name] = {
            "git_ref_type": payload.git_ref_type,
            "git_ref_reference": payload.git_ref,
            "plugin": payload.plugin,
            "moodle_versions": list(payload.moodle_versions),
            "created_at": datetime.now(timezone.utc).isoformat(),
            "phase": "queued",
        }

    background_tasks.add_task(
        _run_provisioning,
        payload.name,
        payload.plugin,
        payload.git_ref_type,
        ref,
        list(payload.moodle_versions),
    )

    return CreateInfrastructureResponse(
        status="accepted",
        message=f"Infrastructure {payload.name} is being provisioned",
        name=payload.name,
    )


class AddContainersRequest(BaseModel):
    moodle_versions: list[str] = Field(..., min_length=1)


class AddContainersResponse(BaseModel):
    status: str
    message: str
    name: str


def _run_build_only(name: str, moodle_versions: list[str]) -> None:
    """Background worker that builds additional containers for an existing infra."""
    try:
        core = _get_core()
        _set_phase(name, "building")
        core.build_infrastructure(name, *moodle_versions)
        _set_phase(name, "finalizing")
    except Exception as e:  # noqa: BLE001 - record any failure
        log().exception("Container build failed for infrastructure '{}'", name)
        with _provisioning_lock:
            if name in _provisioning:
                _provisioning[name]["error"] = str(e)
                _provisioning[name]["phase"] = "error"
        return

    with _provisioning_lock:
        _provisioning.pop(name, None)


@router.post("/{name}/containers", response_model=AddContainersResponse, status_code=202)
def add_containers(
    name: str,
    payload: AddContainersRequest,
    background_tasks: BackgroundTasks,
) -> AddContainersResponse:
    """Schedule additional Moodle containers for an existing infrastructure.

    Equivalent to: ``boost-union-envs build <name> <moodle_version> ...``
    """
    existing = yaml_parser().load_testbed_info()
    if name not in existing:
        raise HTTPException(status_code=404, detail=f"Infrastructure '{name}' not found")

    # Reject versions that already exist for this infra.
    existing_versions = set(existing[name].get("moodles", {}).keys())
    duplicates = [v for v in payload.moodle_versions if v in existing_versions]
    if duplicates:
        raise HTTPException(
            status_code=409,
            detail=f"Moodle version(s) already exist for '{name}': {', '.join(duplicates)}",
        )

    with _provisioning_lock:
        prov = _provisioning.get(name)
        if prov is not None:
            # Append to the existing in-flight list so polling picks it up.
            prov.setdefault("moodle_versions", []).extend(payload.moodle_versions)
        else:
            git_ref = existing[name].get("git_ref", {})
            _provisioning[name] = {
                "git_ref_type": git_ref.get("type", ""),
                "git_ref_reference": str(git_ref.get("reference", "")),
                "moodle_versions": list(payload.moodle_versions),
                "created_at": existing[name].get("created_at", ""),
                "phase": "queued",
            }

    background_tasks.add_task(_run_build_only, name, list(payload.moodle_versions))

    return AddContainersResponse(
        status="accepted",
        message=f"Building {len(payload.moodle_versions)} container(s) for {name}",
        name=name,
    )


@router.post("/{name}/{version}/start")
def start_container(name: str, version: str) -> dict:
    """Start a Moodle container for the given infrastructure and version."""
    try:
        core = _get_core()
        core.start_environment(name, version)
        return {"status": "ok", "message": f"Container {name}/{version} started"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{name}/{version}/stop")
def stop_container(name: str, version: str) -> dict:
    """Stop a Moodle container for the given infrastructure and version."""
    try:
        core = _get_core()
        core.stop_environment(name, version)
        return {"status": "ok", "message": f"Container {name}/{version} stopped"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{name}/{version}")
def destroy_container(name: str, version: str) -> dict:
    """Stop and destroy a Moodle container for the given infrastructure and version.

    This runs `docker-compose down` (which stops and removes the container),
    deletes the generated nginx config and the container working directory,
    and removes the entry from infrastructure.yaml.
    """
    try:
        core = _get_core()
        core.destroy_environment(name, version)
        return {"status": "ok", "message": f"Container {name}/{version} destroyed"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{name}")
def teardown_infrastructure(name: str) -> dict:
    """Tear down an entire infrastructure.

    Destroys all Moodle containers, removes their nginx configs, removes the
    entire infrastructure working directory, and removes the infrastructure
    entry from infrastructure.yaml.
    """
    try:
        core = _get_core()
        core.teardown_infrastructure(name)
        return {"status": "ok", "message": f"Infrastructure {name} torn down"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
