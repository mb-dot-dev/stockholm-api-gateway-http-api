from __future__ import annotations

import json
from typing import TYPE_CHECKING

from app import consumer

if TYPE_CHECKING:
    from tests.conftest import FakeLambdaContext


def _sqs_event(*bodies: str) -> dict:
    return {
        "Records": [
            {
                "messageId": f"msg-{index}",
                "receiptHandle": f"handle-{index}",
                "body": body,
                "attributes": {},
                "messageAttributes": {},
                "md5OfBody": "0",
                "eventSource": "aws:sqs",
                "eventSourceARN": "arn:aws:sqs:eu-central-1:123456789012:test-queue",
                "awsRegion": "eu-central-1",
            }
            for index, body in enumerate(bodies)
        ]
    }


def test_lambda_handler_processes_batch(lambda_context: FakeLambdaContext) -> None:
    event = _sqs_event(json.dumps({"a": 1}), json.dumps({"b": 2}))

    result = consumer.lambda_handler(event, lambda_context)

    assert result == {"batchItemFailures": []}


def test_lambda_handler_reports_partial_failure_on_invalid_json(lambda_context: FakeLambdaContext) -> None:
    # A mixed batch: the valid record succeeds, the malformed one is reported back to SQS for retry.
    event = _sqs_event(json.dumps({"a": 1}), "not-json")

    result = consumer.lambda_handler(event, lambda_context)

    assert result["batchItemFailures"] == [{"itemIdentifier": "msg-1"}]
