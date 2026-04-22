from pydantic import BaseModel


class MoodleContainerResponse(BaseModel):
    moodle_version: str
    status: str
    url: str
    admin_password: str
    www_port: str
    db_port: str
    created_at: str


class InfrastructureResponse(BaseModel):
    name: str
    git_ref_type: str
    git_ref_reference: str
    created_at: str
    moodles: list[MoodleContainerResponse]
    # When the infrastructure is still being provisioned, this reports the
    # current phase (reserving / cloning / building / initializing / error).
    # Empty/None when the infrastructure is ready.
    provisioning_phase: str | None = None
    provisioning_error: str | None = None


class InfrastructureListResponse(BaseModel):
    infrastructures: list[InfrastructureResponse]
