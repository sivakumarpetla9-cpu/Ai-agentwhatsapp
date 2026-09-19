from contextlib import asynccontextmanager
from typing import AsyncGenerator
from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.v1.router import api_router
from app.core.config import get_settings
from app.core.exceptions import AppException
from app.core.logging import get_logger, setup_logging
from app.database.session import engine

# Initialize logging configuration
setup_logging()
logger = get_logger("app.main")
settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """
    Application lifespan context manager managing startup and shutdown tasks.
    """
    logger.info(
        f"Starting {settings.PROJECT_NAME} in '{settings.ENVIRONMENT}' mode "
        f"(debug={settings.DEBUG})."
    )
    yield
    logger.info("Shutting down application and releasing database resources...")
    await engine.dispose()
    logger.info("Application shutdown complete.")


def create_application() -> FastAPI:
    """
    FastAPI application factory.
    """
    application = FastAPI(
        title=settings.PROJECT_NAME,
        description="Production-oriented V1 WhatsApp Dine-In Restaurant Ordering Platform API",
        version="1.0.0",
        openapi_url=f"{settings.API_V1_STR}/openapi.json",
        docs_url="/docs",
        redoc_url="/redoc",
        lifespan=lifespan,
    )

    # 1. Mount CORS Middleware
    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # 2. Security Headers Middleware
    @application.middleware("http")
    async def add_security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        return response

    # Register Global Exception Handlers
    @application.exception_handler(AppException)
    async def app_exception_handler(
        request: Request, exc: AppException
    ) -> JSONResponse:
        logger.warning(
            f"Handled AppException: code={exc.error_code} status={exc.status_code} "
            f"path={request.url.path} message={exc.message}"
        )
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": {
                    "code": exc.error_code,
                    "message": exc.message,
                    "details": exc.details if exc.details else None,
                }
            },
        )

    @application.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        logger.warning(f"Validation error on {request.url.path}: {exc.errors()}")
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "VALIDATION_ERROR",
                    "message": "Invalid request parameters or payload.",
                    "details": {"validation_errors": exc.errors()},
                }
            },
        )

    @application.exception_handler(Exception)
    async def general_exception_handler(
        request: Request, exc: Exception
    ) -> JSONResponse:
        logger.exception(f"Unhandled exception on {request.url.path}: {exc}")
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "error": {
                    "code": "INTERNAL_SERVER_ERROR",
                    "message": "An unexpected error occurred. Please try again later.",
                    "details": None,
                }
            },
        )

    # Mount API Routers
    application.include_router(api_router, prefix=settings.API_V1_STR)

    return application


app = create_application()
