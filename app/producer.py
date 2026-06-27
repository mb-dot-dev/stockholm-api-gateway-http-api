from __future__ import annotations

import json
import os
from typing import TYPE_CHECKING

from aws_lambda_powertools import Logger
from aws_lambda_powertools.utilities.data_classes import APIGatewayProxyEventV2, event_source
from botocore.exceptions import ClientError

from app.allowlist import is_allowed, parse_allowed_networks
from app.clients import get_sqs_client

if TYPE_CHECKING:
    from aws_lambda_powertools.utilities.typing import LambdaContext

logger = Logger()


def _build_response(status_code: int, message: str) -> dict[str, object]:
    return {
        "statusCode": status_code,
        "headers": {"content-type": "application/json"},
        "body": json.dumps({"message": message}),
    }


@logger.inject_lambda_context
@event_source(data_class=APIGatewayProxyEventV2)
def lambda_handler(event: APIGatewayProxyEventV2, context: LambdaContext) -> dict[str, object]:  # noqa: ARG001
    source_ip = event.request_context.http.source_ip
    claims = event.request_context.authorizer.jwt_claim
    principal = claims.get("sub")

    allowed_client_id = os.environ.get("ALLOWED_CLIENT_ID")
    if allowed_client_id is not None and principal != allowed_client_id:
        logger.warning(
            "Request denied by client ID allowlist",
            extra={"sourceIp": source_ip, "principal": principal, "decision": "DENY"},
        )
        return _build_response(403, "Forbidden")

    networks = parse_allowed_networks(os.environ.get("ALLOWED_IPS", ""))
    if not is_allowed(source_ip, networks):
        logger.warning(
            "Request denied by IP allowlist",
            extra={"sourceIp": source_ip, "principal": principal, "decision": "DENY"},
        )
        return _build_response(403, "Forbidden")

    try:
        result = get_sqs_client().send_message(QueueUrl=os.environ["QUEUE_URL"], MessageBody=event.body or "")
    except ClientError:
        logger.exception(
            "Failed to enqueue message",
            extra={"sourceIp": source_ip, "principal": principal, "decision": "ERROR"},
        )
        return _build_response(500, "Internal Server Error")

    logger.info(
        "Request allowed and enqueued",
        extra={
            "sourceIp": source_ip,
            "principal": principal,
            "decision": "ALLOW",
            "messageId": result["MessageId"],
        },
    )
    return _build_response(202, "Accepted")
