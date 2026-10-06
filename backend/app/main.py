from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from sqlalchemy import Engine, text
from sqlalchemy.exc import SQLAlchemyError

from app.config import Settings
from app.database import build_engine, build_session_factory
from app.api import router
from app.auth_service import AuthError, AuthService


def create_app(settings: Settings | None = None, engine: Engine | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        active_settings = settings if settings is not None else Settings()
        active_engine = engine if engine is not None else build_engine(active_settings)
        application.state.settings = active_settings
        application.state.engine = active_engine
        application.state.session_factory = build_session_factory(active_engine)
        application.state.auth = AuthService(active_engine, active_settings)
        try:
            yield
        finally:
            if engine is None:
                active_engine.dispose()

    application = FastAPI(
        title="OfflineWallet research prototype",
        version="0.2.0",
        lifespan=lifespan,
    )

    application.include_router(router)

    @application.middleware("http")
    async def no_cache(request: Request, call_next):
        response = await call_next(request)
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
            response.headers["Pragma"] = "no-cache"
        return response

    @application.exception_handler(AuthError)
    async def auth_error(request: Request, error: AuthError):
        return JSONResponse(status_code=error.status, content={"detail": error.message})

    @application.exception_handler(RequestValidationError)
    async def validation_error(request: Request, error: RequestValidationError):
        # FastAPI's default error includes input values (potentially a password or token).
        return JSONResponse(status_code=422, content={"detail": [
            {"loc": list(e["loc"]), "msg": "Invalid request field", "type": e["type"]} for e in error.errors()]})

    @application.exception_handler(SQLAlchemyError)
    async def database_error(request: Request, error: SQLAlchemyError):
        return JSONResponse(status_code=503, content={"detail": "Service temporarily unavailable"})

    @application.get("/health")
    def health() -> dict[str, str]:
        """Process liveness, independent of database connectivity."""
        return {"status": "ok"}

    @application.get("/health/ready", responses={503: {"description": "Database unavailable"}})
    def ready(request: Request) -> JSONResponse:
        """Check PostgreSQL with a read-only query; never create or seed data."""
        try:
            with request.app.state.engine.connect() as connection:
                connection.execute(text("SELECT 1"))
        except SQLAlchemyError:
            # Do not return or log connection details, credentials, or exception text.
            return JSONResponse(
                status_code=503,
                content={"status": "not_ready", "database": "unavailable"},
            )
        return JSONResponse(content={"status": "ready", "database": "ok"})

    return application


app = create_app()
