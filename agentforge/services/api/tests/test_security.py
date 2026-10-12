import pytest

from app.services.security import SecurityValidationError, validate_repository


@pytest.mark.parametrize("path", ["../escape.py", "/absolute.py", "src/../../escape.py"])
def test_path_traversal_is_blocked(path: str) -> None:
    with pytest.raises(SecurityValidationError):
        validate_repository({path: "print('no')"})


def test_dynamic_evaluation_is_blocked() -> None:
    with pytest.raises(SecurityValidationError, match="dynamic evaluation"):
        validate_repository({"src/main.py": "result = eval(user_input)"})
