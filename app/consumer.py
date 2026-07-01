import json
from typing import TYPE_CHECKING

from aws_lambda_powertools import Logger, Metrics
from aws_lambda_powertools.metrics import MetricUnit
from aws_lambda_powertools.utilities.batch import (
    BatchProcessor,
    EventType,
    process_partial_response,
)
from aws_lambda_powertools.utilities.data_classes import (
    SQSRecord,  # noqa: TC002 (BatchProcessor introspects this annotation at runtime)
)

if TYPE_CHECKING:
    from aws_lambda_powertools.utilities.batch.types import PartialItemFailureResponse
    from aws_lambda_powertools.utilities.typing import LambdaContext

processor = BatchProcessor(event_type=EventType.SQS)
logger = Logger()
metrics = Metrics(namespace="Stockholm")


def record_handler(record: SQSRecord) -> None:
    try:
        payload: dict = record.json_body
    except json.JSONDecodeError:
        metrics.add_metric(name="BatchItemFailure", unit=MetricUnit.Count, value=1)
        raise

    logger.info("Processing record", extra={"payload": payload})


@metrics.log_metrics
@logger.inject_lambda_context
def lambda_handler(event: dict, context: LambdaContext) -> PartialItemFailureResponse:
    return process_partial_response(
        event=event,
        record_handler=record_handler,
        processor=processor,
        context=context,
    )
