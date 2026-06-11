from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from theme_boost_union_test_envs.cross_cutting.log_buffer import install_log_capture
from theme_boost_union_test_envs.cross_cutting.user_store import user_store

from .routes import (
    audit_router,
    auth_router,
    infrastructures_router,
    logs_router,
    moodle_router,
    plugins_router,
    settings_router,
    users_router,
)
from .security import active_user


def create_app() -> FastAPI:
    # Capture application + uvicorn logs into the in-memory buffer so the
    # frontend can show the same output as the server terminal.
    install_log_capture()

    # Ensure there is always at least one (admin) account to log in with.
    user_store().ensure_seed_admin()

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

    # Auth endpoints are public (they perform their own checks). Everything
    # else requires an authenticated, password-current session.
    protected = [Depends(active_user)]
    app.include_router(auth_router)
    app.include_router(infrastructures_router, dependencies=protected)
    app.include_router(plugins_router, dependencies=protected)
    app.include_router(moodle_router, dependencies=protected)
    app.include_router(audit_router, dependencies=protected)
    app.include_router(settings_router, dependencies=protected)
    app.include_router(logs_router, dependencies=protected)
    app.include_router(users_router)

    return app


app = create_app()
