from typing import Any, Dict, Optional
from fastapi import status


class AppException(Exception):
    """
    Base exception class for application errors.
    """
    def __init__(
        self,
        message: str,
        status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR,
        error_code: str = "INTERNAL_SERVER_ERROR",
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.error_code = error_code
        self.details = details or {}


class BadRequestError(AppException):
    """
    Exception raised for invalid client requests (HTTP 400).
    """
    def __init__(
        self,
        message: str = "Bad Request",
        error_code: str = "BAD_REQUEST",
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(
            message=message,
            status_code=status.HTTP_400_BAD_REQUEST,
            error_code=error_code,
            details=details,
        )


class EntityNotFoundError(AppException):
    """
    Exception raised when a requested resource is not found (HTTP 404).
    """
    def __init__(
        self,
        message: str = "Resource not found",
        error_code: str = "NOT_FOUND",
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(
            message=message,
            status_code=status.HTTP_404_NOT_FOUND,
            error_code=error_code,
            details=details,
        )


class ConflictError(AppException):
    """
    Exception raised for state conflicts (HTTP 409).
    """
    def __init__(
        self,
        message: str = "Resource conflict",
        error_code: str = "CONFLICT",
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(
            message=message,
            status_code=status.HTTP_409_CONFLICT,
            error_code=error_code,
            details=details,
        )


class DatabaseConnectionError(AppException):
    """
    Exception raised when the database cannot be reached (HTTP 503).
    """
    def __init__(
        self,
        message: str = "Database connection unavailable",
        error_code: str = "SERVICE_UNAVAILABLE",
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(
            message=message,
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            error_code=error_code,
            details=details,
        )
