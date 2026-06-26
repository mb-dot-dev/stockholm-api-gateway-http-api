from __future__ import annotations

import pytest


class FakeLambdaContext:
    function_name = "test-function"
    function_version = "$LATEST"
    memory_limit_in_mb = 128
    invoked_function_arn = "arn:aws:lambda:eu-central-1:123456789012:function:test-function"
    aws_request_id = "test-request-id"


@pytest.fixture
def lambda_context() -> FakeLambdaContext:
    return FakeLambdaContext()
