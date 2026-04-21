from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .routes import infrastructures_router, moodle_router, plugins_router


def create_app() -> FastAPI:
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

    return app


app = create_app()
