from token_governor.classifier import classify_request


def test_classifier_detects_debugging_test_and_code_generation() -> None:
    assert classify_request("pytest failed test AssertionError") == "test_output"
    assert classify_request("Traceback error: ValueError in app.py") == "debugging"
    assert classify_request("Please implement a FastAPI route") == "code_generation"
