from __future__ import annotations

import ipaddress
import json
import os
from typing import TYPE_CHECKING

from aws_lambda_powertools import Logger
import boto3
from botocore.exceptions import ClientError

if TYPE_CHECKING:
    from aws_lambda_powertools.utilities.typing import LambdaContext

logger = Logger()
sqs_client = boto3.client("sqs")

IpNetwork = ipaddress.IPv4Network | ipaddress.IPv6Network


def _parse_allowed_networks(raw: str) -> list[IpNetwork]:
    networks: list[IpNetwork] = []
    for entry in raw.split(","):
        candidate = entry.strip()
        if not candidate:
            continue
        try:
            networks.append(ipaddress.ip_network(candidate, strict=False))
        except ValueError:
            logger.warning("Ignoring invalid allowlist entry", extra={"entry": candidate})
    return networks


def _is_allowed(source_ip: str | None, networks: list[IpNetwork]) -> bool:
    if not source_ip or not networks:
        return False
    try:
        address = ipaddress.ip_address(source_ip)
    except ValueError:
        return False
    return any(address in network for network in networks)


def _response(status_code: int, message: str) -> dict[str, object]:
    return {
        "statusCode": status_code,
        "headers": {"content-type": "application/json"},
        "body": json.dumps({"message": message}),
    }


@logger.inject_lambda_context
def lambda_handler(event: dict, context: LambdaContext) -> dict[str, object]:  # noqa: ARG001
    request_context = event.get("requestContext", {})
    source_ip = request_context.get("http", {}).get("sourceIp")
    claims = request_context.get("authorizer", {}).get("jwt", {}).get("claims", {})
    principal = claims.get("sub")

    networks = _parse_allowed_networks(os.environ.get("ALLOWED_IPS", ""))
    if not _is_allowed(source_ip, networks):
        logger.warning(
            "Request denied by IP allowlist",
            extra={"sourceIp": source_ip, "principal": principal, "decision": "DENY"},
        )
        return _response(403, "Forbidden")

    try:
        result = sqs_client.send_message(QueueUrl=os.environ["QUEUE_URL"], MessageBody=event.get("body") or "")
    except ClientError:
        logger.exception(
            "Failed to enqueue message",
            extra={"sourceIp": source_ip, "principal": principal, "decision": "ERROR"},
        )
        return _response(500, "Internal Server Error")

    logger.info(
        "Request allowed and enqueued",
        extra={
            "sourceIp": source_ip,
            "principal": principal,
            "decision": "ALLOW",
            "messageId": result["MessageId"],
        },
    )
    return _response(202, "Accepted")
