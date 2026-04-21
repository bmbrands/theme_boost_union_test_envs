from fastapi import APIRouter, HTTPException

from theme_boost_union_test_envs.cross_cutting import yaml_parser
from ..models import InfrastructureListResponse, InfrastructureResponse, MoodleContainerResponse

router = APIRouter(prefix="/api/infrastructures", tags=["infrastructures"])


def _get_core():
    """Get the BoostUnionTestEnvCore singleton from the DI container."""
    from theme_boost_union_test_envs.app import Application
    return Application().core()


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
