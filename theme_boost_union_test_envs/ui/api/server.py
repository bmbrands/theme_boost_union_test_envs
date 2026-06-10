from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from theme_boost_union_test_envs.cross_cutting.log_buffer import install_log_capture

from .routes import (
    audit_router,
    infrastructures_router,
    logs_router,
    moodle_router,
    plugins_router,
    settings_router,
)


def create_app() -> FastAPI:
    # Capture application + uvicorn logs into the in-memory buffer so the
    # frontend can show the same output as the server terminal.
    install_log_capture()

    app = FastAPI(
        title="Boost Union Test Environments API",
        description="API for managing Moodle test environments with the Boost Union theme",
        version="0.1.0",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:5173",   # Vite dev server
            "http://localhost:3000",
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(infrastructures_router)
    app.include_router(plugins_router)
    app.include_router(moodle_router)
    app.include_router(audit_router)
    app.include_router(settings_router)
    app.include_router(logs_router)

    return app


app = create_app()
