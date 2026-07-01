from __future__ import annotations

import json
import os
from typing import TYPE_CHECKING

from aws_lambda_powertools import Logger
from aws_lambda_powertools.event_handler import APIGatewayHttpResolver
from aws_lambda_powertools.event_handler.api_gateway import Response
from botocore.exceptions import ClientError

from app.allowlist import is_allowed, parse_allowed_networks
from app.clients import get_sqs_client
from app.oauth import router as oauth_router

if TYPE_CHECKING:
    from aws_lambda_powertools.utilities.typing import LambdaContext

logger = Logger()
app = APIGatewayHttpResolver()
app.include_router(oauth_router)


@app.post("/")
def _enqueue() -> Response:
    event = app.current_event
    source_ip = event.request_context.http.source_ip
    claims = event.request_context.authorizer.jwt_claim
    principal = claims.get("sub")

    allowed_client_id = os.environ.get("ALLOWED_CLIENT_ID")
    if allowed_client_id is not None and principal != allowed_client_id:
        logger.warning(
            "Request denied by client ID allowlist",
            extra={"sourceIp": source_ip, "principal": principal, "decision": "DENY"},
        )
        return Response(status_code=403, content_type="application/json", body=json.dumps({"message": "Forbidden"}))

    networks = parse_allowed_networks(os.environ.get("ALLOWED_IPS", ""))
    if not is_allowed(source_ip, networks):
        logger.warning(
            "Request denied by IP allowlist",
            extra={"sourceIp": source_ip, "principal": principal, "decision": "DENY"},
        )
        return Response(status_code=403, content_type="application/json", body=json.dumps({"message": "Forbidden"}))

    try:
        result = get_sqs_client().send_message(QueueUrl=os.environ["QUEUE_URL"], MessageBody=event.body or "")
    except ClientError:
        logger.exception(
            "Failed to enqueue message",
            extra={"sourceIp": source_ip, "principal": principal, "decision": "ERROR"},
        )
        return Response(
            status_code=500,
            content_type="application/json",
            body=json.dumps({"message": "Internal Server Error"}),
        )

    logger.info(
        "Request allowed and enqueued",
        extra={
            "sourceIp": source_ip,
            "principal": principal,
            "decision": "ALLOW",
            "messageId": result["MessageId"],
        },
    )
    return Response(status_code=202, content_type="application/json", body=json.dumps({"message": "Accepted"}))


@logger.inject_lambda_context
def lambda_handler(event: dict[str, object], context: LambdaContext) -> dict[str, object]:
    return app.resolve(event, context)
