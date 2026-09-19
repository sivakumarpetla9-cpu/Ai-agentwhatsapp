from app.core.exceptions import AppException, BadRequestError, EntityNotFoundError, ConflictError


def test_app_exception_attributes() -> None:
    exc = AppException(message="Test error", status_code=500, error_code="TEST_ERROR", details={"key": "val"})
    assert exc.message == "Test error"
    assert exc.status_code == 500
    assert exc.error_code == "TEST_ERROR"
    assert exc.details == {"key": "val"}


def test_specialized_exceptions() -> None:
    bad_req = BadRequestError("Invalid input", details={"field": "amount"})
    assert bad_req.status_code == 400
    assert bad_req.error_code == "BAD_REQUEST"

    not_found = EntityNotFoundError("Resource not found")
    assert not_found.status_code == 404
    assert not_found.error_code == "NOT_FOUND"

    conflict = ConflictError("Resource already exists")
    assert conflict.status_code == 409
    assert conflict.error_code == "CONFLICT"
