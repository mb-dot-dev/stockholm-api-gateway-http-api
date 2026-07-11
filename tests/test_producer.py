import json
import os
from typing import TYPE_CHECKING
from unittest.mock import patch

import boto3
from moto import mock_aws
import pytest

from app import clients, main
from tests.conftest import find_emf_metric

if TYPE_CHECKING:
    from collections.abc import Iterator

    from tests.conftest import FakeLambdaContext

AWS_ENV = {
    "AWS_ACCESS_KEY_ID": "testing",
    "AWS_SECRET_ACCESS_KEY": "testing",
    "AWS_DEFAULT_REGION": "eu-central-1",
}
ALLOWED_IPS = "10.0.0.0/8"
ALLOWED_CLIENT_ID = "clientid@clients"


def _build_event(source_ip: str, *, sub: str = "auth0|user", body: str = '{"hello": "world"}') -> dict:
    return {
        "version": "2.0",
        "routeKey": "POST /",
        "rawPath": "/",
        "rawQueryString": "",
        "body": body,
        "requestContext": {
            "stage": "$default",
            "http": {
                "method": "POST",
                "path": "/",
                "sourceIp": source_ip,
            },
            "authorizer": {"jwt": {"claims": {"sub": sub}}},
        },
    }


@pytest.fixture(autouse=True)
def _aws_env() -> Iterator[None]:
    with patch.dict(os.environ, {**AWS_ENV, "ALLOWED_IPS": ALLOWED_IPS}):
        clients.get_sqs_client.cache_clear()
        yield


@pytest.fixture
def sqs_queue() -> Iterator[str]:
    with mock_aws():
        url = boto3.client("sqs", region_name="eu-central-1").create_queue(QueueName="test-queue")["QueueUrl"]
        with patch.dict(os.environ, {"QUEUE_URL": url}):
            yield url


def test_handler_allowed_request_is_enqueued(sqs_queue: str, lambda_context: FakeLambdaContext) -> None:
    response = main.lambda_handler(_build_event("10.1.2.3"), lambda_context)

    assert response["statusCode"] == 202
    assert json.loads(str(response["body"])) == {"message": "Accepted"}
    messages = boto3.client("sqs").receive_message(QueueUrl=sqs_queue).get("Messages", [])
    assert [m["Body"] for m in messages] == ['{"hello": "world"}']


def test_handler_disallowed_ip_is_forbidden(lambda_context: FakeLambdaContext) -> None:
    response = main.lambda_handler(_build_event("192.168.1.1"), lambda_context)

    assert response["statusCode"] == 403
    assert json.loads(str(response["body"])) == {"message": "Forbidden"}


def test_handler_sqs_failure_returns_500(lambda_context: FakeLambdaContext) -> None:
    bad_url = "https://sqs.eu-central-1.amazonaws.com/123456789012/nonexistent"
    with mock_aws(), patch.dict(os.environ, {"QUEUE_URL": bad_url}):
        response = main.lambda_handler(_build_event("10.1.2.3"), lambda_context)

    assert response["statusCode"] == 500


def test_handler_empty_body_sends_empty_string(sqs_queue: str, lambda_context: FakeLambdaContext) -> None:
    main.lambda_handler(_build_event("10.1.2.3", body=""), lambda_context)

    messages = boto3.client("sqs").receive_message(QueueUrl=sqs_queue).get("Messages", [])
    assert [m["Body"] for m in messages] == [""]


def test_handler_disallowed_client_id_is_forbidden(lambda_context: FakeLambdaContext) -> None:
    with patch.dict(os.environ, {"ALLOWED_CLIENT_ID": ALLOWED_CLIENT_ID}):
        response = main.lambda_handler(_build_event("10.1.2.3", sub="other-client@clients"), lambda_context)

    assert response["statusCode"] == 403
    assert json.loads(str(response["body"])) == {"message": "Forbidden"}


def test_handler_allowed_client_id_is_accepted(sqs_queue: str, lambda_context: FakeLambdaContext) -> None:
    with patch.dict(os.environ, {"ALLOWED_CLIENT_ID": ALLOWED_CLIENT_ID}):
        response = main.lambda_handler(_build_event("10.1.2.3", sub=ALLOWED_CLIENT_ID), lambda_context)

    assert response["statusCode"] == 202


def test_handler_no_client_id_restriction_allows_any_client(sqs_queue: str, lambda_context: FakeLambdaContext) -> None:
    response = main.lambda_handler(_build_event("10.1.2.3", sub="any-client@clients"), lambda_context)

    assert response["statusCode"] == 202


def test_handler_disallowed_ip_emits_denied_metric(
    capsys: pytest.CaptureFixture[str], lambda_context: FakeLambdaContext
) -> None:
    main.lambda_handler(_build_event("192.168.1.1"), lambda_context)

    metric = find_emf_metric(capsys, "RequestDenied")
    assert metric["RequestDenied"] == [1.0]
    assert metric["reason"] == "IpAllowlist"


def test_handler_disallowed_client_id_emits_denied_metric(
    capsys: pytest.CaptureFixture[str], lambda_context: FakeLambdaContext
) -> None:
    with patch.dict(os.environ, {"ALLOWED_CLIENT_ID": ALLOWED_CLIENT_ID}):
        main.lambda_handler(_build_event("10.1.2.3", sub="other-client@clients"), lambda_context)

    metric = find_emf_metric(capsys, "RequestDenied")
    assert metric["RequestDenied"] == [1.0]
    assert metric["reason"] == "ClientIdAllowlist"


def test_handler_sqs_failure_emits_enqueue_failure_metric(
    capsys: pytest.CaptureFixture[str], lambda_context: FakeLambdaContext
) -> None:
    bad_url = "https://sqs.eu-central-1.amazonaws.com/123456789012/nonexistent"
    with mock_aws(), patch.dict(os.environ, {"QUEUE_URL": bad_url}):
        main.lambda_handler(_build_event("10.1.2.3"), lambda_context)

    metric = find_emf_metric(capsys, "EnqueueFailure")
    assert metric["EnqueueFailure"] == [1.0]
