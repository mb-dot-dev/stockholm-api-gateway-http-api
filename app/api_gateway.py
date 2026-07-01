from typing import TYPE_CHECKING

from aws_lambda_powertools import Logger, Metrics
from aws_lambda_powertools.event_handler import APIGatewayHttpResolver

from app.oauth import router as oauth_router
from app.producer import router as producer_router

if TYPE_CHECKING:
    from aws_lambda_powertools.utilities.typing import LambdaContext

logger = Logger()
metrics = Metrics(namespace="Stockholm")
app = APIGatewayHttpResolver()
app.include_router(oauth_router)
app.include_router(producer_router)


@metrics.log_metrics
@logger.inject_lambda_context
def lambda_handler(event: dict[str, object], context: LambdaContext) -> dict[str, object]:
    return app.resolve(event, context)
