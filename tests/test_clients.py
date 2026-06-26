from __future__ import annotations

import os
from typing import TYPE_CHECKING
from unittest.mock import patch

import boto3
from moto import mock_aws
import pytest

from app import clients

if TYPE_CHECKING:
    from collections.abc import Iterator

AWS_ENV = {
    "AWS_ACCESS_KEY_ID": "testing",
    "AWS_SECRET_ACCESS_KEY": "testing",
    "AWS_DEFAULT_REGION": "eu-central-1",
}


@pytest.fixture(autouse=True)
def _aws() -> Iterator[None]:
    with patch.dict(os.environ, AWS_ENV):
        clients.get_sqs_client.cache_clear()
        yield


@mock_aws
def test_get_sqs_client_returns_a_working_sqs_client() -> None:
    queue_url = boto3.client("sqs").create_queue(QueueName="test-queue")["QueueUrl"]

    client = clients.get_sqs_client()
    client.send_message(QueueUrl=queue_url, MessageBody="hello")

    messages = client.receive_message(QueueUrl=queue_url)["Messages"]
    assert [message["Body"] for message in messages] == ["hello"]


@mock_aws
def test_get_sqs_client_is_cached() -> None:
    assert clients.get_sqs_client() is clients.get_sqs_client()
