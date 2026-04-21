from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from theme_boost_union_test_envs.cross_cutting import yaml_parser
from ..models import InfrastructureListResponse, InfrastructureResponse, MoodleContainerResponse

router = APIRouter(prefix="/api/infrastructures", tags=["infrastructures"])


def _get_core():
    """Get the BoostUnionTestEnvCore singleton from the DI container."""
    from theme_boost_union_test_envs.app import Application
    return Application().core()


class CreateInfrastructureRequest(BaseModel):
    name: str = Field(..., min_length=1, description="Unique infrastructure name")
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

        infrastructures.append(
            InfrastructureResponse(
                name=name,
                git_ref_type=git_ref.get("type", ""),
                git_ref_reference=str(git_ref.get("reference", "")),
                created_at=data.get("created_at", ""),
                moodles=moodles,
            )
        )

    return InfrastructureListResponse(infrastructures=infrastructures)


@router.post("", response_model=CreateInfrastructureResponse)
def create_infrastructure(payload: CreateInfrastructureRequest) -> CreateInfrastructureResponse:
    """Create a new infrastructure and build Moodle containers for it.

    Equivalent to running:

        boost-union-envs setup <name> <git_ref_type> <git_ref>
        boost-union-envs build <name> <moodle_version> [<moodle_version> ...]
    """
    # Import here to avoid importing GitPython at module load time.
    from theme_boost_union_test_envs.domain.git import GitReference, GitReferenceType
    from theme_boost_union_test_envs.exceptions import (
        InfrastructureDoesNotExistYetError,
        InvalidMoodleVersionError,
        NameAlreadyTakenError,
        TestbedDoesNotExistYetError,
        UnsupportedMoodleVersionError,
    )

    core = _get_core()

    # PRs are passed as ints in the domain layer.
    ref: str | int = payload.git_ref
    if payload.git_ref_type == "pr":
        try:
            ref = int(payload.git_ref)
        except ValueError as e:
            raise HTTPException(status_code=400, detail="PR reference must be numeric") from e

    try:
        git_ref = GitReference(ref, GitReferenceType(payload.git_ref_type))
        core.setup_infrastructure(payload.name, git_ref)
        core.build_infrastructure(payload.name, *payload.moodle_versions)
    except NameAlreadyTakenError as e:
        raise HTTPException(status_code=409, detail=f"Infrastructure '{payload.name}' already exists") from e
    except TestbedDoesNotExistYetError as e:
        raise HTTPException(status_code=412, detail="Testbed has not been initialised yet. Run `init` first.") from e
    except InfrastructureDoesNotExistYetError as e:
        raise HTTPException(status_code=500, detail="Infrastructure disappeared during build") from e
    except UnsupportedMoodleVersionError as e:
        raise HTTPException(status_code=400, detail=f"Unsupported Moodle version: {e.version}") from e
    except InvalidMoodleVersionError as e:
        raise HTTPException(status_code=400, detail=f"Invalid Moodle version: {e.version}") from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e

    return CreateInfrastructureResponse(
        status="ok",
        message=f"Infrastructure {payload.name} created with {len(payload.moodle_versions)} container(s)",
        name=payload.name,
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
