from fastapi import APIRouter

from theme_boost_union_test_envs.cross_cutting import yaml_parser
from ..models import InfrastructureListResponse, InfrastructureResponse, MoodleContainerResponse

router = APIRouter(prefix="/api/infrastructures", tags=["infrastructures"])


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
                )
            )

        infrastructures.append(
            InfrastructureResponse(
                name=name,
                git_ref_type=git_ref.get("type", ""),
                git_ref_reference=str(git_ref.get("reference", "")),
                moodles=moodles,
            )
        )

    return InfrastructureListResponse(infrastructures=infrastructures)
