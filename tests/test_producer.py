from __future__ import annotations

import json
import os
from typing import TYPE_CHECKING
from unittest.mock import patch

import boto3
from moto import mock_aws
import pytest

from app import clients, producer

if TYPE_CHECKING:
    from collections.abc import Iterator

    from tests.conftest import FakeLambdaContext

AWS_ENV = {
    "AWS_ACCESS_KEY_ID": "testing",
    "AWS_SECRET_ACCESS_KEY": "testing",
    "AWS_DEFAULT_REGION": "eu-central-1",
}
ALLOWED_IPS = "10.0.0.0/8"


def _build_event(source_ip: str, *, sub: str = "auth0|user", body: str = '{"hello": "world"}') -> dict:
    return {
        "version": "2.0",
        "routeKey": "POST /",
        "rawPath": "/",
        "body": body,
        "requestContext": {
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
    response = producer.lambda_handler(_build_event("10.1.2.3"), lambda_context)

    assert response == {
        "statusCode": 202,
        "headers": {"content-type": "application/json"},
        "body": json.dumps({"message": "Accepted"}),
    }
    messages = boto3.client("sqs").receive_message(QueueUrl=sqs_queue).get("Messages", [])
    assert [m["Body"] for m in messages] == ['{"hello": "world"}']


def test_handler_disallowed_ip_is_forbidden(lambda_context: FakeLambdaContext) -> None:
    response = producer.lambda_handler(_build_event("192.168.1.1"), lambda_context)

    assert response["statusCode"] == 403
    assert json.loads(response["body"]) == {"message": "Forbidden"}


def test_handler_sqs_failure_returns_500(lambda_context: FakeLambdaContext) -> None:
    bad_url = "https://sqs.eu-central-1.amazonaws.com/123456789012/nonexistent"
    with mock_aws(), patch.dict(os.environ, {"QUEUE_URL": bad_url}):
        response = producer.lambda_handler(_build_event("10.1.2.3"), lambda_context)

    assert response["statusCode"] == 500


def test_handler_empty_body_sends_empty_string(sqs_queue: str, lambda_context: FakeLambdaContext) -> None:
    producer.lambda_handler(_build_event("10.1.2.3", body=""), lambda_context)

    messages = boto3.client("sqs").receive_message(QueueUrl=sqs_queue).get("Messages", [])
    assert [m["Body"] for m in messages] == [""]
