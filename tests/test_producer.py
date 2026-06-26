from __future__ import annotations

import json
import os
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

from botocore.exceptions import ClientError
import pytest

from app import producer

if TYPE_CHECKING:
    from collections.abc import Iterator

    from tests.conftest import FakeLambdaContext

QUEUE_URL = "https://sqs.eu-central-1.amazonaws.com/123456789012/test-queue"


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


@pytest.fixture
def sqs_client() -> Iterator[MagicMock]:
    client = MagicMock()
    env = {"ALLOWED_IPS": "10.0.0.0/8", "QUEUE_URL": QUEUE_URL}
    with patch.dict(os.environ, env), patch.object(producer, "get_sqs_client", return_value=client):
        yield client


def test_handler_allowed_request_is_enqueued(sqs_client: MagicMock, lambda_context: FakeLambdaContext) -> None:
    sqs_client.send_message.return_value = {"MessageId": "msg-1"}

    response = producer.lambda_handler(_build_event("10.1.2.3"), lambda_context)

    assert response == {
        "statusCode": 202,
        "headers": {"content-type": "application/json"},
        "body": json.dumps({"message": "Accepted"}),
    }
    sqs_client.send_message.assert_called_once_with(QueueUrl=QUEUE_URL, MessageBody='{"hello": "world"}')


def test_handler_disallowed_ip_is_forbidden(sqs_client: MagicMock, lambda_context: FakeLambdaContext) -> None:
    response = producer.lambda_handler(_build_event("192.168.1.1"), lambda_context)

    assert response["statusCode"] == 403
    assert json.loads(response["body"]) == {"message": "Forbidden"}
    sqs_client.send_message.assert_not_called()


def test_handler_sqs_failure_returns_500(sqs_client: MagicMock, lambda_context: FakeLambdaContext) -> None:
    sqs_client.send_message.side_effect = ClientError(
        {"Error": {"Code": "InternalError", "Message": "boom"}},
        "SendMessage",
    )

    response = producer.lambda_handler(_build_event("10.1.2.3"), lambda_context)

    assert response["statusCode"] == 500


def test_handler_empty_body_sends_empty_string(sqs_client: MagicMock, lambda_context: FakeLambdaContext) -> None:
    sqs_client.send_message.return_value = {"MessageId": "msg-1"}

    producer.lambda_handler(_build_event("10.1.2.3", body=""), lambda_context)

    assert sqs_client.send_message.call_args.kwargs["MessageBody"] == ""
