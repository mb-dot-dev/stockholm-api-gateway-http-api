import json
import os

from aws_lambda_powertools import Logger, Metrics
from aws_lambda_powertools.event_handler.api_gateway import Response
from aws_lambda_powertools.event_handler.router import APIGatewayHttpRouter
from aws_lambda_powertools.metrics import MetricUnit
from botocore.exceptions import ClientError

from app.allowlist import is_allowed, parse_allowed_networks
from app.clients import get_sqs_client

logger = Logger()
metrics = Metrics(namespace="Stockholm")
router = APIGatewayHttpRouter()


@router.post("/")
def enqueue() -> Response:
    event = router.current_event
    source_ip = event.request_context.http.source_ip
    claims = event.request_context.authorizer.jwt_claim
    principal = claims.get("sub")

    allowed_client_id = os.environ.get("ALLOWED_CLIENT_ID")
    if allowed_client_id is not None and principal != allowed_client_id:
        logger.warning(
            "Request denied by client ID allowlist",
            extra={"sourceIp": source_ip, "principal": principal, "decision": "DENY"},
        )
        metrics.add_dimension(name="reason", value="ClientIdAllowlist")
        metrics.add_metric(name="RequestDenied", unit=MetricUnit.Count, value=1)
        return Response(status_code=403, content_type="application/json", body=json.dumps({"message": "Forbidden"}))

    networks = parse_allowed_networks(os.environ.get("ALLOWED_IPS", ""))
    if not is_allowed(source_ip, networks):
        logger.warning(
            "Request denied by IP allowlist",
            extra={"sourceIp": source_ip, "principal": principal, "decision": "DENY"},
        )
        metrics.add_dimension(name="reason", value="IpAllowlist")
        metrics.add_metric(name="RequestDenied", unit=MetricUnit.Count, value=1)
        return Response(status_code=403, content_type="application/json", body=json.dumps({"message": "Forbidden"}))

    try:
        result = get_sqs_client().send_message(QueueUrl=os.environ["QUEUE_URL"], MessageBody=event.body or "")
    except ClientError:
        logger.exception(
            "Failed to enqueue message",
            extra={"sourceIp": source_ip, "principal": principal, "decision": "ERROR"},
        )
        metrics.add_metric(name="EnqueueFailure", unit=MetricUnit.Count, value=1)
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
