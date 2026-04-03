from pydantic import BaseModel


class MoodleContainerResponse(BaseModel):
    moodle_version: str
    status: str
    url: str
    admin_password: str
    www_port: str
    db_port: str


class InfrastructureResponse(BaseModel):
    name: str
    git_ref_type: str
    git_ref_reference: str
    moodles: list[MoodleContainerResponse]


class InfrastructureListResponse(BaseModel):
    infrastructures: list[InfrastructureResponse]
