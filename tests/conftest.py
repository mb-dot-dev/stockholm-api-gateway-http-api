import json

from aws_lambda_powertools.utilities.typing import LambdaContext
import pytest


class FakeLambdaContext(LambdaContext):
    _function_name = "test-function"
    _function_version = "$LATEST"
    _memory_limit_in_mb = 128
    _invoked_function_arn = "arn:aws:lambda:eu-central-1:123456789012:function:test-function"
    _aws_request_id = "test-request-id"
    _log_group_name = ""
    _log_stream_name = ""


@pytest.fixture
def lambda_context() -> FakeLambdaContext:
    return FakeLambdaContext()


def find_emf_metric(capsys: pytest.CaptureFixture[str], name: str) -> dict:
    """Find and return the EMF payload that published the named metric from captured stdout."""
    for line in capsys.readouterr().out.strip().splitlines():
        payload = json.loads(line)
        if "_aws" in payload and name in payload:
            return payload
    pytest.fail(f"metric {name!r} not found in captured stdout")
