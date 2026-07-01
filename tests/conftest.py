from __future__ import annotations

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
